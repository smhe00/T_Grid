"""Narrow broker execution port shared by dry-run and live execution (NODEB-001).

One protocol — ``place_order / cancel_order / query_order / query_trades /
query_orders`` — is the ONLY broker surface the core execution layer consumes.
:class:`SimBroker` (simulation) and :class:`XtQuantBrokerBridge` (the single
audited live bridge) both implement it; :class:`LiveBrokerAdapter` implements
it on top of an injected broker so ``ExecutionEngine`` never depends on a
concrete broker type.

All broker objects cross the boundary as TGrid-owned typed DTOs
(:class:`BrokerOrder` / :class:`BrokerTrade`); the core never touches raw
XtQuant object shapes.

The broker error hierarchy lives here too so the engine can catch the same
failures regardless of which port implementation raised them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from tgrid.execution.models import BUY, SELL, ORDER_STATUSES
from tgrid.risk.exceptions import TGridError


class BrokerError(TGridError):
    """Base class for broker port failures."""


class BrokerDisconnectedError(BrokerError):
    """The broker is disconnected (network failure, design §23)."""


class BrokerOrderRejectedError(BrokerError):
    """The broker rejected the order at send time."""


class BrokerCancelFailedError(BrokerError):
    """The broker failed to cancel the order (design §25)."""


@dataclass(frozen=True)
class BrokerOrder:
    """TGrid-owned typed broker order snapshot (never a raw XtQuant object).

    ``status`` uses the TGrid :data:`tgrid.execution.models.ORDER_STATUSES`
    vocabulary; ``side`` is ``BUY``/``SELL``; ``filled_qty`` is the broker
    reported filled quantity; ``client_order_key`` / ``order_remark`` carry the
    §18 idempotency tags when the broker echoes them back.
    """

    order_id: str
    symbol: str
    side: str
    qty: int
    limit_price: float
    status: str
    filled_qty: int
    client_order_key: str | None = None
    order_remark: str | None = None

    def __post_init__(self) -> None:
        for name in ("order_id", "symbol", "status"):
            value = getattr(self, name)
            if type(value) is not str or value == "":
                raise BrokerError(f"{name} must be a non-empty string")
        if self.side not in (BUY, SELL):
            raise BrokerError("side must be BUY or SELL")
        if type(self.qty) is not int or self.qty <= 0:
            raise BrokerError("qty must be a positive plain int")
        if type(self.limit_price) not in (int, float) or isinstance(self.limit_price, bool):
            raise BrokerError("limit_price must be a number")
        if not (self.limit_price > 0):
            raise BrokerError("limit_price must be > 0")
        if self.status not in ORDER_STATUSES:
            raise BrokerError(f"status must be one of {ORDER_STATUSES}")
        if type(self.filled_qty) is not int or self.filled_qty < 0:
            raise BrokerError("filled_qty must be a non-negative plain int")
        for name in ("client_order_key", "order_remark"):
            value = getattr(self, name)
            if value is not None and type(value) is not str:
                raise BrokerError(f"{name} must be a string or None")


@dataclass(frozen=True)
class BrokerTrade:
    """TGrid-owned typed broker trade (fill) snapshot."""

    trade_id: str
    order_id: str
    qty: int
    price: float
    time: str

    def __post_init__(self) -> None:
        for name in ("trade_id", "order_id", "time"):
            value = getattr(self, name)
            if type(value) is not str or value == "":
                raise BrokerError(f"{name} must be a non-empty string")
        if type(self.qty) is not int or self.qty <= 0:
            raise BrokerError("qty must be a positive plain int")
        if type(self.price) not in (int, float) or isinstance(self.price, bool):
            raise BrokerError("price must be a number")
        if not (self.price > 0):
            raise BrokerError("price must be > 0")


class BrokerPort(ABC):
    """The one narrow broker execution surface (NODEB-001).

    Implementations: :class:`~tgrid.execution.simbroker.SimBroker` (offline
    simulation) and :class:`~tgrid.integrations.xtquant_bridge.XtQuantBrokerBridge`
    (the only audited live bridge).  :class:`~tgrid.integrations.live_broker_adapter.LiveBrokerAdapter`
    also implements it by delegating to an injected broker while enforcing the
    pre-live safety boundary.
    """

    @abstractmethod
    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: int,
        limit_price: float,
        client_order_key: str | None = None,
        order_remark: str | None = None,
    ) -> str:
        """Send an order; returns the broker order id (never ``None``)."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> None:
        """Cancel an order; raises :class:`BrokerCancelFailedError` on failure."""

    @abstractmethod
    def query_order(self, order_id: str) -> BrokerOrder:
        """Read one order's current broker-side state (fail closed if unknown)."""

    @abstractmethod
    def query_trades(self, order_id: str) -> tuple:
        """Return the trades (fills) recorded for ``order_id``."""

    @abstractmethod
    def query_orders(self, *, symbol: str | None = None) -> tuple:
        """Return all orders (optionally filtered by exact symbol)."""
