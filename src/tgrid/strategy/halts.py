"""Volatility and event-block halt decisions (Gate 3, offline).

Design §28 (Volatility Halt): a daily move beyond ``K_halt × ATR%`` *or* an
open gap beyond ``2G`` is treated as an information shock, not normal
volatility — the symbol must not open new T lots that day.

Design §29 (Event Block): earnings/corporate events are manually configured as
a per-symbol set of event dates; the block window covers
``[event - block_before_days, event + block_after_days]``.

Both are pure decisions; the engine decides how to persist/act on them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from tgrid.strategy.exceptions import StrategyInputError


def _require_finite(value, name: str) -> float:
    if type(value) not in (int, float) or isinstance(value, bool):
        raise StrategyInputError(f"{name} must be a number")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise StrategyInputError(f"{name} must be finite")
    return result


def volatility_halt(
    *,
    previous_close: float,
    current_price: float,
    atr_pct: float,
    halt_atr_k: float,
    grid_g: float,
) -> bool:
    """True if the symbol must halt for the day (design §28).

    Halts when the daily move ``|current/prev - 1| > K_halt × ATR%`` *or* the
    gap ``|current - prev|/prev > 2G``.  ``atr_pct`` >= 0, ``halt_atr_k`` > 0,
    ``0 < grid_g < 1``, both prices > 0.
    """
    return daily_move_halted(
        previous_close=previous_close,
        current_price=current_price,
        atr_pct=atr_pct,
        halt_atr_k=halt_atr_k,
    ) or gap_halted(
        gap_reference=previous_close,
        current_price=current_price,
        grid_g=grid_g,
    )


def daily_move_halted(
    *,
    previous_close: float,
    current_price: float,
    atr_pct: float,
    halt_atr_k: float,
) -> bool:
    """True when the daily move exceeds ``K_halt × ATR%`` (design §28 rule 1).

    ``previous_close`` is the reference daily close (from the frozen daily
    basis), ``current_price`` the latest bar price, ``atr_pct`` ATR14/Close
    (>= 0) and ``halt_atr_k`` > 0.
    """
    previous = _require_finite(previous_close, "previous_close")
    current = _require_finite(current_price, "current_price")
    atr = _require_finite(atr_pct, "atr_pct")
    halt_k = _require_finite(halt_atr_k, "halt_atr_k")
    if previous <= 0 or current <= 0:
        raise StrategyInputError("prices must be > 0")
    if atr < 0 or halt_k <= 0:
        raise StrategyInputError("atr_pct must be >= 0 and halt_atr_k must be > 0")
    return abs(current - previous) / previous > halt_k * atr


def gap_halted(
    *,
    gap_reference: float,
    current_price: float,
    grid_g: float,
) -> bool:
    """True when the open/bar-to-bar gap exceeds ``2G`` (design §28 rule 2).

    ``gap_reference`` is the reference price the gap is measured from — for the
    day's first bar the previous daily close, for later bars the immediately
    preceding bar's close.  ``0 < grid_g < 1`` and both prices > 0.
    """
    reference = _require_finite(gap_reference, "gap_reference")
    current = _require_finite(current_price, "current_price")
    g = _require_finite(grid_g, "grid_g")
    if reference <= 0 or current <= 0:
        raise StrategyInputError("prices must be > 0")
    if not (0 < g < 1):
        raise StrategyInputError("grid_g must be strictly between 0 and 1")
    return abs(current - reference) / reference > 2.0 * g


@dataclass(frozen=True)
class EventBlockRule:
    """Per-symbol manual event dates plus the block window (design §29).

    ``events`` maps a symbol to an immutable tuple of event dates
    (``YYYY-MM-DD``).  ``block_before_days`` / ``block_after_days`` default to
    1 as in the design.  The rule is frozen and validated on construction.
    """

    events: Mapping
    block_before_days: int = 1
    block_after_days: int = 1

    def __post_init__(self) -> None:
        if type(self.block_before_days) is not int or self.block_before_days < 0:
            raise StrategyInputError("block_before_days must be a non-negative int")
        if type(self.block_after_days) is not int or self.block_after_days < 0:
            raise StrategyInputError("block_after_days must be a non-negative int")
        cleaned = {}
        if self.events is None or not hasattr(self.events, "items"):
            raise StrategyInputError("events must be a mapping of symbol -> dates")
        for symbol, dates in self.events.items():
            if type(symbol) is not str or symbol == "":
                raise StrategyInputError("event symbol must be a non-empty string")
            if dates is None or isinstance(dates, (str, bytes)) or not hasattr(dates, "__len__"):
                raise StrategyInputError(f"event dates for {symbol!r} must be a sequence")
            cleaned[symbol] = tuple(str(d) for d in dates)
        object.__setattr__(self, "events", dict(cleaned))


def event_blocked(
    rule: object,
    *,
    symbol: str,
    trade_date: str,
) -> bool:
    """True if ``symbol`` is inside an event block window on ``trade_date``."""
    if rule is None or not isinstance(rule, EventBlockRule):
        raise StrategyInputError("rule must be an EventBlockRule")
    if type(symbol) is not str or symbol == "":
        raise StrategyInputError("symbol must be a non-empty string")
    if type(trade_date) is not str or len(trade_date) != 10:
        raise StrategyInputError("trade_date must be a YYYY-MM-DD string")
    try:
        from datetime import date, timedelta

        trade = date.fromisoformat(trade_date)
        dates = rule.events.get(symbol)
        if not dates:
            return False
        for event in dates:
            event_date = date.fromisoformat(event)
            window_start = event_date - timedelta(days=rule.block_before_days)
            window_end = event_date + timedelta(days=rule.block_after_days)
            if window_start <= trade <= window_end:
                return True
    except ValueError:
        raise StrategyInputError("trade_date or event dates must be valid YYYY-MM-DD") from None
    return False
