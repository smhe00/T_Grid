"""The ONE concrete XtQuant broker bridge (NODEB-001).

This module is the only place in the repository allowed to call the real XtQuant
order/cancel surface (``order_stock`` / ``cancel_order_stock``); the capability
scan allowlists exactly these call sites and fails on any additional direct
real-broker invocation anywhere else in ``src``.

The bridge maps the shared :class:`~tgrid.execution.port.BrokerPort` contract to
``XtQuantTrader``:

* ``place_order``  -> ``trader.order_stock(account, symbol, order_type,
  volume, price_type, price, strategy_name, order_remark)``;
* ``cancel_order`` -> ``trader.cancel_order_stock(account, order_id)``;
* reads           -> ``query_stock_orders`` / ``query_stock_trades``.

Every broker object crosses the boundary as a TGrid-owned typed DTO
(:class:`BrokerOrder` / :class:`BrokerTrade`); raw XtQuant object shapes never
leak into the core.  Broker callback payloads are converted by the bridge-owned
:class:`XtQuantCallbackHandler` into immutable data-only events that are ONLY
enqueued onto an injected event sink (NODEB-004).

The bridge never constructs XtQuantTrader itself and never trades on its own:
production wires a real ``XtQuantTrader`` + ``StockAccount`` in; tests wire
fakes.  No real order/cancel is invoked before Audit Node B PASS.
"""

from __future__ import annotations

from dataclasses import dataclass

from tgrid.execution.models import BUY, SELL, OrderStatus
from tgrid.execution.port import (
    BrokerCancelFailedError,
    BrokerDisconnectedError,
    BrokerError,
    BrokerOrder,
    BrokerOrderRejectedError,
    BrokerPort,
    BrokerTrade,
)

# XtQuant side / price-type constants (mirror xtquant.xtconstant; kept local so
# the bridge stays importable and testable without the closed-source client).
STOCK_BUY = 23
STOCK_SELL = 24
FIX_PRICE = 11  # 限价单

# XtQuant order_status ints (xtconstant ORDER_*) -> TGrid OrderStatus.
# 48 未报 / 49 待报 / 50 已报 -> SUBMITTED; 51 已报待撤 / 52 部成待撤 ->
# CANCEL_REQUESTED; 53 部撤 / 54 已撤 -> CANCELED; 55 部成 -> PARTIAL;
# 56 已成 -> FILLED; 57 废单 -> REJECTED; anything else -> UNKNOWN (fail closed).
XT_STATUS_TO_TGRID = {
    48: OrderStatus.SUBMITTED,
    49: OrderStatus.SUBMITTED,
    50: OrderStatus.SUBMITTED,
    51: OrderStatus.CANCEL_REQUESTED,
    52: OrderStatus.CANCEL_REQUESTED,
    53: OrderStatus.CANCELED,
    54: OrderStatus.CANCELED,
    55: OrderStatus.PARTIAL,
    56: OrderStatus.FILLED,
    57: OrderStatus.REJECTED,
}


@dataclass(frozen=True)
class BrokerOrderEvent:
    """Immutable, data-only order callback event (NODEB-004)."""

    kind: str = "BROKER_ORDER"
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    status: str = ""
    qty: int = 0
    filled_qty: int = 0
    price: float = 0.0
    client_order_key: str | None = None
    order_remark: str | None = None


@dataclass(frozen=True)
class BrokerTradeEvent:
    """Immutable, data-only trade callback event (NODEB-004)."""

    kind: str = "BROKER_TRADE"
    trade_id: str = ""
    order_id: str = ""
    symbol: str = ""
    qty: int = 0
    price: float = 0.0
    time: str = ""


