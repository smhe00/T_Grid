"""Gate 5 shadow-mode live runner (design §40; NODEA-R3-001..004).

Connects to the running MiniQMT (read-only, via the Gate 1 runtime bridge),
downloads history data with an EXPLICIT RAW/ADJUSTED basis, feeds REAL daily +
5m bars through the offline ACCUMULATE strategy (ShadowEngine), applies the
settlement (T+1) policy, and writes the four §40 deliverables plus the
separate shadow-delta and evidence-classification records.

Evidence class for this runner is ``REAL_QMT_HISTORICAL_REPLAY +
REAL_BROKER_SNAPSHOT``: real market data and a real broker position snapshot
are used, but intraday bars are replayed from downloaded history — this is
NOT wall-clock continuous live soak (AUD-R1-004).

It NEVER sends an order: execution is SHADOW (INV-009, ``live_trading_allowed``
is never touched).  Run with the repo venv that has xtquant:

    python scripts/gate5_shadow_live.py --config config/gate1_qmt.local.json \
        --strategy-config config/strategy.local.yaml \
        --out work/reports/shadow/2026-08-14 --date 2026-08-14 --run-days 10 \
        --factor-map config/factors.local.json

Fail-closed requirements (NODEA-R3-001..003):

* the strategy config must be a trusted local file, NOT config.example.yaml;
  the requested symbol must exist in it;
* settlement must be explicit in that config or via --settlement; no
  suffix-based default for an executable run;
* the same-day ADJUSTED->RAW factor must come from a trusted per-day source
  (--factor-map or an XtQuant dividend-factor adapter); no 1.0 default;
* session hours must come from an explicit market policy; only the validated
  A-share session is supported in this runner;
* real reconciliation decomposition (Core/Strategic/OpenT) is loaded from
  trusted local state; a missing component is UNKNOWN, never guessed zero.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from tgrid.shadow import (
    ShadowEngine,
    build_shadow_reports,
    fetch_bars,
)
from tgrid.shadow.daily_factor import (
    PROVENANCE_LOCAL_MAP,
    DailyFactorRegistry,
)
from tgrid.shadow.settlement import SettlementPolicy
from tgrid.strategy.bars import SessionWindow
from tgrid.strategy.engine import AccumulateStrategy

# Evidence classification (AUD-R1-004): historical replay of real QMT data
# plus a real broker position snapshot.  NOT wall-clock continuous live soak.
EVIDENCE_CLASS = "REAL_QMT_HISTORICAL_REPLAY + REAL_BROKER_SNAPSHOT"

# Explicit market-data basis (AUD-R1-001): daily indicator history is
# forward-adjusted (ADJUSTED); intraday execution reference is RAW.
DIVIDEND_DAILY = "front"
DIVIDEND_M5 = "none"

# Only the validated A-share session is supported (NODEA-R3-002): 09:30-11:30,
# 13:00-15:00, lunch 11:30-13:00.  HK session policy is not implemented; the
# runner rejects non-SH/SZ symbols rather than applying the wrong session.
A_SHARE_SESSION = SessionWindow(570, 900, lunch_start=690, lunch_end=780)
SUPPORTED_MARKETS = ("SH", "SZ")


def _load_strategy_config(config_path: str, code: str):
    """Load the TRUSTED strategy config; symbol must exist (NODEA-R3-002).

    ``config.example.yaml`` is never used as runtime strategy state.
    """
    from tgrid.config import load_config

    root = load_config(config_path)
    symbol_cfg = root.symbols.get(code)
    if symbol_cfg is None:
        raise SystemExit(
            f"[fail-closed] symbol {code!r} is not configured in trusted "
            f"strategy config {config_path}; refusing to run"
        )
    return symbol_cfg, root.global_config


def _load_factor_registry(factor_map_path: str, code: str, trading_days) -> DailyFactorRegistry:
    """Load the trusted per-day factor map (NODEA-R3-001).

    The map keys are ``"SYMBOL|YYYY-MM-DD"``; every replay day must have an
    entry, otherwise the runner fails closed (no 1.0 default).
    """
    path = Path(factor_map_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"[fail-closed] cannot read factor map {path}: {exc}") from None
    if not isinstance(raw, dict):
        raise SystemExit("[fail-closed] factor map must be a JSON object")
    factors = {}
    for key, value in raw.items():
        if not isinstance(key, str) or "|" not in key:
            raise SystemExit(f"[fail-closed] invalid factor key {key!r}")
        symbol, trade_date = key.split("|", 1)
        factors[(symbol, trade_date)] = value
    registry = DailyFactorRegistry(factors, provenance=PROVENANCE_LOCAL_MAP)
    # Every replay day must have a trusted factor.
    for day in trading_days:
        registry.factor_for(code, day)  # raises (fail closed) if missing
    return registry


def _load_reconciliation_state(state_path: str, code: str) -> dict:
    """Load trusted local decomposition for real reconciliation (NODEA-R3-003).

    Returns ``{"strategic_extra": int, "open_t_position": int}`` plus an
    optional ``"legacy_core_qty"`` field preserved ONLY so the caller can run
    the exact-equality guard (NODEB-P0-001).  The state provides only
    independently known StrategicExtra and persisted/open real T quantity;
    ``SymbolConfig.core_qty`` is the sole Core authority (NODEA-R4-002).  An
    optional legacy ``core_qty`` is NOT discarded before the mismatch check —
    the loader preserves it for :func:`_check_core_authority`, which requires
    exact equality with the configured Core and then discards it.

    A missing file fails closed; each component must be present (an unknown
    component is NOT treated as zero).
    """
    path = Path(state_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"[fail-closed] cannot read reconciliation state {path}: {exc}"
        ) from None
    entry = raw.get(code)
    if not isinstance(entry, dict):
        raise SystemExit(
            f"[fail-closed] no reconciliation state for {code!r}"
        )
    for field in ("strategic_extra", "open_t_position"):
        if field not in entry or type(entry[field]) is not int or entry[field] < 0:
            raise SystemExit(
                f"[fail-closed] reconciliation state for {code!r} is missing "
                f"non-negative int {field!r}"
            )
    result = {
        "strategic_extra": entry["strategic_extra"],
        "open_t_position": entry["open_t_position"],
    }
    # NODEB-P0-001: a legacy core_qty is preserved so the exact-equality guard
    # can run BEFORE any broker execution capability is invoked; it is never
    # used as a Core source.
    if "core_qty" in entry:
        result["legacy_core_qty"] = entry["core_qty"]
    return result


def _check_core_authority(reconciliation_state: dict, symbol_cfg, code: str) -> None:
    """Single-Core-authority guard (NODEA-R4-002 / NODEB-P0-001).

    ``symbol_cfg.core_qty`` is the sole Core source.  If the reconciliation
    state carries a legacy ``core_qty`` (preserved by the loader) it must
    exactly equal the configured value; a mismatch fails closed before any
    broker execution.  The state value is never used to construct the engine
    and is discarded after the check.
    """
    legacy = reconciliation_state.get("legacy_core_qty")
    if legacy is None:
        return  # preferred schema: no Core in reconciliation state
    if type(legacy) is not int or legacy != symbol_cfg.core_qty:
        raise SystemExit(
            f"[fail-closed] reconciliation-state legacy core_qty {legacy!r} does "
            f"not equal SymbolConfig.core_qty {symbol_cfg.core_qty!r}; "
            "SymbolConfig.core_qty is the sole Core authority"
        )


def _strict_prior_daily_bars(daily, trade_date: str):
    """Daily indicator history STRICTLY BEFORE ``trade_date`` (NODEA-R4-001).

    Design §9: Anchor/ATR are computed before market open and frozen for the
    day, so a replay for day D may only use completed daily bars with
    ``bar_date < D``.  The day-D daily bar (a 15:00 print) is future
    information at the 09:xx decision point and must never enter D's basis.
    """
    if type(trade_date) is not str or trade_date == "":
        raise SystemExit("[fail-closed] trade_date must be a non-empty string")
    prior = [bar for bar in daily if bar.time[:10] < trade_date]
    return prior


def _file_sha256(path: str) -> str:
    """SHA-256 of a trusted input file (evidence binding, NODEA-R4-003)."""
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_of_files(*paths: str) -> str:
    """Combined SHA-256 of the implementation files backing this run."""
    import hashlib

    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.encode("utf-8"))
        digest.update(_file_sha256(path).encode("utf-8"))
    return digest.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Gate 5 shadow-mode live runner")
    parser.add_argument("--config", required=True, help="gate1_qmt.local.json path")
    parser.add_argument("--strategy-config", required=True,
                        help="trusted strategy YAML config (never config.example.yaml)")
    parser.add_argument("--factor-map", required=True,
                        help="trusted per-day ADJUSTED->RAW factor JSON map")
    parser.add_argument("--reconciliation-state", required=True,
                        help="trusted local Core/Strategic/OpenT JSON state")
    parser.add_argument("--out", required=True, help="output directory for the reports")
    parser.add_argument("--date", required=True, help="last trade date YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=30, help="daily history window (anchor/ATR)")
    parser.add_argument("--code", default=None, help="symbol (defaults to gate1 config stock_code)")
    parser.add_argument("--run-days", type=int, default=1,
                        help="number of consecutive trading days to shadow (design 40: >= 5)")
    parser.add_argument("--settlement", default=None,
                        help="explicit settlement rule T0/T1 (required unless in strategy config)")
    args = parser.parse_args(argv)

    from tgrid.integrations.qmt_gate1_runtime import (
        _OpaqueAccount,
        _real_stock_account_factory,
        _real_trader_factory,
        _real_xtconstant_values,
        _real_xtdata,
        load_account_binding,
        load_gate1_config,
        load_runtime_config,
        ReadOnlyQmtGate1TraderBridge,
    )

    gate1 = load_gate1_config(args.config)
    runtime = load_runtime_config(
        gate1.runtime_config_path, environment=gate1.environment
    )
    binding = load_account_binding(
        gate1.account_binding_path,
        environment=gate1.environment,
        qmt_path=runtime.qmt_path,
    )
    code = args.code or gate1.stock_code

    # NODEA-R3-002: market restriction + explicit settlement, no suffix guess.
    if not code.endswith(SUPPORTED_MARKETS):
        raise SystemExit(
            f"[fail-closed] runner supports only {SUPPORTED_MARKETS}; "
            f"got {code!r}. HK session policy is not implemented."
        )
    symbol_cfg, global_cfg = _load_strategy_config(args.strategy_config, code)
    if args.settlement is not None:
        settlement_rule = args.settlement
    else:
        settlement_rule = getattr(symbol_cfg, "settlement_rule", None)
        if settlement_rule is None:
            raise SystemExit(
                f"[fail-closed] no explicit settlement rule for {code!r}; "
                "pass --settlement T0|T1"
            )
    settlement = SettlementPolicy(symbol=code, rule=settlement_rule)

    # 1. Real market data with explicit basis (AUD-R1-001).
    xtdata = _real_xtdata()
    end = args.date.replace("-", "")
    start_daily = "20260101"
    start_m5 = "20260801"
    try:
        xtdata.download_history_data(code, period="1d", start_time=start_daily, end_time=end)
        xtdata.download_history_data(code, period="5m", start_time=start_m5, end_time=end)
    except Exception as exc:  # noqa: BLE001 - reported, not fatal
        print(f"[warn] history download: {exc}", file=sys.stderr)

    daily, daily_binding = fetch_bars(
        xtdata, code=code, period="1d", start_time=start_daily, end_time=end,
        dividend_type=DIVIDEND_DAILY,
    )
    m5, m5_binding = fetch_bars(
        xtdata, code=code, period="5m", start_time=start_m5, end_time=end,
        dividend_type=DIVIDEND_M5,
    )
    print(f"[shadow] {code}: {len(daily)} daily bars ({daily_binding.price_basis}), "
          f"{len(m5)} 5m bars ({m5_binding.price_basis}); evidence={EVIDENCE_CLASS}")

    # 2. Real broker positions via the Gate 1 read-only trader bridge.
    trader = _real_trader_factory(str(runtime.qmt_path))
    security_type, status_ok = _real_xtconstant_values()
    token = _OpaqueAccount()
    bridge = ReadOnlyQmtGate1TraderBridge(
        trader=trader, security_account_type=security_type,
        account_status_ok=status_ok,
        stock_account_factory=_real_stock_account_factory(),
        binding=binding, token=token,
    )
    bridge.start()
    bridge.connect()
    bridge.subscribe(token)
    asset = bridge.query_stock_asset(token)
    positions = list(bridge.query_stock_positions(token))
    held = 0
    can_use = 0
    for pos in positions:
        if getattr(pos, "stock_code", None) == code:
            held = int(getattr(pos, "volume", 0) or 0)
            can_use = int(getattr(pos, "can_use_volume", 0) or 0)
    cash = float(getattr(asset, "cash", 0.0) or 0.0)
    bridge.stop()
    print(f"[shadow] real broker: {code} held={held} can_use={can_use}")

    # 3. Trusted reconciliation decomposition (NODEA-R3-003): loaded from an
    #    explicit local state file, never inferred from the broker residual.
    rec_state = _load_reconciliation_state(args.reconciliation_state, code)
    # NODEA-R4-002: SymbolConfig.core_qty is the sole Core authority; any
    # core_qty carried in the state must match exactly (else fail closed).
    _check_core_authority(rec_state, symbol_cfg, code)

    # 4. Strategy + shadow engine (pure offline, fed with real bars).
    #    NODEA-R4-002: SymbolConfig.core_qty is the SOLE Core authority.
    strategy = AccumulateStrategy(
        symbol_cfg, global_cfg, session_window=A_SHARE_SESSION,
    )
    shadow = ShadowEngine(
        strategy, symbol=code, settlement_policy=settlement,
        core_qty=symbol_cfg.core_qty,
    )

    # 5. Feed 5m bars day by day (design §9: the anchor is frozen per trading
    #    day, never across days).  Trading days must advance monotonically
    #    (NODEA-R3-001).  Each day's indicator history is STRICTLY prior
    #    (NODEA-R4-001): never include day D's own daily bar.
    by_day: dict = defaultdict(list)
    for bar in m5:
        by_day[bar.time[:10]].append(bar)
    trading_days = sorted(by_day)
    if args.run_days > 1:
        trading_days = trading_days[-args.run_days:]
    factor_registry = _load_factor_registry(args.factor_map, code, trading_days)

    for day in trading_days:
        day_bars = _strict_prior_daily_bars(daily, day)
        if len(day_bars) == 0:
            raise SystemExit(
                f"[fail-closed] no strictly-prior daily bars for {day}; "
                "cannot compute a pre-market basis without look-ahead"
            )
        # NODEA-R3-001: trusted per-day factor; fail closed if absent.
        factor = factor_registry.factor_for(code, day)
        shadow.begin_day(
            day_bars, trade_date=day,
            adjusted_to_raw_factor=factor,
            daily_price_basis=daily_binding.price_basis,
        )
        for bar in by_day[day]:
            shadow.on_bar(
                bar,
                broker_position=held,
                can_use_qty=can_use,
                strategic_extra=rec_state["strategic_extra"],
                available_cash=cash,
                assume_fill_price=bar.close,
                trade_date=day,
            )

    # 6. Four deliverables + shadow delta + evidence classification.
    reports = build_shadow_reports(
        shadow, trade_date=args.date,
        broker_positions={code: held},
        strategic_extras={code: rec_state["strategic_extra"]},
        open_t_positions={code: rec_state["open_t_position"]},
    )
    reports["evidence"] = {
        "class": EVIDENCE_CLASS,
        "code": {
            "implementation_sha": _sha256_of_files(
                "scripts/gate5_shadow_live.py",
                "src/tgrid/shadow/engine.py",
                "src/tgrid/shadow/daily_factor.py",
                "src/tgrid/strategy/engine.py",
            ),
        },
        "basis": {
            "daily": {"dividend_type": DIVIDEND_DAILY,
                      "price_basis": daily_binding.price_basis},
            "5m": {"dividend_type": DIVIDEND_M5,
                   "price_basis": m5_binding.price_basis},
        },
        "factor_registry": factor_registry.sanitized_summary(),
        "factor_map_sha256": _file_sha256(args.factor_map),
        "reconciliation_state_sha256": _file_sha256(args.reconciliation_state),
        "strategy_config_sha256": _file_sha256(args.strategy_config),
        "settlement": {"symbol": settlement.symbol, "rule": settlement.rule},
        "reconciliation_source": {
            # NODEA-R4-002: Core is NOT in the reconciliation state; it comes
            # solely from SymbolConfig.  Only StrategicExtra and OpenT are
            # loaded from trusted local state.
            "core_authority": "SymbolConfig.core_qty",
            "strategic_extra_present": True,
            "open_t_position_present": True,
        },
        "run_days": len(trading_days),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("shadow_orders", "signal_log", "reconciliation",
                 "shadow_delta", "daily_report", "evidence"):
        payload = reports[name]
        (out / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"[shadow] wrote {len(trading_days)}-day evidence to {out}")
    print(json.dumps(reports["daily_report"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
