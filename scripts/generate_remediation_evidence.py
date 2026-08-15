"""Generate sanitized AUD-R1 evidence for the Gate-5 remediation (offline).

Produces the two required remediation evidence classes WITHOUT a live QMT
connection (AUD-R1-004 classification: OFFLINE_SYNTHETIC_FIXTURES):

* zero-real-position scenario;
* non-zero real/Core-position scenario;
* settlement-policy (T+1) behavior;
* explicit RAW/ADJUSTED basis behavior.

Output goes to ``work/reports/shadow/remediation-evidence/`` as JSON, fully
sanitized (no paths, ports, accounts, cash, or holdings).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tgrid.models import GlobalConfig, SymbolConfig
from tgrid.shadow import (
    ShadowEngine,
    build_shadow_reports,
    fetch_bars,
)
from tgrid.shadow.settlement import SETTLE_T1, SettlementPolicy
from tgrid.strategy.bars import Bar, SessionWindow
from tgrid.strategy.engine import AccumulateStrategy

EVIDENCE_CLASS = "OFFLINE_SYNTHETIC_FIXTURES"
OUT = Path(__file__).resolve().parents[1] / "work" / "reports" / "shadow" / "remediation-evidence"


def _global(**overrides):
    cfg = dict(
        live_trading=False, database="data/tgrid.db", log_dir="logs",
        bar_period="5m", order_timeout_seconds=120, skip_open_minutes=15,
        skip_close_minutes=15, volatility_halt_atr=2.5,
        minimum_cash_buffer=50000.0,
    )
    cfg.update(overrides)
    return GlobalConfig(**cfg)


def _symbol(**overrides):
    cfg = dict(
        enabled=True, mode="ACCUMULATE", core_qty=600, target_qty=1100,
        t_unit=100, lot_size=100, price_tick=0.001, max_t_lots=2,
        max_t_capital=200000.0, anchor="VWAP20", atr_period=14, atr_k=1.2,
        min_grid=0.004, max_grid=0.012, exit_multiple=1.15,
    )
    cfg.update(overrides)
    return SymbolConfig(**cfg)


SESSION = SessionWindow(570, 900, lunch_start=690, lunch_end=780)


def _daily_bars(close=440.0, high=446.0, low=434.0, n=40, volume=1000):
    bars = []
    for i in range(n):
        day = 1 + i // 2
        bars.append(
            Bar(
                symbol="510300.SH",
                time=f"2026-07-{day:02d}T15:00:00",
                open=close, high=high, low=low, close=close,
                volume=volume, kind="DAILY", price_basis="ADJUSTED",
            )
        )
    return bars


def _m5(day, minute, close, volume=1000):
    hours, mins = divmod(minute, 60)
    return Bar(
        symbol="510300.SH",
        time=f"{day}T{hours:02d}:{mins:02d}:00",
        open=close, high=close, low=close, close=close,
        volume=volume, kind="5m", price_basis="RAW",
    )


def _run_scenario(symbol_cfg, core_qty, *, held, can_use, label, out_name):
    strategy = AccumulateStrategy(symbol_cfg, _global(), session_window=SESSION)
    policy = SettlementPolicy(symbol="510300.SH", rule=SETTLE_T1)
    shadow = ShadowEngine(
        strategy, symbol="510300.SH", settlement_policy=policy, core_qty=core_qty,
    )
    shadow.begin_day(_daily_bars(), trade_date="2026-08-12")

    # Real strategic extra = held - core (only when held exceeds core).
    strategic_extra = max(0, held - core_qty)

    # Day 1: buy at the dip (T+1 locks the shares).  Gap 433 vs 440 is 1.6%,
    # below 2G (2.4%), so no volatility halt; 433 < Buy_1 (434.7) triggers.
    # Strategy view keeps Broker = Core + Strategic + OpenT: the real holding
    # decomposes into core + strategic, and the shadow BUY adds an open T lot
    # hypothetically, which the strategy tracks internally.
    shadow.on_bar(
        _m5("2026-08-12", 600, 433.0), now="2026-08-12T10:00:00",
        broker_position=held, can_use_qty=can_use, strategic_extra=strategic_extra,
        available_cash=500000.0, assume_fill_price=433.0,
        trade_date="2026-08-12",
    )
    # Day 1 same-session rebound: cannot sell the just-bought shares
    # (T+1 lock keeps effective sellable = real can_use).
    d_same = shadow.on_bar(
        _m5("2026-08-12", 605, 440.0), now="2026-08-12T10:05:00",
        broker_position=held, can_use_qty=can_use, strategic_extra=strategic_extra,
        available_cash=500000.0, assume_fill_price=440.0,
        trade_date="2026-08-12",
    )
    # Day 2: shares released (T+1); rebound may sell.  can_use gains the
    # released shadow shares; broker total stays the real holding.
    shadow.begin_day(_daily_bars(), trade_date="2026-08-13")
    shadow.on_bar(
        _m5("2026-08-13", 600, 436.0), now="2026-08-13T10:00:00",
        broker_position=held, can_use_qty=can_use,
        strategic_extra=strategic_extra, available_cash=500000.0,
        trade_date="2026-08-13",
    )
    d_next = shadow.on_bar(
        _m5("2026-08-13", 605, 440.0), now="2026-08-13T10:05:00",
        broker_position=held, can_use_qty=can_use,
        strategic_extra=strategic_extra, available_cash=500000.0,
        assume_fill_price=440.0, trade_date="2026-08-13",
    )

    # Real broker position stays as reported by the broker (no shadow fills
    # are real): reconciliation compares REAL broker vs REAL local expectation
    # (AUD-R1-003); shadow hypothetical activity is reported via shadow_delta.
    real_broker = held
    reports = build_shadow_reports(
        shadow, trade_date="2026-08-13",
        broker_positions={"510300.SH": real_broker},
        strategic_extras={"510300.SH": strategic_extra},
        open_t_positions={"510300.SH": 0},  # shadow activity is NOT real open T
    )
    reports["evidence"] = {
        "class": EVIDENCE_CLASS,
        "scenario": label,
        "settlement": {"symbol": "510300.SH", "rule": SETTLE_T1},
        "basis": {"daily": "ADJUSTED", "5m": "RAW"},
        "same_day_sell_kind": d_same.kind,
        "same_day_sell_reason": d_same.reason,
        "next_day_sell_kind": d_next.kind,
        "next_day_sell_reason": d_next.reason,
    }
    out_dir = OUT / out_name
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in reports.items():
        (out_dir / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"[evidence] {label}: same_day={d_same.kind}/{d_same.reason} "
          f"next_day={d_next.kind}/{d_next.reason} orders={len(reports['shadow_orders'])}")
    return reports


def main() -> int:
    # Scenario 1: zero real position (core 0, nothing held).
    _run_scenario(
        _symbol(core_qty=0, target_qty=100000), core_qty=0,
        held=0, can_use=0, label="zero-real-position", out_name="zero-position",
    )
    # Scenario 2: non-zero real/Core position (core 600, 700 held, 600 can_use).
    _run_scenario(
        _symbol(), core_qty=600,
        held=700, can_use=600, label="non-zero-real-core-position",
        out_name="nonzero-core-position",
    )
    print(f"[evidence] wrote sanitized evidence to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
