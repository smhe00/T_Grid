"""Tests for tgrid.strategy.corporate_action (Gate 3, design §7.1)."""

import unittest

from tgrid.strategy.bars import Bar
from tgrid.strategy.corporate_action import (
    CorporateActionFactor,
    PriceBasis,
    adjust_historical_prices,
)
from tgrid.strategy.exceptions import StrategyInputError
from tgrid.strategy.indicators import atr14, vwap20


def _bar(close, time, high=None, low=None, volume=1000):
    high = high if high is not None else close
    low = low if low is not None else close
    return Bar(
        symbol="0700.HK", time=time, open=close, high=high, low=low,
        close=close, volume=volume, kind="DAILY",
    )


class TestCorporateActionFactor(unittest.TestCase):
    def test_valid_factor(self):
        factor = CorporateActionFactor(
            action_type="SPLIT", effective_time="2026-08-12T00:00:00",
            price_factor=0.5, qty_factor=2.0,
        )
        self.assertEqual(factor.action_type, "SPLIT")
        self.assertEqual(factor.price_factor, 0.5)

    def test_non_positive_factors_rejected(self):
        for price_factor, qty_factor in ((0.0, 1.0), (-1.0, 1.0), (1.0, 0.0)):
            with self.assertRaises(StrategyInputError):
                CorporateActionFactor(
                    action_type="X", effective_time="2026-08-12T00:00:00",
                    price_factor=price_factor, qty_factor=qty_factor,
                )

    def test_nan_rejected(self):
        with self.assertRaises(StrategyInputError):
            CorporateActionFactor(
                action_type="X", effective_time="2026-08-12T00:00:00",
                price_factor=float("nan"), qty_factor=1.0,
            )

    def test_empty_action_rejected(self):
        with self.assertRaises(StrategyInputError):
            CorporateActionFactor(
                action_type="", effective_time="2026-08-12T00:00:00",
                price_factor=0.5, qty_factor=2.0,
            )

    def test_factor_is_frozen(self):
        factor = CorporateActionFactor(
            action_type="SPLIT", effective_time="2026-08-12T00:00:00",
            price_factor=0.5, qty_factor=2.0,
        )
        with self.assertRaises(Exception):
            factor.price_factor = 0.9  # frozen


class TestAdjustHistoricalPrices(unittest.TestCase):
    def setUp(self):
        self.pre = [
            _bar(100.0, f"2026-07-{i + 1:02d}T00:00:00")
            for i in range(16)
        ]
        self.post = [
            _bar(50.0, f"2026-08-{i + 1:02d}T00:00:00")
            for i in range(8)
        ]
        self.factor = CorporateActionFactor(
            action_type="SPLIT", effective_time="2026-08-01T00:00:00",
            price_factor=0.5, qty_factor=2.0,
        )

    def test_pre_action_bars_scaled_to_adjusted(self):
        adjusted = adjust_historical_prices(self.pre + self.post, self.factor)
        self.assertEqual(len(adjusted), 24)
        # pre-action prices halved, volume doubled
        self.assertAlmostEqual(adjusted[0].close, 50.0, places=10)
        self.assertEqual(adjusted[0].volume, 2000)
        self.assertEqual(adjusted[0].price_basis, PriceBasis.ADJUSTED)
        # post-action prices unchanged on ADJUSTED basis
        self.assertAlmostEqual(adjusted[16].close, 50.0, places=10)
        self.assertEqual(adjusted[16].volume, 1000)
        self.assertEqual(adjusted[16].price_basis, PriceBasis.ADJUSTED)

    def test_input_never_mutated(self):
        before = [self.pre[0], self.post[0]]
        snapshot = (before[0].close, before[0].volume, before[1].close, before[1].volume)
        adjust_historical_prices(before, self.factor)
        self.assertEqual(before[0].close, snapshot[0])
        self.assertEqual(before[0].volume, snapshot[1])
        self.assertEqual(before[1].close, snapshot[2])
        self.assertEqual(before[1].volume, snapshot[3])

    def test_indicator_continuity_across_split(self):
        # A flat 100 price with a 1:2 split: the adjusted series must be
        # indistinguishable from a continuous series at the same adjusted
        # prices and adjusted share volumes (design §7.1 unified basis).
        bars = self.pre + self.post
        adjusted = adjust_historical_prices(bars, self.factor)
        flat = [
            _bar(50.0, b.time, volume=b.volume) for b in adjusted
        ]
        self.assertAlmostEqual(vwap20(adjusted), vwap20(flat), places=10)
        self.assertAlmostEqual(atr14(adjusted), atr14(flat), places=10)

    def test_rejects_non_bar_element(self):
        with self.assertRaises(StrategyInputError):
            adjust_historical_prices([1, 2], self.factor)

    def test_rejects_wrong_factor_type(self):
        with self.assertRaises(StrategyInputError):
            adjust_historical_prices(self.pre, {"price_factor": 0.5})

    def test_rejects_negative_adjusted_price(self):
        # Bar is BEFORE effective_time so it must be scaled; -5 * 0.5 < 0.
        bad = _bar(-5.0, "2026-07-15T00:00:00")
        with self.assertRaises(StrategyInputError):
            adjust_historical_prices([bad], self.factor)


if __name__ == "__main__":
    unittest.main()
