"""Durable daily cash-exposure ledger (NODEB-005).

The daily exposure cap must survive restarts and must not be resettable by an
unrestricted public zeroing method.  :class:`DailyExposureLedger` binds the
exposure accounting to a ``trade_date`` and rebuilds the current-day exposure
conservatively from durable/broker-side state before new orders are enabled.

Counting rule (deterministic): the cap counts **submitted BUY notional**
(``qty * limit_price`` at submission).  Once counted, a submitted notional is
never removed for that trade_date — cancel/reject/partial fills do not reopen
the cap, and on restart the conservative maximum of (persisted value, sum of
managed broker-side BUY orders' notional) is used, so a restart cannot silently
reset the boundary.  Only a validated **monotonic trading-day transition**
(``roll_day``) resets the ledger, and only when ``new_trade_date`` is strictly
after the current date.
"""

from __future__ import annotations

import math

from tgrid.risk.exceptions import TGridError


class DailyExposureError(TGridError):
    """Base class for daily-exposure ledger failures."""


class ExposureDateError(DailyExposureError):
    """trade_date is invalid or not a monotonic day transition."""


class ExposureValueError(DailyExposureError):
    """An exposure amount is not a finite non-negative number."""


class DailyExposureLedger:
    """Trade-date-bound daily BUY-notional ledger.

    ``store`` is an optional durable key/value surface (``get(trade_date)`` /
    ``set(trade_date, notional)``) so the persisted value survives restart; when
    ``None`` the ledger is in-memory only and relies on broker-side
    reconstruction (:meth:`reconstruct_from_orders`) for restart safety.
    """

    def __init__(self, *, trade_date: str = "", store: object | None = None) -> None:
        if type(trade_date) is not str:
            raise ExposureDateError("trade_date must be a string")
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

        Managed = BUY orders tagged with ``remark_prefix`` (the §18 tag) that
        are not terminal.  The exposure becomes the maximum of the persisted
        value and the sum of those orders' submitted notional, so a restart can
        never silently shrink the daily cap (NODEB-005).
        """
        total = 0.0
        for order in orders:
            remark = getattr(order, "order_remark", None)
            if not isinstance(remark, str) or not remark.startswith(remark_prefix):
                continue
            if getattr(order, "side", None) != "BUY":
                continue
            if getattr(order, "status", None) in ("FILLED", "CANCELED", "REJECTED", "UNKNOWN"):
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
        """Advance to ``new_trade_date``; only a strict monotonic transition resets."""
        if type(new_trade_date) is not str or new_trade_date == "":
            raise ExposureDateError("new_trade_date must be a non-empty string")
        if self._trade_date and new_trade_date <= self._trade_date:
            raise ExposureDateError(
                f"day roll requires a monotonic transition: "
                f"{self._trade_date!r} -> {new_trade_date!r}"
            )
        self._trade_date = new_trade_date
        self._used = 0.0
        self._persist()
