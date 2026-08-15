"""Gate 5 shadow-mode live runner (design §40; remediation AUD-R1-001..004).

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
        --out work/reports/shadow/2026-08-14 --date 2026-08-14 --run-days 10
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
from tgrid.shadow.settlement import SETTLE_T1, SettlementPolicy
from tgrid.strategy.bars import SessionWindow
from tgrid.strategy.engine import AccumulateStrategy

# Evidence classification (AUD-R1-004): historical replay of real QMT data
# plus a real broker position snapshot.  NOT wall-clock continuous live soak.
EVIDENCE_CLASS = "REAL_QMT_HISTORICAL_REPLAY + REAL_BROKER_SNAPSHOT"

# Explicit market-data basis (AUD-R1-001): daily indicator history is
# forward-adjusted (ADJUSTED); intraday execution reference is RAW.
DIVIDEND_DAILY = "front"
DIVIDEND_M5 = "none"


def _load_symbol_and_global(config_path: str, code: str):
    from tgrid.config import load_config

    root = load_config(config_path)
    symbol_cfg = root.symbols.get(code)
    if symbol_cfg is not None:
        return symbol_cfg, root.global_config
    # Fall back to a conservative default shape for the target symbol (the
    # design never hard-codes securities; this is only a demo fallback).
    from tgrid.models import SymbolConfig

    fallback = SymbolConfig(
        enabled=True, mode="ACCUMULATE", core_qty=0, target_qty=100000,
        t_unit=100, lot_size=100, price_tick=0.001, max_t_lots=2,
        max_t_capital=500000.0, anchor="VWAP20", atr_period=14, atr_k=1.2,
        min_grid=0.004, max_grid=0.012, exit_multiple=1.15,
    )
    return fallback, root.global_config


def _settlement_rule_for(code: str) -> str:
    """Explicit settlement rule per symbol (AUD-R1-002).

    A-share (SH/SZ equities and A-share ETFs) settle T+1; HK same-day.  The
    rule is explicit per symbol; unknown patterns fail closed in
    SettlementPolicy.  This mapping is the documented default and is
    overridable via ``--settlement``.
    """
    if code.endswith(".HK"):
        return "T0"
    return SETTLE_T1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Gate 5 shadow-mode live runner")
    parser.add_argument("--config", required=True, help="gate1_qmt.local.json path")
    parser.add_argument("--out", required=True, help="output directory for the reports")
    parser.add_argument("--date", required=True, help="last trade date YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=30, help="daily history window (anchor/ATR)")
    parser.add_argument("--code", default=None, help="symbol (defaults to gate1 config stock_code)")
    parser.add_argument("--run-days", type=int, default=1,
                        help="number of consecutive trading days to shadow (design 40: >= 5)")
    parser.add_argument("--settlement", default=None,
                        help="explicit settlement rule T0/T1 (default per symbol)")
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
    settlement_rule = args.settlement or _settlement_rule_for(code)
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
    # Do NOT print real account values to the report stream (AUD-R1-005); the
    # console may print only counts, and reports must be sanitized.
    print(f"[shadow] real broker: {code} held={held} can_use={can_use}")

    # 3. Strategy + shadow engine (pure offline, fed with real bars).
    example_config = str(Path(args.config).parent / "config.example.yaml")
    symbol_cfg, global_cfg = _load_symbol_and_global(example_config, code)
    # A-share session: 09:30-11:30, 13:00-15:00 (lunch 11:30-13:00).
    strategy = AccumulateStrategy(
        symbol_cfg, global_cfg,
        session_window=SessionWindow(570, 900, lunch_start=690, lunch_end=780),
    )
    shadow = ShadowEngine(
        strategy, symbol=code, settlement_policy=settlement,
        core_qty=symbol_cfg.core_qty,
    )
    shadow.begin_day(daily, trade_date=args.date)

    # 4. Feed 5m bars day by day (design §9: the anchor is frozen per trading
    #    day, never across days).  The strategy sees the REAL broker position
    #    plus the settlement-released shadow sellable (AUD-R1-002/-003); the
    #    hypothetical shadow position is tracked separately and reported as
    #    ``shadow_delta``, never mixed into the real reconciliation.
    by_day: dict = defaultdict(list)
    for bar in m5:
        by_day[bar.time[:10]].append(bar)
    trading_days = sorted(by_day)
    if args.run_days > 1:
        trading_days = trading_days[-args.run_days:]
    for index, day in enumerate(trading_days, start=1):
        day_bars = daily[: len(daily) - (len(trading_days) - index)]
        shadow.begin_day(day_bars, trade_date=day)
        for bar in by_day[day]:
            shadow.on_bar(
                bar,
                broker_position=held,
                can_use_qty=can_use,
                strategic_extra=0,
                available_cash=cash,
                assume_fill_price=bar.close,
                trade_date=day,
            )

    # 5. Four deliverables + shadow delta + evidence classification.
    reports = build_shadow_reports(
        shadow, trade_date=args.date,
        broker_positions={code: held},
        strategic_extras={code: 0},
        open_t_positions={code: 0},
    )
    reports["evidence"] = {
        "class": EVIDENCE_CLASS,
        "basis": {
            "daily": {"dividend_type": DIVIDEND_DAILY,
                      "price_basis": daily_binding.price_basis},
            "5m": {"dividend_type": DIVIDEND_M5,
                   "price_basis": m5_binding.price_basis},
        },
        "settlement": {"symbol": settlement.symbol, "rule": settlement.rule},
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
