"""Durable daily cash-exposure ledger (NODEB-005 / NODEB-I2-004).

The daily exposure cap must survive restarts and must not be resettable by an
unrestricted public zeroing method.  :class:`DailyExposureLedger` binds the
exposure accounting to a ``trade_date`` and rebuilds the current-day exposure
conservatively from durable/broker-side state before new orders are enabled.

Counting rule (deterministic): the cap counts **submitted BUY notional**
(``qty * limit_price`` at submission).  Once counted, a submitted notional is
never removed for that trade_date — cancel/reject/partial fills do not reopen
the cap, and on restart the conservative maximum of (persisted value, sum of
managed broker-side BUY orders' notional INCLUDING terminal same-day orders)
is used (I2-004), so a restart cannot silently reset the boundary.

Crash safety (I2-004):

* ``trade_date`` must be a real ISO calendar date (``datetime.date``), so a
  lexicographic-looking future string cannot bypass the cap;
* day rollover is a strict monotonic ISO-date transition only;
* reconstruction counts every managed BUY order on the trade date — terminal
  or not — matching the "submitted notional never removed" rule;
* a send-before-ledger crash window is closed by reserving submitted BUY
  notional conservatively BEFORE the broker send (failed/rejected sends do not
  need to reopen the daily cap).
"""

from __future__ import annotations

import datetime
import math

from tgrid.risk.exceptions import TGridError


class DailyExposureError(TGridError):
    """Base class for daily-exposure ledger failures."""


class ExposureDateError(DailyExposureError):
    """trade_date is invalid or not a monotonic ISO-day transition."""


class ExposureValueError(DailyExposureError):
    """An exposure amount is not a finite non-negative number."""


def _validate_iso_date(trade_date: str) -> datetime.date:
    if type(trade_date) is not str or trade_date == "":
        raise ExposureDateError("trade_date must be a non-empty string")
    try:
        return datetime.date.fromisoformat(trade_date)
    except ValueError as exc:
        raise ExposureDateError(f"trade_date must be an ISO calendar date: {trade_date!r}") from exc


class DailyExposureLedger:
    """Trade-date-bound daily BUY-notional ledger.

    ``trade_date`` is a validated ISO calendar date; ``store`` is the durable
    key/value surface (``get(trade_date)`` / ``set(trade_date, notional)``) so
    the persisted value survives restart.  Production/live construction MUST
    provide a durable store (the adapter enforces this, NODEB-I2-004).
    """

    def __init__(self, *, trade_date: str = "", store: object | None = None) -> None:
        if trade_date:
            _validate_iso_date(trade_date)
        self._trade_date = trade_date
        self._store = store
        self._used = 0.0
        self._load()

    # --------------------------------------------------------------- state

    @property
    def trade_date(self) -> str:
        return self._trade_date

    @property
    def used(self) -> float:
        return self._used

    def _load(self) -> None:
        if self._store is None or not self._trade_date:
            return
        value = self._store.get(self._trade_date)
        if value is None:
            return
        if type(value) not in (int, float) or isinstance(value, bool) or not math.isfinite(float(value)) or value < 0:
            raise ExposureValueError("persisted exposure must be a finite non-negative number")
        self._used = float(value)

    def _persist(self) -> None:
        if self._store is not None and self._trade_date:
            self._store.set(self._trade_date, self._used)

    # -------------------------------------------------------------- writes

    def record_submitted_buy(self, notional: float) -> None:
        """Add a submitted BUY notional to today's exposure (never removed)."""
        if type(notional) not in (int, float) or isinstance(notional, bool):
            raise ExposureValueError("notional must be a number")
        if not math.isfinite(float(notional)) or notional < 0:
            raise ExposureValueError("notional must be a finite non-negative number")
        self._used += float(notional)
        self._persist()

    def reconstruct_from_orders(self, orders: tuple, *, remark_prefix: str = "TG_") -> None:
        """Conservatively rebuild today's exposure from managed broker orders.

        Managed = BUY orders tagged with ``remark_prefix`` that belong to the
        current ``trade_date``.  The date is taken from the order's
        **durable intent/journal timestamp** when present (``order_time`` in the
        native QMT representation is NOT assumed — RR-004: do not key
        safety-critical same-day reconstruction on a raw broker timestamp
        format).  Orders carrying no durable date are counted conservatively.
        **Terminal same-day orders are included** (I2-004): the "submitted BUY
        notional is never removed" rule means a filled/canceled/rejected
        same-day order still consumed the cap.
        """
        total = 0.0
        for order in orders:
            remark = getattr(order, "order_remark", None)
            if not isinstance(remark, str) or not remark.startswith(remark_prefix):
                continue
            if getattr(order, "side", None) != "BUY":
                continue
            order_time = getattr(order, "order_time", "")
            if isinstance(order_time, str) and order_time and self._trade_date:
                # Accept the ISO date prefix of the journal timestamp; raw
                # QMT formats are not assumed, so an unrecognized value makes
                # the order count conservatively rather than being dropped.
                if not order_time.startswith(self._trade_date):
                    continue
            qty = getattr(order, "qty", 0)
            price = getattr(order, "limit_price", 0.0)
            if type(qty) is not int or qty <= 0:
                continue
            if type(price) not in (int, float) or isinstance(price, bool) or not math.isfinite(float(price)) or price <= 0:
                continue
            total += qty * float(price)
        self._used = max(self._used, total)
        self._persist()

    def roll_day(self, new_trade_date: str) -> None:
        """Advance to ``new_trade_date``; only a strict monotonic ISO-day transition resets."""
        new_date = _validate_iso_date(new_trade_date)
        if self._trade_date:
            current = _validate_iso_date(self._trade_date)
            if new_date <= current:
                raise ExposureDateError(
                    f"day roll requires a monotonic ISO transition: "
                    f"{self._trade_date!r} -> {new_trade_date!r}"
                )
        self._trade_date = new_trade_date
        self._used = 0.0
        self._persist()
