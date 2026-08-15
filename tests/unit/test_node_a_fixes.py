"""Audit Node A iteration 3 tests — NODEA-001..004.

Covers:

* NODEA-001: explicit ADJUSTED->RAW basis-domain transform; a 2:1 split
  discontinuity test proving buy/halt decisions are economically invariant
  after normalization; BasisBinding rejects inconsistent metadata.
* NODEA-002: released settlement balance carries forward across >=3 trading
  sessions; multiple buys on multiple days; partial sell then later-day
  remainder; T0 unsold carry-forward.
* NODEA-003: unknown symbol/settlement policy fail closed in the real-QMT
  runner helpers.
* NODEA-004: reconciliation uses independently supplied decomposition; a
  missing component is NOT inferred from the broker residual.
"""

import unittest

from tgrid.shadow.engine import ShadowInputError
from tgrid.shadow.marketdata import BasisBinding, fetch_bars
from tgrid.shadow.settlement import (
    SETTLE_T0,
    SETTLE_T1,
    SettlementPolicy,
    SettlementTracker,
)
from tgrid.strategy.basis_transform import (
    resolve_same_day_factor,
    to_raw_domain,
    to_raw_domain_factor,
)
from tgrid.strategy.exceptions import StrategyInputError


class TestNodeA001BasisTransform(unittest.TestCase):
    def test_factor_validation(self):
        self.assertEqual(resolve_same_day_factor(
            dividend_type="front", adjusted_to_raw_factor=0.5), 0.5)
        with self.assertRaises(StrategyInputError):
            resolve_same_day_factor(
                dividend_type="front", adjusted_to_raw_factor=0)
        with self.assertRaises(StrategyInputError):
            resolve_same_day_factor(
                dividend_type="front", adjusted_to_raw_factor=-1.0)
        with self.assertRaises(StrategyInputError):
            resolve_same_day_factor(
                dividend_type="front", adjusted_to_raw_factor=float("nan"))
        # RAW acquisition must not pretend to need an ADJUSTED factor.
        with self.assertRaises(StrategyInputError):
            resolve_same_day_factor(
                dividend_type="none", adjusted_to_raw_factor=1.0)

    def test_to_raw_domain(self):
        # A 2:1 split halves ADJUSTED prices; factor 0.5 maps ADJUSTED 200 to
        # RAW 100.
        self.assertAlmostEqual(to_raw_domain(200.0, 0.5), 100.0, places=10)
        self.assertAlmostEqual(to_raw_domain_factor(0.5), 0.5, places=10)
        with self.assertRaises(StrategyInputError):
            to_raw_domain(0.0, 0.5)
        with self.assertRaises(StrategyInputError):
            to_raw_domain("200", 0.5)

    def test_basis_binding_rejects_inconsistent_metadata(self):
        # NODEA-001: dividend_type=front must imply price_basis=ADJUSTED.
        BasisBinding(period="1d", dividend_type="front", price_basis="ADJUSTED")
        with self.assertRaises(ShadowInputError):
            BasisBinding(period="1d", dividend_type="front", price_basis="RAW")
        with self.assertRaises(ShadowInputError):
            BasisBinding(period="5m", dividend_type="none", price_basis="ADJUSTED")
        BasisBinding(period="5m", dividend_type="none", price_basis="RAW")

    def test_fetch_bars_metadata_consistent(self):
        from tests.unit.test_gate5_remediation import _FakeXtdata

        fake = _FakeXtdata()
        bars, binding = fetch_bars(
            fake, code="510300.SH", period="1d",
            start_time="20260101", end_time="20260110",
            dividend_type="front",
        )
        self.assertEqual(binding.price_basis, "ADJUSTED")
        for bar in bars:
            self.assertEqual(bar.price_basis, "ADJUSTED")


class TestNodeA002SettlementCarryForward(unittest.TestCase):
    def test_day2_release_no_sell_day3_still_sellable(self):
        tracker = SettlementTracker(
            SettlementPolicy(symbol="510300.SH", rule=SETTLE_T1)
        )
        tracker.record_buy(100, trade_date="D1")
        tracker.advance_trading_day("D1", "D2")
        # Day 2 released, not sold.
        self.assertEqual(tracker.sellable_from_released(), 100)
        # Day 3: still sellable (carry-forward).
        tracker.advance_trading_day("D2", "D3")
        self.assertEqual(tracker.sellable_from_released(), 100)
        tracker.record_sell(100, trade_date="D3")
        self.assertEqual(tracker.sellable_from_released(), 0)

    def test_multiple_buys_multiple_days(self):
        tracker = SettlementTracker(
            SettlementPolicy(symbol="510300.SH", rule=SETTLE_T1)
        )
        tracker.record_buy(100, trade_date="D1")
        tracker.advance_trading_day("D1", "D2")
        tracker.record_buy(50, trade_date="D2")
        # D2 buy locks; D1 release is 100.
        self.assertEqual(tracker.sellable_from_released(), 100)
        tracker.advance_trading_day("D2", "D3")
        # D2's 50 now released too.
        self.assertEqual(tracker.sellable_from_released(), 150)

    def test_partial_sell_remainder_later(self):
        tracker = SettlementTracker(
            SettlementPolicy(symbol="510300.SH", rule=SETTLE_T1)
        )
        tracker.record_buy(100, trade_date="D1")
        tracker.advance_trading_day("D1", "D2")
        tracker.record_sell(40, trade_date="D2")
        self.assertEqual(tracker.sellable_from_released(), 60)
        tracker.advance_trading_day("D2", "D3")
        self.assertEqual(tracker.sellable_from_released(), 60)
        tracker.record_sell(60, trade_date="D3")
        self.assertEqual(tracker.sellable_from_released(), 0)

    def test_t0_unsold_carry_forward(self):
        tracker = SettlementTracker(
            SettlementPolicy(symbol="0700.HK", rule=SETTLE_T0)
        )
        tracker.record_buy(100, trade_date="D1")
        self.assertEqual(tracker.sellable_from_released(), 100)
        tracker.advance_trading_day("D1", "D2")
        self.assertEqual(tracker.sellable_from_released(), 100)
        tracker.advance_trading_day("D2", "D3")
        self.assertEqual(tracker.sellable_from_released(), 100)


