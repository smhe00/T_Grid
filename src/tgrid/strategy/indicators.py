"""Pure indicator mathematics for the offline strategy engine (Gate 3).

All functions are deterministic, side-effect-free, and operate on a sequence of
:class:`~tgrid.strategy.bars.Bar` objects (or plain numeric sequences where
noted).  They never fetch data, never mutate input, and raise
:class:`StrategyInputError` when the input is too short or malformed instead of
silently returning a degraded value (fail closed).

Design references: §9 (VWAP20 / EMA20 anchor), §10 (ATR14 and ATR%).
The adjusted-price basis requirement (§7.1) is enforced by the caller: these
functions do not mix bases, they only compute on what they are given.
"""

from __future__ import annotations

from typing import Sequence

from tgrid.strategy.exceptions import StrategyInputError


def _require_sequence(values, name: str) -> Sequence:
    if values is None or isinstance(values, (str, bytes)) or not hasattr(values, "__len__"):
        raise StrategyInputError(f"{name} must be a non-empty sequence of numbers")
    return values


def ema20(closes: Sequence) -> float:
    """Exponential moving average with period 20, seeded by SMA of the first 20.

    Requires at least 20 values; fewer is fail-closed (design §9: the VWAP20
    anchor may fall back to EMA20, but EMA20 itself needs a full window).
    """
    values = _require_sequence(closes, "closes")
    if len(values) < 20:
        raise StrategyInputError("ema20 requires at least 20 closes")
    period = 20
    alpha = 2.0 / (period + 1.0)
    seed = sum(float(v) for v in values[:period]) / period
    ema = seed
    for value in values[period:]:
        ema = alpha * float(value) + (1.0 - alpha) * ema
    return ema


def vwap20(bars: Sequence) -> float:
    """Volume-weighted average price over the last 20 bars (design §9).

    Typical price = (high + low + close) / 3; VWAP = sum(tp * volume) /
    sum(volume).  Requires at least 1 bar and a strictly positive total volume;
    zero-volume data fails closed (the caller may then fall back to EMA20).
    """
    if bars is None or isinstance(bars, (str, bytes)) or not hasattr(bars, "__len__"):
        raise StrategyInputError("bars must be a non-empty sequence of Bar objects")
    if len(bars) == 0:
        raise StrategyInputError("vwap20 requires at least one bar")
    window = bars[-20:]
    total_value = 0.0
    total_volume = 0
    for bar in window:
        try:
            high = float(bar.high)
            low = float(bar.low)
            close = float(bar.close)
            volume = bar.volume
        except (AttributeError, TypeError, ValueError):
            raise StrategyInputError("vwap20 requires Bar objects with numeric OHLCV") from None
        if type(volume) is not int or volume < 0:
            raise StrategyInputError("vwap20 requires non-negative integer volume")
        if high < low:
            raise StrategyInputError("vwap20 requires high >= low")
        typical = (high + low + close) / 3.0
        total_value += typical * volume
        total_volume += volume
    if total_volume <= 0:
        raise StrategyInputError("vwap20 requires strictly positive total volume")
    return total_value / total_volume


def _true_ranges(bars: Sequence):
    """Yield TR values across bars; requires at least 2 bars."""
    previous_close = None
    for bar in bars:
        try:
            high = float(bar.high)
            low = float(bar.low)
            close = float(bar.close)
        except (AttributeError, TypeError, ValueError):
            raise StrategyInputError("atr14 requires Bar objects with numeric HLC") from None
        if high < low:
            raise StrategyInputError("atr14 requires high >= low")
        if previous_close is None:
            previous_close = close
            continue
        tr = max(high - low, abs(high - previous_close), abs(low - previous_close))
        previous_close = close
        yield tr


def atr14(bars: Sequence) -> float:
    """Wilder's Average True Range over 14 periods (design §10).

    Requires at least 15 bars (14 true ranges).  Uses Wilder smoothing: the
    first ATR is the mean of the first 14 TRs; each following TR updates it as
    ``(prev * 13 + tr) / 14``.
    """
    if bars is None or isinstance(bars, (str, bytes)) or not hasattr(bars, "__len__"):
        raise StrategyInputError("bars must be a non-empty sequence of Bar objects")
    trs = list(_true_ranges(bars))
    if len(trs) < 14:
        raise StrategyInputError("atr14 requires at least 15 bars")
    first = sum(trs[:14]) / 14.0
    atr = first
    for tr in trs[14:]:
        atr = (atr * 13.0 + tr) / 14.0
    return atr


def atr_pct(atr: float, close: float) -> float:
    """Normalized volatility ATR% = ATR14 / Close (design §10)."""
    if type(atr) not in (int, float) or type(close) not in (int, float):
        raise StrategyInputError("atr and close must be numbers")
    atr = float(atr)
    close = float(close)
    if atr < 0 or close <= 0:
        raise StrategyInputError("atr must be >= 0 and close must be > 0")
    return atr / close
