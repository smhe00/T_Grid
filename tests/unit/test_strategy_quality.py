"""Tests for tgrid.strategy.quality (Gate 3, design §26.2)."""

import unittest

from tgrid.strategy.bars import Bar, SessionWindow
from tgrid.strategy.exceptions import StrategyInputError
from tgrid.strategy.quality import BarQualityIssue, DataQualityGuard, check_bar_quality


def _bar(close=10.0, time="2026-08-12T10:25:00", volume=1000, high=None, low=None):
    high = high if high is not None else close
    low = low if low is not None else close
    return Bar(
        symbol="0700.HK", time=time, open=close, high=high, low=low,
        close=close, volume=volume, kind="5m",
    )


NOW = "2026-08-12T10:30:00"


class TestCheckBarQuality(unittest.TestCase):
    def test_clean_bar(self):
        issues = check_bar_quality(
            _bar(), None, expected_interval_seconds=300, now=NOW,
            max_stale_seconds=600,
        )
        self.assertEqual(issues, ())
    def test_stale_bar(self):
        issues = check_bar_quality(
            _bar(time="2026-08-12T09:00:00"), None,
            expected_interval_seconds=300, now=NOW, max_stale_seconds=600,
        )
        self.assertIn(BarQualityIssue.STALE, issues)

    def test_future_timestamp_suspect(self):
        issues = check_bar_quality(
            _bar(time="2026-08-12T11:00:00"), None,
            expected_interval_seconds=300, now=NOW, max_stale_seconds=600,
        )
        self.assertIn(BarQualityIssue.STALE, issues)

    def test_missing_bar(self):
        prev = _bar(time="2026-08-12T09:55:00")
        cur = _bar(time="2026-08-12T10:10:00")
        issues = check_bar_quality(
            cur, prev, expected_interval_seconds=300, now=NOW,
            max_stale_seconds=600,
        )
        # 15 min gap > 2 * 5 min
        self.assertIn(BarQualityIssue.MISSING, issues)

    def test_duplicate_bar(self):
        prev = _bar(time="2026-08-12T10:00:00")
        cur = _bar(time="2026-08-12T10:00:00")
        issues = check_bar_quality(
            cur, prev, expected_interval_seconds=300, now=NOW,
            max_stale_seconds=600,
        )
        self.assertIn(BarQualityIssue.DUPLICATE_BAR, issues)

    def test_out_of_order_bar(self):
        prev = _bar(time="2026-08-12T10:05:00")
        cur = _bar(time="2026-08-12T10:00:00")
        issues = check_bar_quality(
            cur, prev, expected_interval_seconds=300, now=NOW,
            max_stale_seconds=600,
        )
        self.assertIn(BarQualityIssue.OUT_OF_ORDER_BAR, issues)

    def test_price_invalid_high_lt_low(self):
        issues = check_bar_quality(
            _bar(high=9.0, low=11.0), None, expected_interval_seconds=300,
            now=NOW, max_stale_seconds=600,
        )
        self.assertIn(BarQualityIssue.PRICE_INVALID, issues)

    def test_price_invalid_non_positive(self):
        issues = check_bar_quality(
            _bar(close=-1.0, high=-1.0, low=-1.0), None,
            expected_interval_seconds=300, now=NOW, max_stale_seconds=600,
        )
        self.assertIn(BarQualityIssue.PRICE_INVALID, issues)

    def test_volume_invalid(self):
        issues = check_bar_quality(
            _bar(volume=-5), None, expected_interval_seconds=300, now=NOW,
            max_stale_seconds=600,
        )
        self.assertIn(BarQualityIssue.VOLUME_INVALID, issues)

    def test_suspension_zero_volume(self):
        issues = check_bar_quality(
            _bar(volume=0), None, expected_interval_seconds=300, now=NOW,
            max_stale_seconds=600,
        )
        self.assertIn(BarQualityIssue.SUSPENSION, issues)

    def test_non_bar_rejected(self):
        with self.assertRaises(StrategyInputError):
            check_bar_quality(
                "not a bar", None, expected_interval_seconds=300, now=NOW,
                max_stale_seconds=600,
            )

    def test_bad_parameters_rejected(self):
        with self.assertRaises(StrategyInputError):
            check_bar_quality(
                _bar(), None, expected_interval_seconds=0, now=NOW,
                max_stale_seconds=600,
            )
        with self.assertRaises(StrategyInputError):
            check_bar_quality(
                _bar(), None, expected_interval_seconds=300, now="bad",
                max_stale_seconds=600,
            )
        with self.assertRaises(StrategyInputError):
            check_bar_quality(
                _bar(), None, expected_interval_seconds=300, now=NOW,
                max_stale_seconds=-1,
            )


