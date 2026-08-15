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

    def reconstruct_from_orders(
        self,
        orders: tuple,
        *,
        intents: tuple = (),
        remark_prefix: str = "TG_",
    ) -> None:
        """Conservatively rebuild today's exposure (NODEB-RR4-003).

        The safety-critical trade date is taken from DURABLE TGrid intent
        dates (``OrderIntent.created_at`` / explicit trade-date field), joined
        to authoritative broker orders by broker id / client key / remark —
        NEVER from raw broker ``order_time`` formatting.  Managed BUY orders:

        * with a local intent whose durable date is today  -> counted;
        * with a local intent dated another day            -> skipped (correct);
        * with NO local intent (cannot be safely assigned) -> counted
          conservatively (never silently dropped on unknown timestamp format).

        Terminal same-day orders are included (submitted notional is never
        removed for the trade date).  The exposure becomes the maximum of the
        persisted value and the sum; persisted pre-send exposure remains the
        lower bound.
        """
        if intents:
            by_broker_id = {
                getattr(i, "broker_order_id", None): i for i in intents
                if getattr(i, "broker_order_id", None) is not None
            }
            by_key = {
                getattr(i, "client_order_key", None): i for i in intents
                if getattr(i, "client_order_key", None) is not None
            }
            by_remark = {
                getattr(i, "order_remark", None): i for i in intents
                if getattr(i, "order_remark", None) is not None
            }
        else:
            by_broker_id = by_key = by_remark = {}

        total = 0.0
        for order in orders:
            remark = getattr(order, "order_remark", None)
            if not isinstance(remark, str) or not remark.startswith(remark_prefix):
                continue
            if getattr(order, "side", None) != "BUY":
                continue
            qty = getattr(order, "qty", 0)
            price = getattr(order, "limit_price", 0.0)
            if type(qty) is not int or qty <= 0:
                continue
            if type(price) not in (int, float) or isinstance(price, bool) or not math.isfinite(float(price)) or price <= 0:
                continue
            order_id = getattr(order, "order_id", None)
            client_key = getattr(order, "client_order_key", None)
            intent = (
                by_broker_id.get(order_id)
                or by_key.get(client_key)
                or by_remark.get(remark)
            )
            if intent is not None:
                created = getattr(intent, "created_at", "")
                if isinstance(created, str) and created and self._trade_date:
                    if not created.startswith(self._trade_date):
                        continue  # durable intent date says a different day
            # Counted conservatively: same-day intent, or no intent (cannot be
            # safely assigned) — never dropped on unknown timestamp format.
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
