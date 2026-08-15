"""Audit Node A iteration 5 tests — NODEA-R4-001..002.

* NODEA-R4-001: replay uses only STRICTLY-PRIOR daily bars for day D's
  pre-market basis; changing D's daily OHLC/volume by an extreme amount must
  NOT change D's basis or any D intraday decision; boundary test proves the
  last prior completed bar is included and the current-day bar excluded.
* NODEA-R4-002: SymbolConfig.core_qty is the sole Core authority; a second
  Core from reconciliation state must match exactly or fail closed.
"""

import unittest

from tgrid.models import GlobalConfig, SymbolConfig
from tgrid.shadow.engine import ShadowEngine
from tgrid.shadow.settlement import SETTLE_T1, SettlementPolicy
from tgrid.strategy.bars import Bar, SessionWindow
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


def _daily_bars_for_days(days, close=440.0, high=446.0, low=434.0, volume=1000):
    """Daily bars with explicit dates (all ADJUSTED basis)."""
    bars = []
    for day in days:
        bars.append(
            Bar(
                symbol="510300.SH", time=f"{day}T15:00:00",
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


class TestNodeAR4001NoLookAhead(unittest.TestCase):
    """NODEA-R4-001: day-D basis must use only bars strictly before D."""

    DAYS = [f"2026-07-{d:02d}" for d in range(1, 21)] + ["2026-08-11", "2026-08-12"]

    def _basis_for(self, daily, day):
        strategy = AccumulateStrategy(_symbol(), _global(), session_window=SESSION)
        strategy.begin_day(
            daily, trade_date=day,
            adjusted_to_raw_factor=1.0, daily_price_basis="ADJUSTED",
        )
        return strategy.daily_basis

    def test_day_D_basis_ignores_day_D_bar(self):
        # Day 2026-08-12: its own daily bar (close 999999) must NOT affect the
        # pre-market basis; only strictly-prior bars count.
        prior = _daily_bars_for_days(self.DAYS[:-1])          # up to 08-11
        with_day = _daily_bars_for_days(self.DAYS)            # includes 08-12
        # Corrupt ONLY the 08-12 bar.
        with_day[-1] = Bar(
            symbol="510300.SH", time="2026-08-12T15:00:00",
            open=999999.0, high=999999.0, low=999999.0,
            close=999999.0, volume=999999, kind="DAILY",
            price_basis="ADJUSTED",
        )
        # 08-12 basis must be computed from strictly-prior bars.
        prior_basis = self._basis_for(prior, "2026-08-12")
        with_day_basis = self._basis_for(with_day, "2026-08-12")
        self.assertAlmostEqual(prior_basis.anchor, with_day_basis.anchor, places=6)
        self.assertAlmostEqual(prior_basis.previous_close,
                               with_day_basis.previous_close, places=6)
        # The last PRIOR bar (08-11, close 440) is the previous_close, not 999999.
        self.assertLess(with_day_basis.previous_close, 1000.0)

    def test_day_D_intraday_decision_ignores_day_D_daily(self):
        # The 08-12 intraday decision must be identical whether the 08-12
        # daily bar is normal or extreme (it is future information).
        normal_daily = _daily_bars_for_days(self.DAYS)
        corrupted = list(normal_daily)
        corrupted[-1] = Bar(
            symbol="510300.SH", time="2026-08-12T15:00:00",
            open=999999.0, high=999999.0, low=999999.0,
            close=999999.0, volume=999999, kind="DAILY",
            price_basis="ADJUSTED",
        )

        def decide(daily):
            strategy = AccumulateStrategy(_symbol(), _global(), session_window=SESSION)
            strategy.begin_day(
                daily, trade_date="2026-08-12",
                adjusted_to_raw_factor=1.0, daily_price_basis="ADJUSTED",
            )
            return strategy.on_bar(
                _m5("2026-08-12", 605, 217.0),
                broker_position=600, can_use_qty=600, strategic_extra=0,
                reserved_sell_qty=0, available_cash=500000.0,
                now="2026-08-12T10:05:00",
            )

        d_normal = decide(normal_daily)
        d_corrupt = decide(corrupted)
        self.assertEqual(d_normal.kind, d_corrupt.kind)
        self.assertEqual(d_normal.reason, d_corrupt.reason)

    def test_runner_strict_prior_helper(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "gate5_shadow_live", "scripts/gate5_shadow_live.py"
        )
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except SystemExit:
            pass
        daily = _daily_bars_for_days(["2026-08-10", "2026-08-11", "2026-08-12"])
        prior = module._strict_prior_daily_bars(daily, "2026-08-12")
        self.assertEqual(len(prior), 2)
        self.assertEqual(prior[0].time[:10], "2026-08-10")
        self.assertEqual(prior[1].time[:10], "2026-08-11")
        # The 08-12 bar is excluded (no look-ahead).
        self.assertNotIn("2026-08-12", [b.time[:10] for b in prior])


class TestNodeAR4002SingleCoreAuthority(unittest.TestCase):
    """NODEA-R4-002: SymbolConfig.core_qty is the sole Core source."""

    def _shadow(self, core_qty=600):
        strategy = AccumulateStrategy(_symbol(), _global(), session_window=SESSION)
        return ShadowEngine(
            strategy, symbol="510300.SH", core_qty=core_qty,
            settlement_policy=SettlementPolicy(symbol="510300.SH", rule=SETTLE_T1),
        )

    def test_engine_uses_symbol_config_core(self):
        # ShadowEngine constructed with symbol_cfg.core_qty=600; reconciliation
        # expected = core 600 + strategic + openT.
        shadow = self._shadow(core_qty=600)
        row = shadow.reconcile(700, strategic_extra=100, open_t_lot_position=0)
        self.assertTrue(row.reconciled)
        self.assertEqual(row.local_expected_position, 700)

    def test_runner_core_authority_check(self):
        # The runner's _check_core_authority must fail closed when the state
        # carries a core_qty that differs from SymbolConfig.core_qty.
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "gate5_shadow_live", "scripts/gate5_shadow_live.py"
        )
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except SystemExit:
            pass
        symbol_cfg = _symbol(core_qty=600)
        # Matching core is accepted and discarded.
        module._check_core_authority(
            {"strategic_extra": 100, "open_t_position": 0, "core_qty": 600},
            symbol_cfg, "510300.SH",
        )
        # Mismatched core fails closed.
        with self.assertRaises(SystemExit):
            module._check_core_authority(
                {"strategic_extra": 100, "open_t_position": 0, "core_qty": 700},
                symbol_cfg, "510300.SH",
            )

    def test_state_without_core_is_preferred(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "gate5_shadow_live", "scripts/gate5_shadow_live.py"
        )
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except SystemExit:
            pass
        # No core_qty in the state: _check_core_authority returns silently.
        module._check_core_authority(
            {"strategic_extra": 100, "open_t_position": 0},
            _symbol(core_qty=600), "510300.SH",
        )


if __name__ == "__main__":
    unittest.main()
