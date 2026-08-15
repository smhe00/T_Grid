"""Tests for tgrid.strategy.indicators (Gate 3)."""

import unittest

from tgrid.strategy.bars import Bar
from tgrid.strategy.exceptions import StrategyInputError
from tgrid.strategy.indicators import atr14, atr_pct, ema20, vwap20


def _bar(close, high=None, low=None, volume=1000, time="2026-08-01T00:00:00"):
    high = high if high is not None else close
    low = low if low is not None else close
    return Bar(
        symbol="0700.HK", time=time, open=close, high=high, low=low,
        close=close, volume=volume, kind="DAILY",
    )


class TestEma20(unittest.TestCase):
    def test_ema20_constant_series(self):
        closes = [100.0] * 25
        self.assertAlmostEqual(ema20(closes), 100.0, places=10)

    def test_ema20_known_value(self):
        # Linear ramp 1..24: EMA(20) is inside (12.5, 24); monotonic in input.
        closes = [float(i) for i in range(1, 25)]
        ema = ema20(closes)
        self.assertGreater(ema, 12.5)
        self.assertLess(ema, 24.0)

    def test_ema20_requires_20(self):
        with self.assertRaises(StrategyInputError):
            ema20([1.0] * 19)

    def test_ema20_rejects_sequence_duck_types(self):
        with self.assertRaises(StrategyInputError):
            ema20("12345")  # str is rejected before len() is trusted


class TestVwap20(unittest.TestCase):
    def test_vwap20_flat(self):
        bars = [_bar(100.0, high=101.0, low=99.0, volume=500) for _ in range(20)]
        # typical = (101+99+100)/3 = 100 -> VWAP 100
        self.assertAlmostEqual(vwap20(bars), 100.0, places=10)

    def test_vwap20_weighted(self):
        bars = [_bar(100.0, high=100.0, low=100.0, volume=100) for _ in range(19)]
        bars.append(_bar(200.0, high=200.0, low=200.0, volume=100))
        # value = 100*19*100 + 200*100 = 210000; vol = 2000 -> 105
        self.assertAlmostEqual(vwap20(bars), 105.0, places=10)

    def test_vwap20_uses_last_20(self):
        bars = [_bar(100.0, high=100.0, low=100.0, volume=100) for _ in range(30)]
        for i in range(10):
            bars[i] = _bar(1000.0, high=1000.0, low=1000.0, volume=100)
        # only last 20 (all 100) count -> 100
        self.assertAlmostEqual(vwap20(bars), 100.0, places=10)

    def test_vwap20_zero_volume_fails_closed(self):
        bars = [_bar(100.0, volume=0) for _ in range(20)]
        with self.assertRaises(StrategyInputError):
            vwap20(bars)

    def test_vwap20_empty_fails(self):
        with self.assertRaises(StrategyInputError):
            vwap20([])

    def test_vwap20_rejects_non_bar(self):
        with self.assertRaises(StrategyInputError):
            vwap20([1, 2, 3])

    def test_vwap20_rejects_negative_volume(self):
        bars = [_bar(100.0, volume=-1) for _ in range(20)]
        with self.assertRaises(StrategyInputError):
            vwap20(bars)

    def test_vwap20_rejects_bad_price_shape(self):
        bars = [_bar(100.0, high=99.0, low=101.0, volume=100) for _ in range(20)]
        with self.assertRaises(StrategyInputError):
            vwap20(bars)


class TestAtr14(unittest.TestCase):
    def test_atr14_zero_range(self):
        bars = [_bar(100.0) for _ in range(20)]
        self.assertAlmostEqual(atr14(bars), 0.0, places=10)

    def test_atr14_constant_range(self):
        # Every bar spans 10: TR = 10 -> ATR = 10
        bars = [_bar(100.0, high=105.0, low=95.0) for _ in range(20)]
        self.assertAlmostEqual(atr14(bars), 10.0, places=10)

    def test_atr14_wilder_smoothing(self):
        # 15 bars, first 14 TR = 10, last TR = 20.
        bars = [_bar(100.0, high=105.0, low=95.0) for _ in range(15)]
        bars[-1] = _bar(100.0, high=110.0, low=90.0)
        # first ATR = 10; then (10*13 + 20)/14 = 150/14
        expected = (10.0 * 13.0 + 20.0) / 14.0
        self.assertAlmostEqual(atr14(bars), expected, places=10)

    def test_atr14_requires_15_bars(self):
        with self.assertRaises(StrategyInputError):
            atr14([_bar(100.0) for _ in range(14)])

    def test_atr14_rejects_high_lt_low(self):
        bars = [_bar(100.0, high=90.0, low=110.0) for _ in range(20)]
        with self.assertRaises(StrategyInputError):
            atr14(bars)


class TestAtrPct(unittest.TestCase):
    def test_atr_pct(self):
        self.assertAlmostEqual(atr_pct(10.0, 100.0), 0.10, places=10)

    def test_atr_pct_zero_atr(self):
        self.assertAlmostEqual(atr_pct(0.0, 100.0), 0.0, places=10)

    def test_atr_pct_invalid_close(self):
        with self.assertRaises(StrategyInputError):
            atr_pct(1.0, 0.0)
        with self.assertRaises(StrategyInputError):
            atr_pct(1.0, -5.0)

    def test_atr_pct_negative_atr(self):
        with self.assertRaises(StrategyInputError):
            atr_pct(-1.0, 100.0)

    def test_atr_pct_rejects_bool_and_str(self):
        with self.assertRaises(StrategyInputError):
            atr_pct(True, 100.0)
        with self.assertRaises(StrategyInputError):
            atr_pct(1.0, "100")


if __name__ == "__main__":
    unittest.main()