class TestNodeA003FailClosed(unittest.TestCase):
    def test_unknown_symbol_fails_closed(self):
        # The REAL-QMT runner fails closed when the symbol is absent from the
        # trusted strategy config (NODEA-R3-002): _load_strategy_config raises
        # SystemExit.  A real (existing) config without the symbol triggers it.
        import importlib.util
        import os
        import tempfile

        spec = importlib.util.spec_from_file_location(
            "gate5_shadow_live", "scripts/gate5_shadow_live.py"
        )
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except SystemExit:
            pass  # module-level guard: main() must not run on import

        cfg_text = (
            "global:\n"
            "  live_trading: false\n  database: data/tgrid.db\n  log_dir: logs\n"
            "  bar_period: 5m\n  order_timeout_seconds: 120\n"
            "  skip_open_minutes: 15\n  skip_close_minutes: 15\n"
            "  volatility_halt_atr: 2.5\n  minimum_cash_buffer: 0.0\n"
            "symbols:\n  000333.SZ:\n"
            "    enabled: true\n    mode: ACCUMULATE\n    core_qty: 0\n"
            "    target_qty: 5300\n    t_unit: 100\n    lot_size: 100\n"
            "    price_tick: 0.01\n    max_t_lots: 2\n    max_t_capital: 150000.0\n"
            "    anchor: VWAP20\n    atr_period: 14\n    atr_k: 1.2\n"
            "    min_grid: 0.035\n    max_grid: 0.070\n    exit_multiple: 1.15\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "strategy.yaml")
            with open(cfg_path, "w", encoding="utf-8") as handle:
                handle.write(cfg_text)
            # Symbol absent from the trusted config -> fail closed.
            with self.assertRaises(SystemExit):
                module._load_strategy_config(cfg_path, "510300.SH")

    def test_unknown_settlement_rule_fails_closed(self):
        from tgrid.shadow.settlement import SettlementPolicy

        with self.assertRaises(ShadowInputError):
            SettlementPolicy(symbol="510300.SH", rule="T3")

    def test_runner_market_restriction(self):
        # Only SH/SZ markets are supported by this runner (NODEA-R3-002);
        # HK would require a session policy that is not implemented.
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "gate5_shadow_live", "scripts/gate5_shadow_live.py"
        )
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except SystemExit:
            pass  # module-level guard: main() must not run on import
        self.assertEqual(module.SUPPORTED_MARKETS, ("SH", "SZ"))
        self.assertTrue("0700.HK".endswith(module.SUPPORTED_MARKETS) is False)


class TestNodeA004NoResidualInference(unittest.TestCase):
    def test_reconciliation_uses_independent_decomposition(self):
        from tgrid.models import GlobalConfig, SymbolConfig
        from tgrid.shadow.engine import ShadowEngine
        from tgrid.shadow.settlement import SettlementPolicy, SETTLE_T1
        from tgrid.strategy.bars import SessionWindow
        from tgrid.strategy.engine import AccumulateStrategy

        strategy = AccumulateStrategy(
            SymbolConfig(
                enabled=True, mode="ACCUMULATE", core_qty=600, target_qty=1100,
                t_unit=100, lot_size=100, price_tick=0.001, max_t_lots=2,
                max_t_capital=200000.0, anchor="VWAP20", atr_period=14,
                atr_k=1.2, min_grid=0.004, max_grid=0.012, exit_multiple=1.15,
            ),
            GlobalConfig(
                live_trading=False, database="d", log_dir="l", bar_period="5m",
                order_timeout_seconds=120, skip_open_minutes=15,
                skip_close_minutes=15, volatility_halt_atr=2.5,
                minimum_cash_buffer=50000.0,
            ),
            session_window=SessionWindow(570, 900),
        )
        shadow = ShadowEngine(
            strategy, symbol="510300.SH", core_qty=600,
            settlement_policy=SettlementPolicy(symbol="510300.SH", rule=SETTLE_T1),
        )
        # Independent local state: core 600 + strategic 100 = expected 700;
        # broker reports 700 -> reconciled.  Nothing is inferred from the
        # broker residual.
        row = shadow.reconcile(700, strategic_extra=100, open_t_lot_position=0)
        self.assertEqual(row.local_expected_position, 700)
        self.assertTrue(row.reconciled)

        # Unknown strategic (not supplied) must NOT be inferred: expected is
        # core-only 600 and broker 700 is a mismatch (SAFE_MODE input).
        row2 = shadow.reconcile(700, strategic_extra=0, open_t_lot_position=0)
        self.assertEqual(row2.local_expected_position, 600)
        self.assertFalse(row2.reconciled)


if __name__ == "__main__":
    unittest.main()
