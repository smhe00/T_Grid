"""Tests for tgrid.strategy.halts (Gate 3, design §28–§29)."""

import unittest

from tgrid.strategy.exceptions import StrategyInputError
from tgrid.strategy.halts import EventBlockRule, event_blocked, volatility_halt


class TestVolatilityHalt(unittest.TestCase):
    def test_daily_move_exceeds_atr_threshold(self):
        # move 5% > 2.5 * 1.5% = 3.75%
        self.assertTrue(
            volatility_halt(
                previous_close=100.0, current_price=105.0,
                atr_pct=0.015, halt_atr_k=2.5, grid_g=0.05,
            )
        )

    def test_daily_move_within_threshold(self):
        # move 3% < 3.75%
        self.assertFalse(
            volatility_halt(
                previous_close=100.0, current_price=103.0,
                atr_pct=0.015, halt_atr_k=2.5, grid_g=0.05,
            )
        )

    def test_gap_exceeds_2g(self):
        # gap 12% > 2 * 5% = 10%
        self.assertTrue(
            volatility_halt(
                previous_close=100.0, current_price=112.0,
                atr_pct=0.01, halt_atr_k=2.5, grid_g=0.05,
            )
        )

    def test_gap_within_2g(self):
        # gap 8% < 2 * 5% = 10%; ATR high enough that the daily-move rule
        # (2.5 * 5% = 12.5% > 8%) does not fire either.
        self.assertFalse(
            volatility_halt(
                previous_close=100.0, current_price=108.0,
                atr_pct=0.05, halt_atr_k=2.5, grid_g=0.05,
            )
        )

    def test_drop_also_halts(self):
        self.assertTrue(
            volatility_halt(
                previous_close=100.0, current_price=92.0,
                atr_pct=0.015, halt_atr_k=2.5, grid_g=0.05,
            )
        )

    def test_invalid_inputs(self):
        with self.assertRaises(StrategyInputError):
            volatility_halt(
                previous_close=0.0, current_price=100.0,
                atr_pct=0.01, halt_atr_k=2.5, grid_g=0.05,
            )
        with self.assertRaises(StrategyInputError):
            volatility_halt(
                previous_close=100.0, current_price=100.0,
                atr_pct=0.01, halt_atr_k=0.0, grid_g=0.05,
            )
        with self.assertRaises(StrategyInputError):
            volatility_halt(
                previous_close=100.0, current_price=100.0,
                atr_pct=0.01, halt_atr_k=2.5, grid_g=1.0,
            )
        with self.assertRaises(StrategyInputError):
            volatility_halt(
                previous_close=float("nan"), current_price=100.0,
                atr_pct=0.01, halt_atr_k=2.5, grid_g=0.05,
            )


class TestEventBlockRule(unittest.TestCase):
    def test_valid_rule(self):
        rule = EventBlockRule(
            events={"0700.HK": ("2026-08-12",)},
            block_before_days=1,
            block_after_days=1,
        )
        self.assertEqual(rule.events["0700.HK"], ("2026-08-12",))

    def test_default_window_days(self):
        rule = EventBlockRule(events={})
        self.assertEqual(rule.block_before_days, 1)
        self.assertEqual(rule.block_after_days, 1)

    def test_negative_days_rejected(self):
        with self.assertRaises(StrategyInputError):
            EventBlockRule(events={}, block_before_days=-1)

    def test_non_mapping_events_rejected(self):
        with self.assertRaises(StrategyInputError):
            EventBlockRule(events=[1, 2, 3])

    def test_bad_symbol_rejected(self):
        with self.assertRaises(StrategyInputError):
            EventBlockRule(events={123: ("2026-08-12",)})


class TestEventBlocked(unittest.TestCase):
    def test_inside_window(self):
        rule = EventBlockRule(events={"0700.HK": ("2026-08-12",)})
        self.assertTrue(event_blocked(rule, symbol="0700.HK", trade_date="2026-08-12"))
        self.assertTrue(event_blocked(rule, symbol="0700.HK", trade_date="2026-08-11"))
        self.assertTrue(event_blocked(rule, symbol="0700.HK", trade_date="2026-08-13"))

    def test_outside_window(self):
        rule = EventBlockRule(events={"0700.HK": ("2026-08-12",)})
        self.assertFalse(event_blocked(rule, symbol="0700.HK", trade_date="2026-08-10"))
        self.assertFalse(event_blocked(rule, symbol="0700.HK", trade_date="2026-08-14"))

    def test_other_symbol_not_blocked(self):
        rule = EventBlockRule(events={"0700.HK": ("2026-08-12",)})
        self.assertFalse(event_blocked(rule, symbol="000333.SZ", trade_date="2026-08-12"))

    def test_no_events_never_blocked(self):
        rule = EventBlockRule(events={})
        self.assertFalse(event_blocked(rule, symbol="0700.HK", trade_date="2026-08-12"))

    def test_wider_window(self):
        rule = EventBlockRule(
            events={"0700.HK": ("2026-08-12",)},
            block_before_days=3, block_after_days=3,
        )
        self.assertTrue(event_blocked(rule, symbol="0700.HK", trade_date="2026-08-09"))
        self.assertTrue(event_blocked(rule, symbol="0700.HK", trade_date="2026-08-15"))

    def test_invalid_inputs(self):
        rule = EventBlockRule(events={})
        with self.assertRaises(StrategyInputError):
            event_blocked(None, symbol="0700.HK", trade_date="2026-08-12")
        with self.assertRaises(StrategyInputError):
            event_blocked(rule, symbol="", trade_date="2026-08-12")
        with self.assertRaises(StrategyInputError):
            event_blocked(rule, symbol="0700.HK", trade_date="12-08-2026")

    def test_malformed_event_date_fails_closed(self):
        rule = EventBlockRule(events={"0700.HK": ("not-a-date",)})
        with self.assertRaises(StrategyInputError):
            event_blocked(rule, symbol="0700.HK", trade_date="2026-08-12")


if __name__ == "__main__":
    unittest.main()
