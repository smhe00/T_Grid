"""XtQuantBrokerBridge tests (NODEB-001 #4, NODEB-004, I2-001, I2-003).

Exercises the concrete bridge with a FAKE trader object that mirrors the
XtQuantTrader surface (``order_stock`` / ``cancel_order_stock`` /
``query_stock_orders`` / ``query_stock_trades`` / ``register_callback``).  No
real XtQuant client is constructed or invoked.

Covers:
* concrete XtQuant argument mapping (account token, side constants 23/24,
  price type 11, volume, price, strategy name, remark);
* native **int** order-id contract (I2-001): the fake trader uses positive int
  ids exactly like the official XtQuant interface, the bridge converts once at
  its boundary, and the actual cancel argument is asserted to be an int;
* order/trade/status mapping into TGrid-owned typed DTOs (NODEB-001 #4);
* fail-closed reads (unknown order id, query failure);
* callback handler: concrete XtQuant payloads -> immutable events -> ONLY
  enqueue/put (NODEB-004 / I2-003), including disconnect/account-status/
  order-error/cancel-error events, and health flips on enqueue failure.
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
    BrokerAccountStatusEvent,
    BrokerCancelErrorEvent,
    BrokerDisconnectEvent,
    BrokerOrderErrorEvent,
    XtQuantBrokerBridge,
    XtQuantCallbackHandler,
)
from tgrid.execution.port import BrokerQueryAmbiguous


class _FakeAccount:
    account_id = "fake-account"
    account_type = "STOCK"


class _FakeTrade:
    def __init__(self, traded_id, order_id, traded_volume, traded_price, traded_time):
        self.traded_id = traded_id
        self.order_id = order_id  # native int
        self.stock_code = "510300.SH"
        self.traded_volume = traded_volume
        self.traded_price = traded_price
        self.traded_time = traded_time


class _FakeOrder:
    def __init__(self, order_id, order_type, order_volume, price, order_status,
                 traded_volume=0, order_remark=None, order_time=""):
        self.order_id = order_id  # native int
        self.stock_code = "510300.SH"
        self.order_type = order_type
        self.order_volume = order_volume
        self.price = price
        self.order_status = order_status
        self.traded_volume = traded_volume
        self.order_remark = order_remark
        self.order_time = order_time
        self.strategy_name = "TGRID"


class _FakeTrader:
    """Mirrors the XtQuantTrader call surface; native order ids are INTs."""

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
        order_id = 1000 + self._seq  # native int, mirrors official contract
        self.orders[order_id] = _FakeOrder(
            order_id=order_id, order_type=order_type, order_volume=order_volume,
            price=price, order_status=50,
            order_remark=order_remark or None,
            order_time="2026-08-15 09:35:00",
        )
        return order_id

    def cancel_order_stock(self, account, order_id):
        self.calls.append(("cancel_order_stock", (account, order_id)))
        if order_id not in self.orders:
            return -1
        order = self.orders[order_id]
        order.order_status = 54  # 已撤
        return 0

    def query_stock_orders(self, account, cancelable_only=False):
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
        self.assertEqual(order_id, "1001")  # TGrid string serialization of int

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
            return -1  # native failure marker

        trader.order_stock = fail
        with self.assertRaises(BrokerOrderRejectedError):
            bridge.place_order(symbol="510300.SH", side=BUY, qty=100,
                               limit_price=4.6)

    def test_cancel_maps_to_cancel_order_stock_with_int(self):
        trader, bridge = self._bridge()
        order_id = bridge.place_order(
            symbol="510300.SH", side=BUY, qty=100, limit_price=4.6,
        )
        bridge.cancel_order(order_id)
        name, args = trader.calls[1]
        self.assertEqual(name, "cancel_order_stock")
        # I2-001: the native cancel boundary must receive an INT, not a string.
        self.assertIs(type(args[1]), int)
        self.assertEqual(args[1], int(order_id))

    def test_cancel_failure_raises(self):
        trader, bridge = self._bridge()
        with self.assertRaises(BrokerCancelFailedError):
            bridge.cancel_order("999999")

    def test_native_conversion_rejects_non_decimal(self):
        bridge = XtQuantBrokerBridge(_FakeTrader(), _FakeAccount())
        with self.assertRaises(BrokerError):
            bridge.cancel_order("XT00000001")
        with self.assertRaises(BrokerError):
            bridge.cancel_order("1.5")
        with self.assertRaises(BrokerError):
            bridge.cancel_order("")


class TestStatusMapping(unittest.TestCase):
    """NODEB-001: XtQuant status ints -> TGrid OrderStatus vocabulary."""

    def _order_with_status(self, status):
        return _FakeOrder(
            order_id=1, order_type=STOCK_BUY, order_volume=100,
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
        order = trader.orders[int(order_id)]
        order.order_status = 55
        order.traded_volume = 60
        dto = bridge.query_order(order_id)
        self.assertEqual(dto.order_id, order_id)
        self.assertEqual(dto.side, BUY)
        self.assertEqual(dto.qty, 100)
        self.assertEqual(dto.status, OrderStatus.PARTIAL)
        self.assertEqual(dto.filled_qty, 60)
        # Core must never see the raw object shape or the native int directly.
        self.assertFalse(hasattr(dto, "order_type"))

    def test_query_order_unknown_id_fails_closed(self):
        bridge = XtQuantBrokerBridge(_FakeTrader(), _FakeAccount())
        with self.assertRaises(BrokerError):
            bridge.query_order("999999")

    def test_query_trades_maps_to_dtos(self):
        trader = _FakeTrader()
        bridge = XtQuantBrokerBridge(trader, _FakeAccount())
        order_id = bridge.place_order(
            symbol="510300.SH", side=BUY, qty=100, limit_price=4.6,
        )
        trader.trades.append(_FakeTrade("T1", int(order_id), 60, 4.6, "20260815093500"))
        trades = bridge.query_trades(order_id)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].trade_id, "T1")
        self.assertEqual(trades[0].price, 4.6)


class TestStrictQuery(unittest.TestCase):
    """NODEB-RR-002: bounded-retry strict queries; None never means empty."""

    def test_none_never_empty_success(self):
        trader = _FakeTrader()

        def returns_none(*a, **k):
            return None

        trader.query_stock_orders = returns_none
        bridge = XtQuantBrokerBridge(trader, _FakeAccount())
        with self.assertRaises(BrokerQueryAmbiguous):
            bridge.query_orders()

    def test_transient_exception_then_success(self):
        trader = _FakeTrader()
        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return list(trader.orders.values())

        trader.query_stock_orders = flaky
        bridge = XtQuantBrokerBridge(trader, _FakeAccount())
        bridge.place_order(symbol="510300.SH", side=BUY, qty=100,
                           limit_price=4.6)
        orders = bridge.query_orders()
        self.assertEqual(len(orders), 1)
        self.assertGreaterEqual(calls["n"], 2)

    def test_persistent_exception_fails_closed(self):
        trader = _FakeTrader()

        def always_fails(*a, **k):
            raise RuntimeError("persistent")

        trader.query_stock_orders = always_fails
        bridge = XtQuantBrokerBridge(trader, _FakeAccount())
        with self.assertRaises(BrokerQueryAmbiguous):
            bridge.query_orders()

    def test_empty_list_is_legit_success(self):
        trader = _FakeTrader()
        bridge = XtQuantBrokerBridge(trader, _FakeAccount())
        orders = bridge.query_orders()
        self.assertEqual(orders, ())  # empty success, not ambiguous

    def test_duplicate_match_fails_closed(self):
        # Native query_stock_order present: duplicates can't arise; force the
        # scan fallback by removing the exact-order method and duplicating ids.
        trader = _FakeTrader()
        bridge = XtQuantBrokerBridge(trader, _FakeAccount())
        o1 = bridge.place_order(symbol="510300.SH", side=BUY, qty=100,
                                limit_price=4.6)
        o2 = bridge.place_order(symbol="510300.SH", side=BUY, qty=100,
                                limit_price=4.6)
        # Duplicate the first order id inside the trader book.
        trader.orders[int(o2)] = trader.orders[int(o1)]
        trader.query_stock_order = None  # force all-orders scan fallback
        with self.assertRaises(BrokerQueryAmbiguous):
            bridge.query_order(o1)

    def test_query_order_prefers_native_exact_query(self):
        trader = _FakeTrader()
        seen = []

        def exact(account, order_id):
            seen.append(order_id)
            return trader.orders[order_id]

        trader.query_stock_order = exact
        bridge = XtQuantBrokerBridge(trader, _FakeAccount())
        oid = bridge.place_order(symbol="510300.SH", side=BUY, qty=100,
                                 limit_price=4.6)
        dto = bridge.query_order(oid)
        self.assertEqual(dto.order_id, oid)
        # The native exact-order query was used with the native INT id.
        self.assertEqual(seen, [int(oid)])


class TestAccountHealthVerification(unittest.TestCase):
    """NODEB-RR6-002: reconnect must verify id + type + status exactly."""

    def _bridge(self, *, security=1, status_ok=1, account_id="fake-account"):
        trader = _FakeTrader()
        bridge = XtQuantBrokerBridge(
            trader, _FakeAccount(), event_sink=_Sink(),
            security_account_type=security, account_status_ok=status_ok,
        )
        return trader, bridge

    def _status(self, account_id="fake-account", account_type=1, status=1):
        return type("S", (), {
            "account_id": account_id, "account_type": account_type, "status": status,
        })()

    def test_success_with_non_default_constants(self):
        # Correct id + type + status with NON-DEFAULT injected constants.
        trader, bridge = self._bridge(security=23, status_ok=7)
        trader.query_account_status = lambda: [self._status(account_type=23, status=7)]
        bridge._verify_bound_account_healthy()  # must not raise

    def test_wrong_account_type_fails(self):
        trader, bridge = self._bridge(security=23, status_ok=7)
        trader.query_account_status = lambda: [self._status(account_type=1, status=7)]
        with self.assertRaises(Exception):
            bridge._verify_bound_account_healthy()

    def test_abnormal_status_fails(self):
        trader, bridge = self._bridge(security=23, status_ok=7)
        trader.query_account_status = lambda: [self._status(account_type=23, status=2)]
        with self.assertRaises(Exception):
            bridge._verify_bound_account_healthy()

    def test_unbound_constants_fail_closed(self):
        # No unverified default: constants must come from the session.
        trader, bridge = self._bridge(security=None, status_ok=None)
        trader.query_account_status = lambda: [self._status()]
        with self.assertRaises(Exception):
            bridge._verify_bound_account_healthy()

    def test_missing_account_fails(self):
        trader, bridge = self._bridge(security=23, status_ok=7)
        trader.query_account_status = lambda: []
        with self.assertRaises(Exception):
            bridge._verify_bound_account_healthy()


class TestCallbackIsolation(unittest.TestCase):
    """NODEB-004 / I2-003: concrete handler only enqueues immutable events."""

    def test_order_callback_only_enqueues_immutable_event(self):
        sink = _Sink()
        handler = XtQuantCallbackHandler(sink)
        raw = _FakeOrder(
            order_id=1, order_type=STOCK_BUY, order_volume=100,
            price=4.6, order_status=56, traded_volume=100,
            order_remark="TG_510300SH_B001",
        )
        handler.on_stock_order(raw)
        self.assertEqual(len(sink.events), 1)
        event = sink.events[0]
        self.assertEqual(event.order_id, "1")
        self.assertEqual(event.status, OrderStatus.FILLED)
        self.assertEqual(event.filled_qty, 100)
        self.assertFalse(hasattr(event, "broker"))
        self.assertFalse(hasattr(event, "engine"))
        with self.assertRaises(Exception):
            event.order_id = "MUTATED"  # frozen dataclass

    def test_trade_callback_only_enqueues_immutable_event(self):
        sink = _Sink()
        handler = XtQuantCallbackHandler(sink)
        raw = _FakeTrade("T1", 1, 60, 4.6, "20260815093500")
        handler.on_stock_trade(raw)
        self.assertEqual(len(sink.events), 1)
        event = sink.events[0]
        self.assertEqual(event.trade_id, "T1")
        self.assertEqual(event.qty, 60)

    def test_critical_callbacks_are_not_dropped(self):
        sink = _Sink()
        handler = XtQuantCallbackHandler(sink)
        handler.on_account_status(type("S", (), {"status": 1})())
        handler.on_order_error(type("E", (), {"order_id": 7, "error_msg": "bad"})())
        handler.on_cancel_error(type("C", (), {"order_id": 8, "error_msg": "nope"})())
        kinds = [e.kind for e in sink.events]
        self.assertEqual(kinds, [
            "BROKER_ACCOUNT_STATUS",
            "BROKER_ORDER_ERROR",
            "BROKER_CANCEL_ERROR",
        ])
        self.assertIsInstance(sink.events[0], BrokerAccountStatusEvent)
        self.assertIsInstance(sink.events[1], BrokerOrderErrorEvent)
        self.assertIsInstance(sink.events[2], BrokerCancelErrorEvent)

    def test_disconnect_marks_unhealthy_immediately(self):
        # NODEB-RR-005: on_disconnected emits the event AND flips health false
        # right away; subsequent enqueues are blocked.
        sink = _Sink()
        handler = XtQuantCallbackHandler(sink)
        self.assertTrue(handler.healthy)
        handler.on_disconnected()
        self.assertEqual(len(sink.events), 1)
        self.assertIsInstance(sink.events[0], BrokerDisconnectEvent)
        self.assertFalse(handler.healthy)
        # A later callback cannot enqueue anything.
        handler.on_account_status(type("S", (), {"status": 1})())
        self.assertEqual(len(sink.events), 1)

    def test_handler_holds_no_engine_or_store_references(self):
        sink = _Sink()
        handler = XtQuantCallbackHandler(sink)
        self.assertFalse(hasattr(handler, "engine"))
        self.assertFalse(hasattr(handler, "store"))
        self.assertFalse(hasattr(handler, "adapter"))
        self.assertFalse(hasattr(handler, "broker"))

    def test_enqueue_failure_flips_unhealthy(self):
        class FailingSink:
            def enqueue(self, event):
                raise RuntimeError("queue full")

        handler = XtQuantCallbackHandler(FailingSink())
        handler.on_stock_order(_FakeOrder(
            order_id=1, order_type=STOCK_BUY, order_volume=100,
            price=4.6, order_status=50,
        ))
        self.assertFalse(handler.healthy)

    def test_bridge_registers_handler_on_trader(self):
        trader = _FakeTrader()
        sink = _Sink()
        bridge = XtQuantBrokerBridge(trader, _FakeAccount(), event_sink=sink)
        self.assertIsNotNone(bridge.callback_handler)
        self.assertIs(trader.callback, bridge.callback_handler)
        self.assertTrue(bridge.execution_healthy)

    def test_bridge_execution_healthy_flips_after_enqueue_failure(self):
        class FailingSink:
            def enqueue(self, event):
                raise RuntimeError("queue full")

        trader = _FakeTrader()
        bridge = XtQuantBrokerBridge(trader, _FakeAccount(), event_sink=FailingSink())
        trader.callback.on_stock_order(_FakeOrder(
            order_id=1, order_type=STOCK_BUY, order_volume=100,
            price=4.6, order_status=50,
        ))
        self.assertFalse(bridge.execution_healthy)

    def test_no_sink_means_no_handler(self):
        bridge = XtQuantBrokerBridge(_FakeTrader(), _FakeAccount())
        self.assertIsNone(bridge.callback_handler)


if __name__ == "__main__":
    unittest.main()
