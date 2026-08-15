"""XtQuantBrokerBridge tests (NODEB-001 requirement 4, NODEB-004).

Exercises the concrete bridge with a FAKE trader object that mirrors the
XtQuantTrader surface (``order_stock`` / ``cancel_order_stock`` /
``query_stock_orders`` / ``query_stock_trades`` / ``register_callback``).  No
real XtQuant client is constructed or invoked.

Covers:
* concrete XtQuant argument mapping (account token, side constants 23/24,
  price type 11, volume, price, strategy name, remark);
* order/trade/status mapping into TGrid-owned typed DTOs (NODEB-001 #4);
* fail-closed reads (unknown order id, query failure);
* callback handler: concrete XtQuant payloads -> immutable events -> ONLY
  ``event_sink.put(event)`` (NODEB-004); handler holds no engine/store refs.
"""

import unittest

from tgrid.execution.models import BUY, SELL, OrderStatus
from tgrid.execution.port import (
    BrokerCancelFailedError,
    BrokerError,
    BrokerOrderRejectedError,
)
from tgrid.integrations.xtquant_bridge import (
    STOCK_BUY,
    STOCK_SELL,
    XT_STATUS_TO_TGRID,
    XtQuantBrokerBridge,
    XtQuantCallbackHandler,
)


class _FakeAccount:
    account_id = "fake-account"
    account_type = "STOCK"


class _FakeTrade:
    def __init__(self, traded_id, order_id, traded_volume, traded_price, traded_time):
        self.traded_id = traded_id
        self.order_id = order_id
        self.stock_code = "510300.SH"
        self.traded_volume = traded_volume
        self.traded_price = traded_price
        self.traded_time = traded_time


class _FakeOrder:
    def __init__(self, order_id, order_type, order_volume, price, order_status,
                 traded_volume=0, order_remark=None):
        self.order_id = order_id
        self.stock_code = "510300.SH"
        self.order_type = order_type
        self.order_volume = order_volume
        self.price = price
        self.order_status = order_status
        self.traded_volume = traded_volume
        self.order_remark = order_remark
        self.strategy_name = "TGRID"


class _FakeTrader:
    """Mirrors the XtQuantTrader call surface used by the bridge."""

    def __init__(self):
        self.orders = {}
        self.trades = []
        self.calls = []
        self.callback = None
        self._seq = 0

    def register_callback(self, callback):
        self.callback = callback

    def order_stock(self, account, stock_code, order_type, order_volume,
                    price_type, price, strategy_name="", order_remark=""):
        self.calls.append(
            ("order_stock", dict(
                account=account, stock_code=stock_code, order_type=order_type,
                order_volume=order_volume, price_type=price_type, price=price,
                strategy_name=strategy_name, order_remark=order_remark,
            ))
        )
        self._seq += 1
        order_id = f"XT{self._seq:08d}"
        self.orders[order_id] = _FakeOrder(
            order_id=order_id, order_type=order_type, order_volume=order_volume,
            price=price, order_status=50,
            order_remark=order_remark or None,
        )
        return order_id

    def cancel_order_stock(self, account, order_id):
        self.calls.append(("cancel_order_stock", (account, order_id)))
        if order_id not in self.orders:
            return -1
        order = self.orders[order_id]
        order.order_status = 54  # 已撤
        return 0

    def query_stock_orders(self, account):
        return list(self.orders.values())

    def query_stock_trades(self, account):
        return self.trades


class _Sink:
    def __init__(self):
        self.events = []

    def put(self, event):
        self.events.append(event)


class TestArgumentMapping(unittest.TestCase):
    """NODEB-001: exact XtQuant argument mapping from the port contract."""

    def _bridge(self):
        trader = _FakeTrader()
        bridge = XtQuantBrokerBridge(trader, _FakeAccount(), strategy_name="TGRID")
        return trader, bridge

    def test_buy_maps_to_stock_buy_fix_price(self):
        trader, bridge = self._bridge()
        account = _FakeAccount()
        bridge = XtQuantBrokerBridge(trader, account, strategy_name="TGRID")
        order_id = bridge.place_order(
            symbol="510300.SH", side=BUY, qty=100, limit_price=4.6,
            client_order_key="K1", order_remark="TG_510300SH_B001",
        )
        name, args = trader.calls[0]
        self.assertEqual(name, "order_stock")
        self.assertIs(args["account"], account)
        self.assertEqual(args["stock_code"], "510300.SH")
        self.assertEqual(args["order_type"], STOCK_BUY)
        self.assertEqual(args["order_volume"], 100)
        self.assertEqual(args["price_type"], 11)  # FIX_PRICE
        self.assertEqual(args["price"], 4.6)
        self.assertEqual(args["strategy_name"], "TGRID")
        self.assertEqual(args["order_remark"], "TG_510300SH_B001")
        self.assertTrue(order_id.startswith("XT"))

    def test_sell_maps_to_stock_sell(self):
        trader, bridge = self._bridge()
        bridge.place_order(
            symbol="510300.SH", side=SELL, qty=100, limit_price=4.8,
        )
        name, args = trader.calls[0]
        self.assertEqual(args["order_type"], STOCK_SELL)

    def test_rejection_on_failed_send(self):
        trader, bridge = self._bridge()

        def fail(*a, **k):
            return -1

        trader.order_stock = fail
        with self.assertRaises(BrokerOrderRejectedError):
            bridge.place_order(symbol="510300.SH", side=BUY, qty=100,
                               limit_price=4.6)

    def test_cancel_maps_to_cancel_order_stock(self):
        trader, bridge = self._bridge()
        order_id = bridge.place_order(
            symbol="510300.SH", side=BUY, qty=100, limit_price=4.6,
        )
        bridge.cancel_order(order_id)
        name, args = trader.calls[1]
        self.assertEqual(name, "cancel_order_stock")
        self.assertEqual(args[1], order_id)

    def test_cancel_failure_raises(self):
        trader, bridge = self._bridge()
        with self.assertRaises(BrokerCancelFailedError):
            bridge.cancel_order("NO_SUCH")


