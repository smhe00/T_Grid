"""Deterministic simulated broker for the Gate 4 dry run (design §39).

:class:`SimBroker` behaves like a QMT broker surface but is fully offline and
scriptable.  Every behaviour — accept, partial fill, full fill, reject,
timeout, cancel failure, disconnect — is driven by an explicit, per-order
:class:`SimOrder` ``script`` the test (or the dry-run harness) controls, so the
whole §39 failure matrix is reproducible without real markets.

The broker keeps its own order/trade book so crash recovery (design §23) can be
tested: orders/trades survive independently of the local execution store.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tgrid.risk.exceptions import TGridError


class BrokerError(TGridError):
    """Base class for simulated broker failures."""


class BrokerDisconnectedError(BrokerError):
    """The simulated broker is disconnected (network failure, design §23)."""


class BrokerOrderRejectedError(BrokerError):
    """The simulated broker rejected the order at send time."""


class BrokerCancelFailedError(BrokerError):
    """The simulated broker failed to cancel the order (design §25)."""


@dataclass(frozen=True)
class SimFill:
    """One simulated trade against a SimOrder."""

    trade_id: str
    order_id: str
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
    * ``("CANCEL_FAIL",)`` — a cancel attempt raises BrokerCancelFailedError.

    The script is consumed in order as the executor queries/fills the order;
    a step is only consumed once.  ``status`` tracks the broker-side lifecycle.
    """

    order_id: str
    symbol: str
    side: str
    qty: int
    limit_price: float
    client_order_key: str | None = None
    order_remark: str | None = None
    script: tuple = field(default_factory=tuple)
    status: str = "SUBMITTED"
    filled_qty: int = 0
    trades: list = field(default_factory=list)


class SimBroker:
    """Offline simulated broker with an in-memory order/trade book.

    ``connected`` toggles disconnect behaviour: any operation while
    disconnected raises :class:`BrokerDisconnectedError`.  ``place_*`` return
    the broker order id immediately (deterministic); fills/rejects are applied
    on the next :meth:`query_orders` / :meth:`query_trades` / :meth:`tick`
    call, consuming the script one step at a time.
    """

    def __init__(self) -> None:
        self._orders: dict = {}
        self._trades: dict = {}
        self._seq = 0
        self.connected = True

    # ------------------------------------------------------------ plumbing

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}{self._seq:06d}"

    def _require_connected(self) -> None:
        if not self.connected:
            raise BrokerDisconnectedError("simulated broker is disconnected")

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
        """Place an order with an empty script (submitted, no auto-fill).

        ``client_order_key`` / ``order_remark`` are stored on the broker-side
        order so crash recovery can match broker orders back to local intents
        (design §23); they are not used for any trading decision here.
        """
        self._require_connected()
        if type(symbol) is not str or not symbol:
            raise BrokerError("symbol must be a non-empty string")
        if side not in ("BUY", "SELL"):
            raise BrokerError("side must be BUY or SELL")
        if type(qty) is not int or qty <= 0:
            raise BrokerError("qty must be a positive int")
        if type(limit_price) not in (int, float) or isinstance(limit_price, bool) or limit_price <= 0:
            raise BrokerError("limit_price must be a positive number")
        if client_order_key is not None and type(client_order_key) is not str:
            raise BrokerError("client_order_key must be a string or None")
        if order_remark is not None and type(order_remark) is not str:
            raise BrokerError("order_remark must be a string or None")
        order_id = self._next_id("SIM")
        self._orders[order_id] = SimOrder(
            order_id=order_id, symbol=symbol, side=side, qty=qty,
            limit_price=float(limit_price),
            client_order_key=client_order_key, order_remark=order_remark,
        )
        return order_id

    def get_order(self, order_id: str) -> SimOrder:
        if order_id not in self._orders:
            raise BrokerError("unknown order id")
        return self._orders[order_id]

    # ------------------------------------------------------------ lifecycle

    def tick_order(self, order_id: str) -> None:
        """Advance one script step for ``order_id`` (deterministic)."""
        self._require_connected()
        order = self.get_order(order_id)
        if order.status in ("FILLED", "REJECTED", "CANCELED"):
            return
        if not order.script:
            return
        step = order.script[0]
        order.script = order.script[1:]
        action = step[0]
        if action == "FILL":
            qty, price = int(step[1]), float(step[2])
            if qty <= 0 or price <= 0:
                raise BrokerError("invalid FILL step")
            remaining = order.qty - order.filled_qty
            fill_qty = min(qty, remaining)
            if fill_qty <= 0:
                return
            trade_id = self._next_id("TRD")
            order.filled_qty += fill_qty
            order.trades.append(
                SimFill(trade_id=trade_id, order_id=order_id, qty=fill_qty, price=price, time="SIM")
            )
            self._trades[trade_id] = order.trades[-1]
            if order.filled_qty >= order.qty:
                order.status = "FILLED"
            else:
                order.status = "PARTIAL"
        elif action == "REJECT":
            order.status = "REJECTED"
        elif action == "TIMEOUT":
            pass  # stays SUBMITTED, never fills on its own
        elif action == "CANCEL_FAIL":
            pass  # the next cancel attempt will fail (see cancel_order)
        else:
            raise BrokerError(f"unknown script action {action!r}")

    def cancel_order(self, order_id: str) -> None:
        """Cancel an order; fails closed on unknown id / disconnect / script."""
        self._require_connected()
        order = self.get_order(order_id)
        if order.status in ("FILLED", "CANCELED", "REJECTED"):
            raise BrokerError(
                f"cannot cancel order in terminal state {order.status!r}"
            )
        # A CANCEL_FAIL step forces one failed cancel attempt (design §25:
        # after cancel you must re-query, never assume).
        if order.script and order.script[0][0] == "CANCEL_FAIL":
            order.script = order.script[1:]
            raise BrokerCancelFailedError("simulated cancel failure")
        order.status = "CANCELED"

    def query_order(self, order_id: str) -> SimOrder:
        """Read the current broker-side order state (design §24/§25)."""
        self._require_connected()
        return self.get_order(order_id)

    def query_trades(self, order_id: str) -> tuple:
        """Return the trades (fills) recorded for ``order_id``."""
        self._require_connected()
        order = self.get_order(order_id)
        return tuple(order.trades)

    def query_orders(self, *, symbol: str | None = None) -> tuple:
        self._require_connected()
        if symbol is None:
            return tuple(self._orders.values())
        return tuple(o for o in self._orders.values() if o.symbol == symbol)
