"""Data-quality guard for the offline strategy engine (Gate 3, design §26.2).

Any bar used for strategy computation must pass explicit checks before it may
influence a decision:

* timestamp freshness / staleness
* missing bars (gap between consecutive bars)
* duplicate bar (same timestamp twice)
* out-of-order bar (timestamp goes backwards)
* price validity (positive, high >= low, high >= open/close, low <= open/close)
* volume validity (non-negative integer)
* suspension (volume == 0 with a positive-price bar)

A violation produces one or more :class:`BarQualityIssue` codes; the caller
(engine) converts any violation into ``DATA_HALT`` and refuses to open new T
lots (design §26.2: "发现数据质量异常 → DATA_HALT").  The guard is pure: it
never fetches, never mutates, and never guesses.
"""

from __future__ import annotations

from typing import Sequence

from tgrid.strategy.bars import Bar, SessionWindow
from tgrid.strategy.exceptions import StrategyInputError


class _Issue:
    STALE = "STALE"
    MISSING = "MISSING_BAR"
    DUPLICATE_BAR = "DUPLICATE_BAR"
    OUT_OF_ORDER_BAR = "OUT_OF_ORDER_BAR"
    PRICE_INVALID = "PRICE_INVALID"
    VOLUME_INVALID = "VOLUME_INVALID"
    SUSPENSION = "SUSPENSION"


BarQualityIssue = _Issue()


def _is_iso_time(value: str) -> bool:
    # Deterministic lexical check only: ISO-8601-like strings sort correctly and
    # the engine never converts to wall-clock time (design §26.1).  Accept the
    # compact form "YYYY-MM-DDTHH:MM:SS".
    if type(value) is not str or len(value) < 19:
        return False
    try:
        parts = value[:19].split("T")
        if len(parts) != 2:
            return False
        date_part = parts[0].split("-")
        time_part = parts[1].split(":")
        if len(date_part) != 3 or len(time_part) != 3:
            return False
        if not all(len(p) == 2 and p.isdigit() for p in date_part[1:] + time_part):
            return False
        if len(date_part[0]) != 4 or not date_part[0].isdigit():
            return False
        return True
    except Exception:
        return False


def _require_positive_price(value, name: str) -> float:
    if type(value) not in (int, float) or isinstance(value, bool):
        raise StrategyInputError(f"bar {name} must be a number")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")) or result <= 0:
        raise StrategyInputError(f"bar {name} must be finite and positive")
    return result


def check_bar_quality(
    bar: object,
    previous_bar: object,
    *,
    expected_interval_seconds: int,
    now: str,
    max_stale_seconds: int,
    max_gap_multiple: float = 2.0,
    session: object = None,
) -> tuple:
    """Validate one bar; returns a tuple of issue codes (empty = acceptable).

    ``expected_interval_seconds`` is the bar period in seconds (300 for 5m),
    ``now`` the current exchange-local ISO time, ``max_stale_seconds`` the
    freshness horizon.  A gap is flagged when the previous bar is more than
    ``max_gap_multiple`` periods old relative to ``bar``.  ``session`` is an
    optional :class:`~tgrid.strategy.bars.SessionWindow`; when given, a gap
    that spans the lunch break is not treated as missing data (design §26.1:
    the lunch recess is a scheduled break, not a data hole).  Raises
    :class:`StrategyInputError` only for structurally unusable input (not a
    Bar, bad parameters); data problems come back as issue codes so the caller
    decides the halt policy.
    """
    if not isinstance(bar, Bar):
        raise StrategyInputError("bar must be a Bar")
    if type(expected_interval_seconds) is not int or expected_interval_seconds <= 0:
        raise StrategyInputError("expected_interval_seconds must be a positive int")
    if type(max_stale_seconds) is not int or max_stale_seconds < 0:
        raise StrategyInputError("max_stale_seconds must be a non-negative int")
    if type(now) is not str or not _is_iso_time(now):
        raise StrategyInputError("now must be an ISO-8601 time string")
    if type(max_gap_multiple) not in (int, float) or isinstance(max_gap_multiple, bool):
        raise StrategyInputError("max_gap_multiple must be a number")
    if max_gap_multiple < 1.0:
        raise StrategyInputError("max_gap_multiple must be >= 1.0")
    if session is not None and not isinstance(session, SessionWindow):
        raise StrategyInputError("session must be a SessionWindow or None")

    issues = []

    # Price validity.
    try:
        open_ = _require_positive_price(bar.open, "open")
        high = _require_positive_price(bar.high, "high")
        low = _require_positive_price(bar.low, "low")
        close = _require_positive_price(bar.close, "close")
    except StrategyInputError:
        issues.append(BarQualityIssue.PRICE_INVALID)
        open_ = high = low = close = 0.0
    if high < low or high < open_ or high < close or low > open_ or low > close:
        issues.append(BarQualityIssue.PRICE_INVALID)

    # Volume validity + suspension.
    if type(bar.volume) is not int or bar.volume < 0:
        issues.append(BarQualityIssue.VOLUME_INVALID)
        volume = 0
    else:
        volume = bar.volume
        if volume == 0 and BarQualityIssue.PRICE_INVALID not in issues:
            issues.append(BarQualityIssue.SUSPENSION)

    # Timestamp checks (only when structurally usable).
    if not _is_iso_time(bar.time):
        issues.append(BarQualityIssue.OUT_OF_ORDER_BAR)
    else:
        if now < bar.time:
            issues.append(BarQualityIssue.STALE)  # future timestamp = suspect
        elif _iso_seconds(now) - _iso_seconds(bar.time) > max_stale_seconds:
            issues.append(BarQualityIssue.STALE)

        if previous_bar is not None:
            if not isinstance(previous_bar, Bar) or not _is_iso_time(previous_bar.time):
                issues.append(BarQualityIssue.OUT_OF_ORDER_BAR)
            else:
                if previous_bar.time == bar.time:
                    issues.append(BarQualityIssue.DUPLICATE_BAR)
                elif previous_bar.time > bar.time:
                    issues.append(BarQualityIssue.OUT_OF_ORDER_BAR)
                else:
                    gap_seconds = _iso_seconds(bar.time) - _iso_seconds(previous_bar.time)
                    # A gap spanning the scheduled lunch break is expected
                    # (e.g. 11:30 -> 13:00 for A-shares), not missing data.
                    lunch_padding = _lunch_gap_seconds(previous_bar.time, bar.time, session)
                    if gap_seconds - lunch_padding > expected_interval_seconds * max_gap_multiple:
                        issues.append(BarQualityIssue.MISSING)

    return tuple(issues)