class TestDataQualityGuard(unittest.TestCase):
    def test_sequence_clean(self):
        guard = DataQualityGuard(expected_interval_seconds=300, max_stale_seconds=600)
        issues = guard.check(_bar(time="2026-08-12T10:25:00"), now=NOW)
        self.assertEqual(issues, ())
        issues = guard.check(_bar(time="2026-08-12T10:26:00"), now=NOW)
        self.assertEqual(issues, ())

    def test_sequence_detects_gap(self):
        guard = DataQualityGuard(expected_interval_seconds=300, max_stale_seconds=600)
        guard.check(_bar(time="2026-08-12T10:20:00"), now=NOW)
        issues = guard.check(_bar(time="2026-08-12T10:31:00"), now=NOW)
        # 11 min = 660s > 2 * 300 = 600s -> MISSING
        self.assertIn(BarQualityIssue.MISSING, issues)

    def test_guard_remembers_previous(self):
        guard = DataQualityGuard(expected_interval_seconds=300, max_stale_seconds=600)
        guard.check(_bar(time="2026-08-12T10:25:00"), now=NOW)
        issues = guard.check(_bar(time="2026-08-12T10:25:00"), now=NOW)
        self.assertIn(BarQualityIssue.DUPLICATE_BAR, issues)


class TestLunchBreakGap(unittest.TestCase):
    """A gap spanning the scheduled lunch recess is not missing data (design §26.1)."""

    SESSION = SessionWindow(570, 900, lunch_start=690, lunch_end=780)  # 09:30-15:00

    def test_lunch_gap_not_flagged_missing(self):
        prev = _bar(time="2026-08-12T11:30:00")
        cur = _bar(time="2026-08-12T13:00:00")
        issues = check_bar_quality(
            cur, prev, expected_interval_seconds=300, now="2026-08-12T13:00:00",
            max_stale_seconds=600, session=self.SESSION,
        )
        # 90-min gap spans lunch; with the session it is expected, not MISSING.
        self.assertNotIn(BarQualityIssue.MISSING, issues)

    def test_real_gap_still_flagged_with_session(self):
        prev = _bar(time="2026-08-12T10:00:00")
        cur = _bar(time="2026-08-12T11:00:00")
        issues = check_bar_quality(
            cur, prev, expected_interval_seconds=300, now="2026-08-12T11:00:00",
            max_stale_seconds=600, session=self.SESSION,
        )
        # 60-min gap inside one session half is still missing data.
        self.assertIn(BarQualityIssue.MISSING, issues)

    def test_lunch_gap_without_session_is_missing(self):
        prev = _bar(time="2026-08-12T11:30:00")
        cur = _bar(time="2026-08-12T13:00:00")
        issues = check_bar_quality(
            cur, prev, expected_interval_seconds=300, now="2026-08-12T13:00:00",
            max_stale_seconds=600,
        )
        self.assertIn(BarQualityIssue.MISSING, issues)

    def test_guard_with_session_accepts_lunch_gap(self):
        guard = DataQualityGuard(
            expected_interval_seconds=300, max_stale_seconds=600,
            session=self.SESSION,
        )
        guard.check(_bar(time="2026-08-12T11:30:00"), now="2026-08-12T13:00:00")
        issues = guard.check(_bar(time="2026-08-12T13:00:00"), now="2026-08-12T13:00:00")
        self.assertNotIn(BarQualityIssue.MISSING, issues)

    def test_invalid_session_rejected(self):
        with self.assertRaises(StrategyInputError):
            check_bar_quality(
                _bar(), None, expected_interval_seconds=300, now=NOW,
                max_stale_seconds=600, session="09:30",
            )


if __name__ == "__main__":
    unittest.main()
