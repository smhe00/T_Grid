"""Tests for tgrid.strategy.grid (Gate 3, design §10–§11, §18.1)."""

import unittest

from tgrid.strategy.exceptions import StrategyInputError
from tgrid.strategy.grid import buy_level, exit_target_price, grid_pct, legalize_price


class TestGridPct(unittest.TestCase):
    def test_clips_to_min_when_volatility_low(self):
        self.assertAlmostEqual(
            grid_pct(0.01, atr_k=1.2, min_grid=0.04, max_grid=0.08),
            0.04, places=10,
        )

    def test_uses_atr_term_when_above_min(self):
        # 1.2 * 0.05 = 0.06 in [0.04, 0.08]
        self.assertAlmostEqual(
            grid_pct(0.05, atr_k=1.2, min_grid=0.04, max_grid=0.08),
            0.06, places=10,
        )

    def test_clips_to_max(self):
        # 1.2 * 0.1 = 0.12 > 0.08
        self.assertAlmostEqual(
            grid_pct(0.10, atr_k=1.2, min_grid=0.04, max_grid=0.08),
            0.08, places=10,
        )

    def test_zero_atr_degrades_to_min(self):
        self.assertAlmostEqual(
            grid_pct(0.0, atr_k=1.2, min_grid=0.04, max_grid=0.08),
            0.04, places=10,
        )

    def test_negative_atr_rejected(self):
        with self.assertRaises(StrategyInputError):
            grid_pct(-0.01, atr_k=1.2, min_grid=0.04, max_grid=0.08)

    def test_inverted_bounds_rejected(self):
        with self.assertRaises(StrategyInputError):
            grid_pct(0.05, atr_k=1.2, min_grid=0.08, max_grid=0.04)

    def test_non_positive_params_rejected(self):
        with self.assertRaises(StrategyInputError):
            grid_pct(0.05, atr_k=0.0, min_grid=0.04, max_grid=0.08)
        with self.assertRaises(StrategyInputError):
            grid_pct(0.05, atr_k=1.2, min_grid=0.0, max_grid=0.08)

    def test_nan_rejected(self):
        with self.assertRaises(StrategyInputError):
            grid_pct(float("nan"), atr_k=1.2, min_grid=0.04, max_grid=0.08)


class TestBuyLevel(unittest.TestCase):
    def test_geometric_levels(self):
        anchor, g = 440.0, 0.05
        b1 = buy_level(anchor, g, 1)
        b2 = buy_level(anchor, g, 2)
        self.assertAlmostEqual(b1, 440.0 * 0.95, places=10)
        self.assertAlmostEqual(b2, 440.0 * 0.95 ** 2, places=10)
        self.assertLess(b2, b1)
        self.assertLess(b1, anchor)

    def test_n_must_be_positive_int(self):
        with self.assertRaises(StrategyInputError):
            buy_level(440.0, 0.05, 0)
        with self.assertRaises(StrategyInputError):
            buy_level(440.0, 0.05, 1.5)
        with self.assertRaises(StrategyInputError):
            buy_level(440.0, 0.05, True)

    def test_anchor_positive(self):
        with self.assertRaises(StrategyInputError):
            buy_level(0.0, 0.05, 1)
        with self.assertRaises(StrategyInputError):
            buy_level(-10.0, 0.05, 1)

    def test_g_bounds(self):
        with self.assertRaises(StrategyInputError):
            buy_level(440.0, 0.0, 1)
        with self.assertRaises(StrategyInputError):
            buy_level(440.0, 1.0, 1)
        with self.assertRaises(StrategyInputError):
            buy_level(440.0, 1.5, 1)


class TestExitTargetPrice(unittest.TestCase):
    def test_exit_above_entry(self):
        target = exit_target_price(420.0, 0.05, 1.15)
        self.assertAlmostEqual(target, 420.0 * (1 + 0.05 * 1.15), places=10)
        self.assertGreater(target, 420.0)

    def test_exit_multiple_minimum_one(self):
        with self.assertRaises(StrategyInputError):
            exit_target_price(420.0, 0.05, 0.9)

    def test_entry_positive(self):
        with self.assertRaises(StrategyInputError):
            exit_target_price(0.0, 0.05, 1.15)
        with self.assertRaises(StrategyInputError):
            exit_target_price(-1.0, 0.05, 1.15)


class TestLegalizePrice(unittest.TestCase):
    def test_buy_floors(self):
        self.assertEqual(legalize_price(420.34, 0.2, side="BUY"), 420.2)
        self.assertEqual(legalize_price(420.0, 0.2, side="BUY"), 420.0)

    def test_sell_ceils(self):
        self.assertEqual(legalize_price(420.34, 0.2, side="SELL"), 420.4)
        self.assertEqual(legalize_price(420.0, 0.2, side="SELL"), 420.0)

    def test_invalid_side(self):
        with self.assertRaises(StrategyInputError):
            legalize_price(420.0, 0.2, side="MID")

    def test_invalid_tick(self):
        with self.assertRaises(StrategyInputError):
            legalize_price(420.0, 0.0, side="BUY")

    def test_non_finite_price(self):
        with self.assertRaises(StrategyInputError):
            legalize_price(float("nan"), 0.2, side="BUY")


if __name__ == "__main__":
    unittest.main()