class XtQuantCallbackHandler:
    """Concrete XtQuant callback handler (NODEB-004).

    Owned by the bridge; receives raw XtQuant payloads from the trader and
    performs ONLY ``event_sink.put(immutable_event)``.  It holds no reference
    to the engine, execution store, strategy state, or an order-capable
    adapter — state changes happen later on the single strategy/event thread.
    """

    def __init__(self, event_sink: object) -> None:
        if not hasattr(event_sink, "put") or not callable(getattr(event_sink, "put")):
            raise BrokerError("event_sink must expose a callable .put()")
        self._event_sink = event_sink

    # -- XtQuantTraderCallback-compatible entry points ---------------------

    def on_stock_order(self, order) -> None:
        """Convert an XtOrder payload into an immutable event and enqueue it."""
        side = BUY if getattr(order, "order_type", None) == STOCK_BUY else (
            SELL if getattr(order, "order_type", None) == STOCK_SELL else ""
        )
        self._event_sink.put(
            BrokerOrderEvent(
                order_id=str(getattr(order, "order_id", "") or ""),
                symbol=str(getattr(order, "stock_code", "") or ""),
                side=side,
                status=XT_STATUS_TO_TGRID.get(
                    getattr(order, "order_status", None), OrderStatus.UNKNOWN
                ),
                qty=int(getattr(order, "order_volume", 0) or 0),
                filled_qty=int(getattr(order, "traded_volume", 0) or 0),
                price=float(getattr(order, "price", 0.0) or 0.0),
                order_remark=getattr(order, "order_remark", None),
            )
        )

    def on_stock_trade(self, trade) -> None:
        """Convert an XtTrade payload into an immutable event and enqueue it."""
        self._event_sink.put(
            BrokerTradeEvent(
                trade_id=str(getattr(trade, "traded_id", "") or ""),
                order_id=str(getattr(trade, "order_id", "") or ""),
                symbol=str(getattr(trade, "stock_code", "") or ""),
                qty=int(getattr(trade, "traded_volume", 0) or 0),
                price=float(getattr(trade, "traded_price", 0.0) or 0.0),
                time=str(getattr(trade, "traded_time", "") or ""),
            )
        )

    def on_connected(self) -> None:
        pass

    def on_disconnected(self) -> None:
        pass

    def on_account_status(self, status) -> None:
        pass

    def on_order_error(self, order_error) -> None:
        pass

    def on_cancel_error(self, cancel_error) -> None:
        pass