class TestStatusMapping(unittest.TestCase):
    """NODEB-001: XtQuant status ints -> TGrid OrderStatus vocabulary."""

    def _order_with_status(self, status):
        return _FakeOrder(
            order_id="X1", order_type=STOCK_BUY, order_volume=100,
            price=4.6, order_status=status,
        )

    def test_pending_reported(self):
        for status in (48, 49, 50):
            self.assertEqual(XT_STATUS_TO_TGRID[status], OrderStatus.SUBMITTED)

    def test_cancel_requested(self):
        for status in (51, 52):
            self.assertEqual(XT_STATUS_TO_TGRID[status], OrderStatus.CANCEL_REQUESTED)

    def test_canceled(self):
        for status in (53, 54):
            self.assertEqual(XT_STATUS_TO_TGRID[status], OrderStatus.CANCELED)

    def test_partial_and_filled(self):
        self.assertEqual(XT_STATUS_TO_TGRID[55], OrderStatus.PARTIAL)
        self.assertEqual(XT_STATUS_TO_TGRID[56], OrderStatus.FILLED)

    def test_rejected(self):
        self.assertEqual(XT_STATUS_TO_TGRID[57], OrderStatus.REJECTED)

    def test_unknown_fails_closed(self):
        bridge = XtQuantBrokerBridge(_FakeTrader(), _FakeAccount())
        dto = bridge._map_order(self._order_with_status(255))
        self.assertEqual(dto.status, OrderStatus.UNKNOWN)

    def test_query_order_returns_typed_dto(self):
        trader = _FakeTrader()
        bridge = XtQuantBrokerBridge(trader, _FakeAccount())
        order_id = bridge.place_order(
            symbol="510300.SH", side=BUY, qty=100, limit_price=4.6,
        )
        order = trader.orders[order_id]
        order.order_status = 55
        order.traded_volume = 60
        dto = bridge.query_order(order_id)
        self.assertEqual(dto.order_id, order_id)
        self.assertEqual(dto.side, BUY)
        self.assertEqual(dto.qty, 100)
        self.assertEqual(dto.status, OrderStatus.PARTIAL)
        self.assertEqual(dto.filled_qty, 60)
        # Core must never see the raw object shape.
        self.assertFalse(hasattr(dto, "order_type"))

    def test_query_order_unknown_id_fails_closed(self):
        bridge = XtQuantBrokerBridge(_FakeTrader(), _FakeAccount())
        with self.assertRaises(BrokerError):
            bridge.query_order("NO_SUCH")

    def test_query_trades_maps_to_dtos(self):
        trader = _FakeTrader()
        bridge = XtQuantBrokerBridge(trader, _FakeAccount())
        order_id = bridge.place_order(
            symbol="510300.SH", side=BUY, qty=100, limit_price=4.6,
        )
        trader.trades.append(_FakeTrade("T1", order_id, 60, 4.6, "20260815093500"))
        trades = bridge.query_trades(order_id)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].trade_id, "T1")
        self.assertEqual(trades[0].price, 4.6)


class TestCallbackIsolation(unittest.TestCase):
    """NODEB-004: concrete handler converts payloads to events; only enqueues."""

    def test_order_callback_only_enqueues_immutable_event(self):
        sink = _Sink()
        handler = XtQuantCallbackHandler(sink)
        raw = _FakeOrder(
            order_id="X1", order_type=STOCK_BUY, order_volume=100,
            price=4.6, order_status=56, traded_volume=100,
            order_remark="TG_510300SH_B001",
        )
        handler.on_stock_order(raw)
        self.assertEqual(len(sink.events), 1)
        event = sink.events[0]
        self.assertEqual(event.order_id, "X1")
        self.assertEqual(event.status, OrderStatus.FILLED)
        self.assertEqual(event.filled_qty, 100)
        # Events are immutable and data-only.
        self.assertFalse(hasattr(event, "broker"))
        self.assertFalse(hasattr(event, "engine"))
        with self.assertRaises(Exception):
            event.order_id = "MUTATED"  # frozen dataclass

    def test_trade_callback_only_enqueues_immutable_event(self):
        sink = _Sink()
        handler = XtQuantCallbackHandler(sink)
        raw = _FakeTrade("T1", "X1", 60, 4.6, "20260815093500")
        handler.on_stock_trade(raw)
        self.assertEqual(len(sink.events), 1)
        event = sink.events[0]
        self.assertEqual(event.trade_id, "T1")
        self.assertEqual(event.qty, 60)

    def test_handler_holds_no_engine_or_store_references(self):
        sink = _Sink()
        handler = XtQuantCallbackHandler(sink)
        self.assertFalse(hasattr(handler, "engine"))
        self.assertFalse(hasattr(handler, "store"))
        self.assertFalse(hasattr(handler, "adapter"))
        self.assertFalse(hasattr(handler, "broker"))

    def test_bridge_registers_handler_on_trader(self):
        trader = _FakeTrader()
        sink = _Sink()
        bridge = XtQuantBrokerBridge(trader, _FakeAccount(), event_sink=sink)
        self.assertIsNotNone(bridge.callback_handler)
        self.assertIs(trader.callback, bridge.callback_handler)

    def test_no_sink_means_no_handler(self):
        bridge = XtQuantBrokerBridge(_FakeTrader(), _FakeAccount())
        self.assertIsNone(bridge.callback_handler)


if __name__ == "__main__":
    unittest.main()