def _lunch_gap_seconds(previous_time: str, current_time: str, session: object) -> int:
    """Extra seconds of the gap attributable to the lunch break (0 if none).

    Returns the lunch duration (in seconds) only when the previous bar ends
    before the lunch break and the current bar starts after it — i.e. the pair
    straddles the recess and the gap is therefore partially scheduled.
    """
    if session is None or session.lunch_start is None or session.lunch_end is None:
        return 0
    prev_minute = _minute_of_day(previous_time)
    curr_minute = _minute_of_day(current_time)
    # A bar stamped at exactly lunch_start is the last pre-recess bar; a bar at
    # lunch_end or later is the first post-recess bar.
    if prev_minute <= session.lunch_start and curr_minute >= session.lunch_end:
        return (session.lunch_end - session.lunch_start) * 60
    return 0


def _minute_of_day(iso_time: str) -> int:
    try:
        hours, minutes, _ = (int(p) for p in iso_time[11:19].split(":"))
        return hours * 60 + minutes
    except Exception:
        return -1


def _iso_seconds(value: str) -> int:
    """Return whole seconds since an arbitrary epoch for ISO time strings."""
    day = value[:10].replace("-", "")
    time_part = value[11:19]
    hours, minutes, seconds = (int(p) for p in time_part.split(":"))
    return int(day) * 86400 + hours * 3600 + minutes * 60 + seconds


class DataQualityGuard:
    """Stateful sequence guard: holds the previous bar and reports issues.

    The engine feeds every incoming bar through :meth:`check`; the returned
    issue tuple decides whether the bar may drive a decision.  The guard is
    deliberately not thread-safe — the engine is single-threaded (design §3.1).
    """

    def __init__(
        self,
        *,
        expected_interval_seconds: int,
        max_stale_seconds: int,
        max_gap_multiple: float = 2.0,
        session: object = None,
    ) -> None:
        if type(expected_interval_seconds) is not int or expected_interval_seconds <= 0:
            raise StrategyInputError("expected_interval_seconds must be a positive int")
        if type(max_stale_seconds) is not int or max_stale_seconds < 0:
            raise StrategyInputError("max_stale_seconds must be a non-negative int")
        if session is not None and not isinstance(session, SessionWindow):
            raise StrategyInputError("session must be a SessionWindow or None")
        self._expected_interval_seconds = expected_interval_seconds
        self._max_stale_seconds = max_stale_seconds
        self._max_gap_multiple = max_gap_multiple
        self._session = session
        self._previous: object | None = None

    def check(self, bar: object, *, now: str) -> tuple:
        """Validate ``bar`` and remember it as the new previous bar."""
        issues = check_bar_quality(
            bar,
            self._previous,
            expected_interval_seconds=self._expected_interval_seconds,
            now=now,
            max_stale_seconds=self._max_stale_seconds,
            max_gap_multiple=self._max_gap_multiple,
            session=self._session,
        )
        if isinstance(bar, Bar):
            self._previous = bar
        return issues
