"""Deterministic simulated broker implementing the public-core BrokerPort.

Migration Phase D: ``SimBroker`` now implements the qmt-execution-core
``BrokerPort`` protocol (native int order ids, ``ExecutionRequest`` in,
``BrokerOrder`` / ``CancelRequestResult`` out) instead of TGrid's deleted
generic ``port.py``.  It stays fully offline and scriptable: every behaviour —
accept, partial fill, full fill, reject, timeout, cancel failure, disconnect —
is driven by an explicit per-order ``SimOrder.script`` that the test or the
dry-run harness controls.

The simulation-only hooks (``get_order`` / ``tick_order`` / ``script``) remain
here for :class:`~tgrid.execution.simdriver.SimulationDriver`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from qmt_execution_core.domain import (
    BrokerOrder,
    BrokerOrderStatus,
    CancelRequestResult,
    ExecutionRequest,
    Side,
)

__all__ = [
    "SimFill",
    "SimOrder",
    "SimBroker",
]


@dataclass(frozen=True)
class SimFill:
    """One simulated trade against a SimOrder."""

    trade_id: str
    order_id: int
    qty: int
    price: float
    time: str


@dataclass
class SimOrder:
    """A simulated broker-side order with a deterministic script.

    ``script`` is a tuple of steps; each step is one of:

    * ``("FILL", qty, price)`` — fill ``qty`` shares at ``price``;
    * ``("REJECT",)`` — the order is rejected by the broker;
    * ``("TIMEOUT",)`` — the order stays open and is never filled on its own;
    * ``("CANCEL_FAIL",)`` — a cancel attempt fails.

    The script is consumed in order as the executor queries/fills the order;
    a step is only consumed once.  ``status`` is a public-core
    ``BrokerOrderStatus``.
    """

    order_id: int
    symbol: str
    side: Side
    qty: int
    limit_price: float
    client_order_key: str | None = None
    order_remark: str | None = None
    script: tuple = field(default_factory=tuple)
    status: BrokerOrderStatus = BrokerOrderStatus.WORKING
    filled_qty: int = 0
    average_fill_price: float | None = None
    trades: list = field(default_factory=list)


class SimBroker:
    """Offline simulated broker with an in-memory order/trade book.

    Implements the public-core ``BrokerPort`` protocol (native int order ids,
    ``ExecutionRequest`` / ``BrokerOrder`` / ``CancelRequestResult`` DTOs).
    ``connected`` toggles disconnect behaviour: any operation while
    disconnected raises an error.  ``place_order`` returns the order id
    immediately; fills/rejects are applied on the next query, consuming the
    script one step at a time.  ``get_order`` / ``tick_order`` are
    simulation-only hooks used by ``SimulationDriver``.
    """

    def __init__(self) -> None:
        self._orders: dict = {}
        self._trades: dict = {}
        self._seq = 0
        self.connected = True
        self.reject_on_submit = False

    # ------------------------------------------------------------ plumbing

    def _next_id(self) -> int:
        self._seq += 1
        return self._seq

    def _require_connected(self) -> None:
        if not self.connected:
            from qmt_execution_core.exceptions import BrokerError

            raise BrokerError("simulated broker is disconnected")

    # ------------------------------------------------------- port lifecycle

    def execution_healthy(self) -> bool:
        """Public-core health probe: healthy while connected."""
        return self.connected

    def place_order(self, request: ExecutionRequest) -> int:
        """Place an order with an empty script (working, no auto-fill)."""
        self._require_connected()
        if self.reject_on_submit:
            from qmt_execution_core.exceptions import BrokerSubmissionRejected

            raise BrokerSubmissionRejected("simulated definitive reject")
        order_id = self._next_id()
        self._orders[order_id] = SimOrder(
            order_id=order_id, symbol=request.symbol, side=request.side,
            qty=request.qty, limit_price=float(request.limit_price),
            client_order_key=request.client_order_id,
            order_remark=request.order_remark,
        )
        return order_id

    def cancel_order(self, order_id: int) -> CancelRequestResult:
        """Cancel an order; fails closed on unknown id / disconnect / script.

        A ``("CANCEL_FAIL",)`` script step forces one failed cancel attempt
        (after a cancel you must re-query, never assume).  A successful cancel
        marks the order CANCEL_PENDING; the confirmation is delivered by the
        next query (public-core cancel semantics).
        """
        self._require_connected()
        order = self.get_order(order_id)
        if order.status in (
            BrokerOrderStatus.FILLED,
            BrokerOrderStatus.CANCELLED,
            BrokerOrderStatus.REJECTED,
        ):
            from qmt_execution_core.exceptions import BrokerError

            raise BrokerError(
                f"cannot cancel order in terminal state {order.status.value!r}"
            )
        if order.script and order.script[0][0] == "CANCEL_FAIL":
            order.script = order.script[1:]
            from qmt_execution_core.exceptions import BrokerError

            raise BrokerError("simulated cancel failure")
        order.status = BrokerOrderStatus.CANCEL_PENDING
        return CancelRequestResult.ACCEPTED

    # ------------------------------------------------------- port read side

    def query_order(self, order_id: int) -> BrokerOrder:
        """Read the current broker-side order state."""
        self._require_connected()
        order = self.get_order(order_id)
        return self._to_broker_order(order)

    def query_orders(self) -> tuple:
        """Return all broker-side orders (public-core contract)."""
        self._require_connected()
        return tuple(self._to_broker_order(o) for o in self._orders.values())

    def _to_broker_order(self, order: SimOrder) -> BrokerOrder:
        return BrokerOrder(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            filled_qty=order.filled_qty,
            status=order.status,
            order_remark=order.order_remark or "",
            client_order_id=order.client_order_key or "",
            average_fill_price=order.average_fill_price,
        )

    # -------------------------------------------------- simulation-only hooks

    def get_order(self, order_id: int) -> SimOrder:
        """Simulation-only hook: return the mutable SimOrder for script work."""
        if order_id not in self._orders:
            from qmt_execution_core.exceptions import BrokerError

            raise BrokerError("unknown order id")
        return self._orders[order_id]

    def tick_order(self, order_id: int) -> None:
        """Advance one script step for ``order_id`` (deterministic)."""
        self._require_connected()
        order = self.get_order(order_id)
        if order.status in (
            BrokerOrderStatus.FILLED,
            BrokerOrderStatus.REJECTED,
            BrokerOrderStatus.CANCELLED,
        ):
            return
        if not order.script:
            return
        step = order.script[0]
        order.script = order.script[1:]
        action = step[0]
        if action == "FILL":
            qty, price = int(step[1]), float(step[2])
            if qty <= 0 or price <= 0:
                from qmt_execution_core.exceptions import BrokerError

                raise BrokerError("invalid FILL step")
            remaining = order.qty - order.filled_qty
            fill_qty = min(qty, remaining)
            if fill_qty <= 0:
                return
            trade_id = f"TRD{self._next_id():06d}"
            order.filled_qty += fill_qty
            order.average_fill_price = price
            order.trades.append(
                SimFill(trade_id=trade_id, order_id=order_id, qty=fill_qty,
                        price=price, time="SIM")
            )
            self._trades[trade_id] = order.trades[-1]
            if order.filled_qty >= order.qty:
                order.status = BrokerOrderStatus.FILLED
            else:
                order.status = BrokerOrderStatus.PARTIALLY_FILLED
        elif action == "REJECT":
            order.status = BrokerOrderStatus.REJECTED
        elif action == "TIMEOUT":
            pass  # stays WORKING, never fills on its own
        elif action == "CANCEL_FAIL":
            pass  # the next cancel attempt will fail (see cancel_order)
        else:
            from qmt_execution_core.exceptions import BrokerError

            raise BrokerError(f"unknown script action {action!r}")

    def query_trades(self, order_id: int) -> tuple:
        """Simulation helper: trades (fills) recorded for ``order_id``."""
        self._require_connected()
        order = self.get_order(order_id)
        return tuple(order.trades)
