"""Bar and session primitives for the offline strategy engine (Gate 3).

A :class:`Bar` is an immutable, plain-data OHLCV row tagged with its kind
(daily vs 5-minute) and its price basis (RAW vs ADJUSTED, see
:mod:`tgrid.strategy.corporate_action`).  The engine never invents bars; it
consumes exactly the bars it is given and fails closed on anything malformed.
"""

from __future__ import annotations

from dataclasses import dataclass


class _BarKind:
    """Fixed bar-kind constants (daily vs 5-minute, design §8/§20)."""

    DAILY = "DAILY"
    FIVE_MINUTE = "5m"


BarKind = _BarKind()


@dataclass(frozen=True)
class Bar:
    """One immutable OHLCV bar.

    ``time`` is an exchange-local ISO-8601 string (e.g. ``2026-08-12T10:05:00``)
    so ordering is deterministic; the engine never interprets wall-clock time
    (design §26.1).  ``price_basis`` must be a :class:`PriceBasis` value
    (RAW/ADJUSTED); indicators are only ever computed on a single, consistent
    basis (design §7.1).
    """

    symbol: str
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    kind: str = BarKind.FIVE_MINUTE
    price_basis: str = "RAW"


@dataclass(frozen=True)
class SessionWindow:
    """A trading session described in exchange-local minute-of-day.

    ``open_minute`` / ``close_minute`` are minutes since midnight
    (e.g. 570 = 09:30, 900 = 15:00).  ``lunch_start`` / ``lunch_end`` split the
    session (both None for continuous sessions); times inside the lunch break
    are not trading minutes.  Used only for the design §27 time-window filters.
    """

    open_minute: int
    close_minute: int
    lunch_start: int | None = None
    lunch_end: int | None = None

    def __post_init__(self) -> None:
        if type(self.open_minute) is not int or type(self.close_minute) is not int:
            raise ValueError("open/close minutes must be plain ints")
        if not (0 <= self.open_minute < self.close_minute <= 24 * 60):
            raise ValueError("invalid session window")
        if self.lunch_start is not None and self.lunch_end is not None:
            if type(self.lunch_start) is not int or type(self.lunch_end) is not int:
                raise ValueError("lunch minutes must be plain ints")
            if not (
                self.open_minute < self.lunch_start < self.lunch_end < self.close_minute
            ):
                raise ValueError("lunch break must be strictly inside the session")

    def contains(self, minute: object) -> bool:
        """True if ``minute`` is a trading minute inside this session."""
        if type(minute) is not int:
            return False
        if minute < self.open_minute or minute >= self.close_minute:
            return False
        if self.lunch_start is not None and self.lunch_end is not None:
            if self.lunch_start <= minute < self.lunch_end:
                return False
        return True