class XtQuantBrokerBridge(BrokerPort):
    """Concrete XtQuantTrader bridge (the only audited real call sites).

    ``trader`` is the injected XtQuantTrader-like object (real in production, a
    fake in tests) and ``account`` the XtQuant account token.  ``event_sink``
    (optional) is an object with a callable ``.put`` — normally the EventQueue
    — that receives only immutable callback events (NODEB-004).
    """

    def __init__(
        self,
        trader: object,
        account: object,
        *,
        strategy_name: str = "TGRID",
        event_sink: object | None = None,
    ) -> None:
        if type(strategy_name) is not str or strategy_name == "":
            raise BrokerError("strategy_name must be a non-empty string")
        self._trader = trader
        self._account = account
        self._strategy_name = strategy_name
        self._handler = XtQuantCallbackHandler(event_sink) if event_sink is not None else None
        if self._handler is not None and hasattr(trader, "register_callback"):
            trader.register_callback(self._handler)

    @property
    def callback_handler(self) -> XtQuantCallbackHandler | None:
        """The concrete callback handler (None if no event sink was wired)."""
        return self._handler

    # ------------------------------------------------------- order surface

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
        """The ONLY order_stock call site in the repository (NODEB-001)."""
        if type(symbol) is not str or symbol == "":
            raise BrokerError("symbol must be a non-empty string")
        if side not in (BUY, SELL):
            raise BrokerError("side must be BUY or SELL")
        if type(qty) is not int or qty <= 0:
            raise BrokerError("qty must be a positive plain int")
        if type(limit_price) not in (int, float) or isinstance(limit_price, bool) or limit_price <= 0:
            raise BrokerError("limit_price must be a positive number")
        order_type = STOCK_BUY if side == BUY else STOCK_SELL
        remark = order_remark if order_remark is not None else (client_order_key or "")
        try:
            result = self._trader.order_stock(
                self._account, symbol, order_type, qty, FIX_PRICE,
                float(limit_price), self._strategy_name, remark,
            )
        except BrokerError:
            raise
        except Exception as exc:  # noqa: BLE001 - broker boundary, fail closed
            raise BrokerDisconnectedError("broker send failed") from exc
        order_id = getattr(result, "order_id", result)
        if order_id is None or str(order_id) in ("", "-1"):
            raise BrokerOrderRejectedError("XtQuantTrader rejected the order")
        return str(order_id)

    def cancel_order(self, order_id: str) -> None:
        """The ONLY cancel_order_stock call site in the repository (NODEB-001)."""
        if type(order_id) is not str or order_id == "":
            raise BrokerError("order_id must be a non-empty string")
        try:
            result = self._trader.cancel_order_stock(self._account, order_id)
        except BrokerError:
            raise
        except Exception as exc:  # noqa: BLE001 - broker boundary, fail closed
            raise BrokerDisconnectedError("broker cancel failed") from exc
        cancel_result = getattr(result, "cancel_result", result)
        if cancel_result != 0:
            raise BrokerCancelFailedError("XtQuantTrader failed to cancel the order")

    # --------------------------------------------------------- read surface

    def query_order(self, order_id: str) -> BrokerOrder:
        if type(order_id) is not str or order_id == "":
            raise BrokerError("order_id must be a non-empty string")
        try:
            orders = self._trader.query_stock_orders(self._account)
        except BrokerError:
            raise
        except Exception as exc:  # noqa: BLE001 - broker boundary, fail closed
            raise BrokerDisconnectedError("broker query failed") from exc
        for raw in orders:
            if str(getattr(raw, "order_id", "")) == order_id:
                return self._map_order(raw)
        raise BrokerError(f"broker has no order {order_id!r}")

    def query_trades(self, order_id: str) -> tuple:
        if type(order_id) is not str or order_id == "":
            raise BrokerError("order_id must be a non-empty string")
        try:
            trades = self._trader.query_stock_trades(self._account)
        except BrokerError:
            raise
        except Exception as exc:  # noqa: BLE001 - broker boundary, fail closed
            raise BrokerDisconnectedError("broker query failed") from exc
        return tuple(
            self._map_trade(raw)
            for raw in trades
            if str(getattr(raw, "order_id", "")) == order_id
        )

    def query_orders(self, *, symbol: str | None = None) -> tuple:
        if symbol is not None and type(symbol) is not str:
            raise BrokerError("symbol must be a string or None")
        try:
            orders = self._trader.query_stock_orders(self._account)
        except BrokerError:
            raise
        except Exception as exc:  # noqa: BLE001 - broker boundary, fail closed
            raise BrokerDisconnectedError("broker query failed") from exc
        return tuple(
            self._map_order(raw)
            for raw in orders
            if symbol is None or getattr(raw, "stock_code", None) == symbol
        )

    # --------------------------------------------------------------- mapping

    @staticmethod
    def _map_order(raw) -> BrokerOrder:
        side = BUY if getattr(raw, "order_type", None) == STOCK_BUY else (
            SELL if getattr(raw, "order_type", None) == STOCK_SELL else ""
        )
        return BrokerOrder(
            order_id=str(getattr(raw, "order_id", "") or ""),
            symbol=str(getattr(raw, "stock_code", "") or ""),
            side=side,
            qty=int(getattr(raw, "order_volume", 0) or 0),
            limit_price=float(getattr(raw, "price", 0.0) or 0.0),
            status=XT_STATUS_TO_TGRID.get(
                getattr(raw, "order_status", None), OrderStatus.UNKNOWN
            ),
            filled_qty=int(getattr(raw, "traded_volume", 0) or 0),
            order_remark=getattr(raw, "order_remark", None),
        )

    @staticmethod
    def _map_trade(raw) -> BrokerTrade:
        return BrokerTrade(
            trade_id=str(getattr(raw, "traded_id", "") or ""),
            order_id=str(getattr(raw, "order_id", "") or ""),
            qty=int(getattr(raw, "traded_volume", 0) or 0),
            price=float(getattr(raw, "traded_price", 0.0) or 0.0),
            time=str(getattr(raw, "traded_time", "") or ""),
        )
