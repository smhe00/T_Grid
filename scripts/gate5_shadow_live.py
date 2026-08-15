"""Gate 5 shadow-mode live runner (design §40).

Connects to the running MiniQMT (read-only, via the Gate 1 runtime bridge),
downloads history data, feeds REAL daily + 5m bars through the offline
ACCUMULATE strategy (ShadowEngine), and writes the four §40 deliverables:

* Shadow Orders (WOULD_BUY / WOULD_SELL)
* Signal Log
* Reconciliation Report (shadow vs real broker positions)
* Daily Report

It NEVER sends an order: execution is SHADOW (INV-009, ``live_trading_allowed``
is never touched).  Run with the repo venv that has xtquant:

    python scripts/gate5_shadow_live.py --config config/gate1_qmt.local.json \
        --out work/reports/shadow/2026-08-14 --date 2026-08-14 --days 30

Notes:

* ``get_trading_calendar`` is not implemented by this QMT build ("function not
  realize"); the runner derives trading dates from ``get_trading_dates``.
* Intraday (5m) history must be downloaded first; the runner downloads the
  requested window, which is a read-only market-data acquisition (no orders).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tgrid.shadow import ShadowEngine, build_shadow_reports
from tgrid.strategy.bars import Bar, SessionWindow
from tgrid.strategy.engine import AccumulateStrategy


def _parse_iso_time(value) -> str:
    # xtdata timestamps look like 20260814093500 -> 2026-08-14T09:35:00
    text = str(value)
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 14:
        return "1970-01-01T00:00:00"
    return (
        f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}T"
        f"{digits[8:10]}:{digits[10:12]}:{digits[12:14]}"
    )


def _daily_bars(xtdata, code: str, start: str, end: str):
    data = xtdata.get_market_data_ex(
        ["open", "high", "low", "close", "volume"], [code],
        period="1d", start_time=start, end_time=end, count=-1,
    )
    frame = data.get(code)
    if frame is None or len(frame) == 0:
        return []
    bars = []
    for ts, row in frame.iterrows():
        bars.append(
            Bar(
                symbol=code, time=_parse_iso_time(ts),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
                volume=int(row["volume"]), kind="DAILY", price_basis="ADJUSTED",
            )
        )
    return bars


def _m5_bars(xtdata, code: str, start: str, end: str):
    data = xtdata.get_market_data_ex(
        ["open", "high", "low", "close", "volume"], [code],
        period="5m", start_time=start, end_time=end, count=-1,
    )
    frame = data.get(code)
    if frame is None or len(frame) == 0:
        return []
    bars = []
    for ts, row in frame.iterrows():
        bars.append(
            Bar(
                symbol=code, time=_parse_iso_time(ts),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
                volume=int(row["volume"]), kind="5m", price_basis="RAW",
            )
        )
    return bars


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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Gate 5 shadow-mode live runner")
    parser.add_argument("--config", required=True, help="gate1_qmt.local.json path")
    parser.add_argument("--out", required=True, help="output directory for the four reports")
    parser.add_argument("--date", required=True, help="shadow trade date YYYY-MM-DD (or --days run)")
    parser.add_argument("--days", type=int, default=30, help="daily history window (anchor/ATR)")
    parser.add_argument("--code", default=None, help="symbol (defaults to gate1 config stock_code)")
    parser.add_argument("--run-days", type=int, default=1,
                        help="number of consecutive trading days to shadow (design 40: >= 5)")
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

    # 1. Real market data (read-only acquisition).
    xtdata = _real_xtdata()
    end = args.date.replace("-", "")
    start_daily = "20260101"
    start_m5 = "20260801"
    try:
        xtdata.download_history_data(code, period="1d", start_time=start_daily, end_time=end)
        xtdata.download_history_data(code, period="5m", start_time=start_m5, end_time=end)
    except Exception as exc:  # noqa: BLE001 - reported, not fatal
        print(f"[warn] history download: {exc}", file=sys.stderr)

    daily = _daily_bars(xtdata, code, start_daily, end)
    m5 = _m5_bars(xtdata, code, start_m5, end)
    print(f"[shadow] {code}: {len(daily)} daily bars, {len(m5)} 5m bars")

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
    print(f"[shadow] real broker: {code} held={held} can_use={can_use} cash={cash}")

    # 3. Strategy + shadow engine (pure offline, fed with real bars).
    example_config = str(Path(args.config).parent / "config.example.yaml")
    symbol_cfg, global_cfg = _load_symbol_and_global(example_config, code)
    # A-share session: 09:30-11:30, 13:00-15:00 (lunch 11:30-13:00).
    strategy = AccumulateStrategy(
        symbol_cfg, global_cfg,
        session_window=SessionWindow(570, 900, lunch_start=690, lunch_end=780),
    )
    shadow = ShadowEngine(strategy, symbol=code)
    shadow.begin_day(daily, trade_date=args.date)

    # 4. Feed 5m bars day by day (design §9: the anchor is frozen per trading
    #    day, never across days).  For each trading day, recompute the daily
    #    basis from the daily history UP TO that day, then feed only that
    #    day's 5m bars with an effective position (real broker holding + shadow
    #    fills) so the Broker=Core+Strategic+OpenT decomposition stays valid
    #    (INV-005); the reconciliation report compares the shadow book against
    #    the REAL broker position and reports any drift.
    effective_position = held
    effective_can_use = can_use
    from collections import defaultdict

    by_day: dict = defaultdict(list)
    for bar in m5:
        by_day[bar.time[:10]].append(bar)
    trading_days = sorted(by_day)
    if args.run_days > 1:
        trading_days = trading_days[-args.run_days:]
    for index, day in enumerate(trading_days, start=1):
        # Daily history through this day (at least the last 20 bars for VWAP20).
        day_bars = daily[: len(daily) - (len(trading_days) - index)]
        shadow.begin_day(day_bars, trade_date=day)
        for bar in by_day[day]:
            shadow.on_bar(
                bar,
                broker_position=effective_position, can_use_qty=effective_can_use,
                strategic_extra=0, available_cash=cash,
                assume_fill_price=bar.close,
            )
            effective_position = held + shadow.shadow_position
            effective_can_use = held + shadow.shadow_position

    # 5. Four deliverables.
    reports = build_shadow_reports(
        shadow, trade_date=args.date, broker_positions={code: held}
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("shadow_orders", "signal_log", "reconciliation", "daily_report"):
        payload = reports[name]
        (out / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"[shadow] wrote 4 reports to {out}")
    print(json.dumps(reports["daily_report"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
