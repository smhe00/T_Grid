"""Order Intent / Reservation data model (Gate 4, offline, design §18.2/§18.3).

An :class:`OrderIntent` is the durable, idempotent record of a single strategy
order.  It is written to the database BEFORE any broker send (INV-013), carries
a unique ``client_order_key`` plus the §18 tags (``strategy_name``,
``order_remark``), and moves through the design §24 status set.  A
:class:`Reservation` books ReservedSellQty (SELL) or ReservedCash (BUY)
atomically with its intent and is released only against the true terminal
order state.

The status set is a single shared constant consumed by the DB CHECK, the
executor and the recovery path — no second drifting list.
"""

from __future__ import annotations

from dataclasses import dataclass

from tgrid.risk.exceptions import TGridError


class OrderStatusError(TGridError):
    """An order status value is invalid or a transition is illegal."""


class OrderIntentError(TGridError):
    """An OrderIntent argument is invalid (fail closed before use)."""


class ReservationError(TGridError):
    """A reservation argument is invalid (fail closed before use)."""


class _OrderSide:
    BUY = "BUY"
    SELL = "SELL"


OrderSide = _OrderSide()
BUY = OrderSide.BUY
SELL = OrderSide.SELL

# Single source of truth for the design §24 status set (+ §18.2 pre-send).
ORDER_STATUSES = (
    "NEW",
    "READY_TO_SEND",
    "SUBMITTED",
    "PARTIAL",
    "FILLED",
    "CANCEL_REQUESTED",
    "CANCELED",
    "REJECTED",
    "UNKNOWN",
)

# Terminal statuses: no further transition may be applied.
TERMINAL_ORDER_STATUSES = frozenset({"FILLED", "CANCELED", "REJECTED", "UNKNOWN"})

# Statuses that consume reservation capacity while pending.
PENDING_ORDER_STATUSES = frozenset(
    {"NEW", "READY_TO_SEND", "SUBMITTED", "PARTIAL", "CANCEL_REQUESTED"}
)


class OrderStatus:
    """Design §24 order statuses as module constants (NEW/SUBMITTED/...)."""

    NEW = "NEW"
    READY_TO_SEND = "READY_TO_SEND"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class OrderIntent:
    """Immutable, data-only order intent (design §18.2).

    ``client_order_key`` is the unique idempotency key; ``strategy_name`` is
    always ``TGRID`` and ``order_remark`` the §18 tag (e.g. ``TG_0700_B01``).
    ``status`` is one of :data:`ORDER_STATUSES`; ``broker_order_id`` is None
    until the broker acknowledged the send.
    """

    client_order_key: str
    symbol: str
    side: str
    qty: int
    limit_price: float
    strategy_name: str
    order_remark: str
    status: str
    broker_order_id: str | None
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        for name in ("client_order_key", "symbol", "side", "strategy_name",
                     "order_remark", "status", "created_at", "updated_at"):
            value = getattr(self, name)
            if type(value) is not str or value == "":
                raise OrderIntentError(f"{name} must be a non-empty string")
        if self.side not in (BUY, SELL):
            raise OrderIntentError("side must be BUY or SELL")
        if type(self.qty) is not int or self.qty <= 0:
            raise OrderIntentError("qty must be a positive plain int")
        if type(self.limit_price) not in (int, float) or isinstance(self.limit_price, bool):
            raise OrderIntentError("limit_price must be a number")
        if not (self.limit_price > 0):
            raise OrderIntentError("limit_price must be > 0")
        if self.status not in ORDER_STATUSES:
            raise OrderIntentError(f"status must be one of {ORDER_STATUSES}")
        if self.broker_order_id is not None and type(self.broker_order_id) is not str:
            raise OrderIntentError("broker_order_id must be a string or None")


@dataclass(frozen=True)
class Reservation:
    """Immutable reservation record (design §18.3).

    SELL reservations carry ``qty`` (ReservedSellQty) and None ``cash_amount``;
    BUY reservations carry ``cash_amount`` (ReservedCash) and the expected
    ``qty`` for reporting.  ``released_at`` is None while the reservation is
    active; the row is never deleted, only released.
    """

    id: str
    symbol: str
    side: str
    qty: int
    cash_amount: float | None
    client_order_key: str
    created_at: str
    released_at: str | None

    def __post_init__(self) -> None:
        for name in ("id", "symbol", "side", "client_order_key", "created_at"):
            value = getattr(self, name)
            if type(value) is not str or value == "":
                raise ReservationError(f"{name} must be a non-empty string")
        if self.side not in (BUY, SELL):
            raise ReservationError("side must be BUY or SELL")
        if type(self.qty) is not int or self.qty <= 0:
            raise ReservationError("qty must be a positive plain int")
        if self.cash_amount is not None:
            if type(self.cash_amount) not in (int, float) or isinstance(self.cash_amount, bool):
                raise ReservationError("cash_amount must be a number or None")
            if self.cash_amount < 0:
                raise ReservationError("cash_amount must be >= 0")
        if self.released_at is not None and type(self.released_at) is not str:
            raise ReservationError("released_at must be a string or None")
