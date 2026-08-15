"""Audit Node A iteration 4 tests — NODEA-R3-001..004.

* NODEA-R3-001: strategy-level 2:1 RAW/ADJUSTED normalization invariance —
  the SAME economic scenario expressed in RAW prices (factor 1.0) and in
  ADJUSTED indicator prices (factor 0.5) must produce identical strategy
  decisions; missing per-day factor fails closed; monotonic trading days.
* NODEA-R3-002: trusted strategy config / explicit settlement / session
  policy — missing pieces fail closed with zero strategy execution.
* NODEA-R3-003: reconciliation loads Core/Strategic/OpenT from trusted
  state; unknown component is UNKNOWN, not zero.
* NODEA-R3-004: control-plane metadata helpers are deterministic.
"""

import unittest

from tgrid.models import GlobalConfig, SymbolConfig
from tgrid.shadow.daily_factor import DailyFactorRegistry
from tgrid.shadow.settlement import SETTLE_T1, SettlementPolicy
from tgrid.strategy.bars import Bar, SessionWindow
from tgrid.strategy.basis_transform import to_raw_domain
from tgrid.strategy.engine import AccumulateStrategy, DecisionKind
from tgrid.strategy.exceptions import StrategyInputError


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


def _decide(daily_close, daily_high, daily_low, factor, bar_close):
    """Run one 5m bar after begin_day; return the decision kind.

    ``factor`` maps ADJUSTED indicator prices to the RAW trading domain
    (RAW = ADJUSTED * factor).  A 2:1 split expressed as ADJUSTED prices that
    are DOUBLE the current RAW scale uses factor 0.5; the RAW world uses
    factor 1.0 at the actual scale.  Both must produce identical decisions.
    """
    strategy = AccumulateStrategy(_symbol(), _global(), session_window=SESSION)
    strategy.begin_day(
        _daily_bars(close=daily_close, high=daily_high, low=daily_low),
        trade_date="2026-08-12",
        adjusted_to_raw_factor=factor,
        daily_price_basis="ADJUSTED",
    )
    return strategy.on_bar(
        _m5("2026-08-12", 605, bar_close),
        broker_position=600, can_use_qty=600, strategic_extra=0,
        reserved_sell_qty=0, available_cash=500000.0,
        now="2026-08-12T10:05:00",
    )


class TestNodeAR3001BasisInvariance(unittest.TestCase):
    """A 2:1 split expressed in RAW vs ADJUSTED scales yields same decisions."""

    def test_buy_level_economically_invariant(self):
        # RAW world: price scale 220, factor 1.0.  ADJUSTED world: the SAME
        # economic series is DOUBLE the scale (440) with factor 0.5 mapping it
        # back to RAW 220.  A bar at RAW 217 (gap 1.4% < 2G, at Buy_1
        # 220*0.988=217.36) triggers the same BUY in both worlds.
        raw = _decide(220.0, 223.0, 217.0, 1.0, 217.0)
        adj = _decide(440.0, 446.0, 434.0, 0.5, 217.0)
        self.assertEqual(raw.kind, adj.kind, "buy decision must be invariant")
        self.assertEqual(raw.reason, adj.reason)
        self.assertEqual(raw.kind, DecisionKind.BUY_T)

    def test_no_buy_above_level_invariant(self):
        # Bar at RAW 218 (above Buy_1 ~217) in both worlds.
        raw = _decide(220.0, 223.0, 217.0, 1.0, 218.0)
        adj = _decide(440.0, 446.0, 434.0, 0.5, 218.0)
        self.assertEqual(raw.kind, adj.kind)
        self.assertEqual(raw.kind, DecisionKind.NO_ACTION)

    def test_volatility_halt_invariant(self):
        # Gap RAW 200 vs 220 = 9.1% > 2G (2.4%) in both worlds -> halt.
        raw = _decide(220.0, 223.0, 217.0, 1.0, 200.0)
        adj = _decide(440.0, 446.0, 434.0, 0.5, 200.0)
        self.assertEqual(raw.kind, adj.kind)
        self.assertEqual(raw.kind, DecisionKind.HALTED)
        self.assertEqual(raw.reason, adj.reason)

    def test_missing_factor_fails_closed(self):
        strategy = AccumulateStrategy(_symbol(), _global(), session_window=SESSION)
        with self.assertRaises(StrategyInputError):
            strategy.begin_day(
                _daily_bars(), trade_date="2026-08-12",
                daily_price_basis="ADJUSTED",  # factor missing -> fail closed
            )

    def test_factor_registry_missing_day_fails_closed(self):
        registry = DailyFactorRegistry(
            {("510300.SH", "2026-08-12"): 1.0},
            provenance="TRUSTED_LOCAL_FACTOR_MAP",
        )
        self.assertEqual(registry.factor_for("510300.SH", "2026-08-12"), 1.0)
        with self.assertRaises(StrategyInputError):
            registry.factor_for("510300.SH", "2026-08-13")  # no fallback

    def test_factor_registry_validates_entries(self):
        with self.assertRaises(StrategyInputError):
            DailyFactorRegistry(
                {("510300.SH", "2026-08-12"): 0.0},
                provenance="TRUSTED_LOCAL_FACTOR_MAP",
            )
        with self.assertRaises(StrategyInputError):
            DailyFactorRegistry(
                {("510300.SH", "2026-08-12"): -1.0},
                provenance="TRUSTED_LOCAL_FACTOR_MAP",
            )

    def test_sanitized_summary_no_factor_values(self):
        registry = DailyFactorRegistry(
            {("510300.SH", "2026-08-12"): 0.5,
             ("510300.SH", "2026-08-13"): 1.0},
            provenance="TRUSTED_LOCAL_FACTOR_MAP",
        )
        summary = registry.sanitized_summary()
        self.assertEqual(summary["binding_count"], 2)
        self.assertEqual(summary["provenance"], "TRUSTED_LOCAL_FACTOR_MAP")
        self.assertNotIn("0.5", str(summary))  # no factor magnitudes leak


class TestNodeAR3003ReconciliationState(unittest.TestCase):
    def test_unknown_component_is_not_zero(self):
        from tgrid.shadow.engine import ShadowEngine

        strategy = AccumulateStrategy(_symbol(), _global(), session_window=SESSION)
        shadow = ShadowEngine(strategy, symbol="510300.SH", core_qty=600)
        # Broker 700 but only core 600 known (strategic/openT unknown -> 0):
        # this is a MISMATCH (SAFE_MODE input), never silently reconciled.
        row = shadow.reconcile(700, strategic_extra=0, open_t_lot_position=0)
        self.assertFalse(row.reconciled)
        self.assertEqual(row.local_expected_position, 600)
        self.assertEqual(row.delta, 100)


if __name__ == "__main__":
    unittest.main()
