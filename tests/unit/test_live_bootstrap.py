"""NODEB-I2-003 / I2-004 / I2-006: EventQueue wiring, exposure crash-safety, bootstrap.

* real TGrid EventQueue integration: concrete fake XtQuant callbacks produce
  immutable events processed on the single worker thread (I2-003);
* queue full/stopped health flips block new orders (I2-003);
* durable exposure: startup-without-reconstruct refuses orders, terminal
  same-day orders are reconstructed, crash-window reservation is pre-send,
  bogus/future roll-day input is rejected (I2-004);
* one production-shaped bootstrap factory: cannot place an order before
  startup reconciliation + runtime confirmation complete (I2-006).
"""

import os
import tempfile
import unittest

from tgrid.events import EventQueue
from tgrid.execution.executor import ExecutionEngine, OrderStatus
from tgrid.execution.store import ExecutionStore
from tgrid.integrations.live_bootstrap import build_live_stack
from tgrid.integrations.live_broker_adapter import (
    ExposureNotReadyError,
    LiveBrokerAdapter,
    LiveBrokerError,
    LiveBrokerPolicy,
)
from tgrid.integrations.xtquant_bridge import (
    STOCK_BUY,
    BrokerOrderEvent,
    XtQuantBrokerBridge,
)
from tgrid.persistence import initialize


def _temp_db_path():
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = handle.name
    handle.close()
    os.remove(path)
    return path


class _FakeAccount:
    account_id = "fake-account"
    account_type = "STOCK"


class _FakeOrder:
    def __init__(self, order_id, order_type, order_volume, price, order_status,
                 traded_volume=0, order_remark=None, order_time=""):
        self.order_id = order_id
        self.stock_code = "510300.SH"
        self.order_type = order_type
        self.order_volume = order_volume
        self.price = price
        self.order_status = order_status
        self.traded_volume = traded_volume
        self.order_remark = order_remark
        self.order_time = order_time
        self.strategy_name = "TGRID"


class _FakeTrade:
    def __init__(self, traded_id, order_id, traded_volume, traded_price, traded_time):
        self.traded_id = traded_id
        self.order_id = order_id
        self.stock_code = "510300.SH"
        self.traded_volume = traded_volume
        self.traded_price = traded_price
        self.traded_time = traded_time


class _DictStore:
    def __init__(self):
        self._data = {}

    def get(self, trade_date):
        return self._data.get(trade_date)

    def set(self, trade_date, notional):
        self._data[trade_date] = notional


class _FakeXtQuantTrader:
    def __init__(self):
        self.orders = {}
        self.trades = []
        self._seq = 0
        self.callback = None

    def register_callback(self, callback):
        self.callback = callback

    def order_stock(self, account, stock_code, order_type, order_volume,
                    price_type, price, strategy_name="", order_remark=""):
        self._seq += 1
        order_id = 9000 + self._seq
        self.orders[order_id] = _FakeOrder(
            order_id=order_id, order_type=order_type, order_volume=order_volume,
            price=price, order_status=50, order_remark=order_remark or None,
            order_time="2026-08-15 09:35:00",
        )
        return order_id

    def cancel_order_stock(self, account, order_id):
        if order_id not in self.orders:
            return -1
        self.orders[order_id].order_status = 54
        return 0

    def query_stock_orders(self, account):
        return list(self.orders.values())

    def query_stock_trades(self, account):
        return self.trades


def _policy(**overrides):
    cfg = dict(
        allowlist=frozenset({"510300.SH"}),
        max_order_qty=1000,
        max_cash_per_order=100000.0,
        max_cash_per_day=500000.0,
    )
    cfg.update(overrides)
    return LiveBrokerPolicy(**cfg)


class TestEventQueueIntegration(unittest.TestCase):
    """I2-003: real EventQueue consumes immutable broker events on one thread."""

    def test_events_processed_on_single_worker_thread(self):
        collected = []
        queue = EventQueue(collected.append, maxsize=100, thread_name="tgrid-event-loop")
        queue.start()
        try:
            trader = _FakeXtQuantTrader()
            bridge = XtQuantBrokerBridge(trader, _FakeAccount(), event_sink=queue)
            # Feed concrete fake XtQuant callbacks through the registered handler.
            trader.callback.on_stock_order(_FakeOrder(
                order_id=1, order_type=STOCK_BUY, order_volume=100,
                price=4.6, order_status=56, traded_volume=100,
                order_remark="TG_510300SH_B001",
            ))
            trader.callback.on_stock_trade(_FakeTrade("T1", 1, 100, 4.6, "t1"))
            trader.callback.on_disconnected()
            # Stop + drain so the worker thread terminates deterministically.
            queue.stop()
            self.assertTrue(queue.join(timeout=2.0))
            self.assertEqual(len(collected), 3)
            kinds = {e.kind for e in collected}
            self.assertIn("BROKER_ORDER", kinds)
            self.assertIn("BROKER_TRADE", kinds)
            self.assertIn("BROKER_DISCONNECT", kinds)
            order_event = next(e for e in collected if e.kind == "BROKER_ORDER")
            self.assertIsInstance(order_event, BrokerOrderEvent)
            self.assertEqual(order_event.status, "FILLED")
            # Immutable: cannot mutate after delivery.
            with self.assertRaises(Exception):
                order_event.order_id = "MUTATED"
        finally:
            queue.stop()
            queue.join(timeout=1.0)

    def test_callback_objects_hold_no_engine_or_store_references(self):
        queue = EventQueue(lambda e: None, maxsize=100)
        queue.start()
        try:
            trader = _FakeXtQuantTrader()
            bridge = XtQuantBrokerBridge(trader, _FakeAccount(), event_sink=queue)
            handler = bridge.callback_handler
            self.assertFalse(hasattr(handler, "engine"))
            self.assertFalse(hasattr(handler, "store"))
            self.assertFalse(hasattr(handler, "adapter"))
            self.assertFalse(hasattr(handler, "broker"))
        finally:
            queue.stop()
            queue.join(timeout=1.0)


class TestQueueHealthBlocksOrders(unittest.TestCase):
    """I2-003: queue failure must refuse new orders via the adapter."""

    def test_queue_failed_flips_unhealthy_and_adapter_refuses(self):
        # A handler that raises puts the EventQueue into FAILED; every later
        # enqueue raises, the callback handler flips unhealthy, and the adapter
        # refuses new orders (I2-003).
        import time

        def boom(event):
            raise RuntimeError("worker failure")

        trader = _FakeXtQuantTrader()
        queue = EventQueue(boom, maxsize=100)
        queue.start()
        try:
            bridge = XtQuantBrokerBridge(trader, _FakeAccount(), event_sink=queue)
            # Feed one event to trigger the worker failure, then wait for the
            # queue to reach FAILED (deterministic sequencing).
            trader.callback.on_stock_order(_FakeOrder(
                order_id=1, order_type=STOCK_BUY, order_volume=100,
                price=4.6, order_status=50,
            ))
            deadline = time.monotonic() + 2.0
            while queue.state.value != "FAILED" and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(queue.state.value, "FAILED")
            # A subsequent callback enqueue fails -> handler unhealthy.
            trader.callback.on_stock_order(_FakeOrder(
                order_id=2, order_type=STOCK_BUY, order_volume=100,
                price=4.6, order_status=50,
            ))
            self.assertFalse(bridge.execution_healthy)
            adapter = LiveBrokerAdapter(
                broker=bridge, policy=_policy(),
                trade_date="2026-08-15", exposure_store=_DictStore(),
                runtime_confirmation_token="startup-token",
            )
            adapter.apply_config_enable(True)
            adapter.reconstruct_daily_exposure()
            adapter.confirm_runtime("startup-token")
            with self.assertRaises(LiveBrokerError):
                adapter.place_order(symbol="510300.SH", side="BUY",
                                    qty=100, limit_price=4.6)
        finally:
            queue.stop()
            queue.join(timeout=1.0)

    def test_queue_stopped_refuses_new_orders(self):
        trader = _FakeXtQuantTrader()
        queue = EventQueue(lambda e: None, maxsize=100)
        queue.start()
        queue.stop()  # stopped: enqueue raises -> handler unhealthy
        try:
            bridge = XtQuantBrokerBridge(trader, _FakeAccount(), event_sink=queue)
            trader.callback.on_stock_order(_FakeOrder(
                order_id=1, order_type=STOCK_BUY, order_volume=100,
                price=4.6, order_status=50,
            ))
            self.assertFalse(bridge.execution_healthy)
        finally:
            queue.join(timeout=1.0)


class TestExposureCrashSafety(unittest.TestCase):
    """I2-004: durable exposure gates and crash windows."""

    def test_startup_without_reconstruct_refuses_orders(self):
        broker = XtQuantBrokerBridge(_FakeXtQuantTrader(), _FakeAccount())
        adapter = LiveBrokerAdapter(
            broker=broker, policy=_policy(),
            trade_date="2026-08-15", exposure_store=_DictStore(),
            runtime_confirmation_token="startup-token",
        )
        adapter.apply_config_enable(True)
        adapter.confirm_runtime("startup-token")
        with self.assertRaises(ExposureNotReadyError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                limit_price=4.6)

    def test_reconstruction_includes_terminal_same_day_orders(self):
        trader = _FakeXtQuantTrader()
        order_id = trader.order_stock(
            _FakeAccount(), "510300.SH", STOCK_BUY, 100, 11, 4.6,
            "TGRID", "TG_510300SH_B001",
        )
        trader.orders[order_id].order_status = 56  # FILLED same day
        trader.orders[order_id].traded_volume = 100
        bridge = XtQuantBrokerBridge(trader, _FakeAccount())
        store = _DictStore()
        adapter = LiveBrokerAdapter(
            broker=bridge, policy=_policy(max_cash_per_day=500.0),
            trade_date="2026-08-15", exposure_store=store,
            runtime_confirmation_token="startup-token",
        )
        adapter.reconstruct_daily_exposure()
        # Terminal same-day BUY still consumed the cap (submitted notional rule).
        self.assertAlmostEqual(adapter.daily_cash_used, 460.0)
        adapter.apply_config_enable(True)
        adapter.confirm_runtime("startup-token")
        with self.assertRaises(LiveBrokerError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                limit_price=4.6)

    def test_crash_window_reservation_is_pre_send(self):
        trader = _FakeXtQuantTrader()
        bridge = XtQuantBrokerBridge(trader, _FakeAccount())
        adapter = LiveBrokerAdapter(
            broker=bridge, policy=_policy(max_cash_per_day=500.0),
            trade_date="2026-08-15", exposure_store=_DictStore(),
            runtime_confirmation_token="startup-token",
        )
        adapter.apply_config_enable(True)
        adapter.reconstruct_daily_exposure()
        adapter.confirm_runtime("startup-token")
        # After a BUY, the durable ledger already holds the notional.
        adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                            limit_price=4.6)
        self.assertAlmostEqual(adapter.daily_cash_used, 460.0)
        # A "crash" (new adapter, same store, same broker) reconstructs >= the
        # pre-send reservation, so the cap is never silently reopened.
        restarted = LiveBrokerAdapter(
            broker=bridge, policy=_policy(max_cash_per_day=500.0),
            trade_date="2026-08-15", exposure_store=adapter.exposure_store,
            runtime_confirmation_token="startup-token",
        )
        restarted.apply_config_enable(True)
        restarted.confirm_runtime("startup-token")
        restarted.reconstruct_daily_exposure()
        self.assertAlmostEqual(restarted.daily_cash_used, 460.0)

    def test_bogus_and_future_roll_input_rejected(self):
        broker = XtQuantBrokerBridge(_FakeXtQuantTrader(), _FakeAccount())
        adapter = LiveBrokerAdapter(
            broker=broker, policy=_policy(),
            trade_date="2026-08-15", exposure_store=_DictStore(),
            runtime_confirmation_token="startup-token",
        )
        adapter.apply_config_enable(True)
        adapter.reconstruct_daily_exposure()
        adapter.confirm_runtime("startup-token")
        with self.assertRaises(LiveBrokerError):
            adapter.roll_day("2026-13-99")  # not an ISO date
        with self.assertRaises(LiveBrokerError):
            adapter.roll_day("tomorrow")  # not a date at all
        # Trusted-session binding: roll must match the session date.
        with self.assertRaises(LiveBrokerError):
            adapter.roll_day("2026-08-17", session_date="2026-08-16")
        adapter.roll_day("2026-08-16", session_date="2026-08-16")


class TestBootstrap(unittest.TestCase):
    """I2-006: one production-shaped factory; no order before activate."""

    def test_stack_cannot_order_before_activate(self):
        trader = _FakeXtQuantTrader()
        conn = initialize(_temp_db_path())
        queue = EventQueue(lambda e: None, maxsize=100)
        try:
            store = ExecutionStore(conn)
            stack = build_live_stack(
                trader=trader, account=_FakeAccount(), store=store,
                policy=_policy(), exposure_store=_DictStore(),
                event_queue=queue, trade_date="2026-08-15",
                runtime_confirmation_token="startup-token",
            )
            self.assertIsInstance(stack.engine, ExecutionEngine)
            # Before activate: config not enabled -> no new order.
            with self.assertRaises(Exception):
                stack.engine.send_buy(
                    client_order_key="K1", symbol="510300.SH", qty=100,
                    limit_price=4.6, order_remark="TG_510300SH_B001",
                    now="t0", expected_available_cash=100000.0,
                    reserved_cash=460.0,
                )
        finally:
            queue.stop()
            queue.join(timeout=1.0)
            conn.close()

    def test_activate_enables_after_reconciliation_and_confirm(self):
        trader = _FakeXtQuantTrader()
        conn = initialize(_temp_db_path())
        queue = EventQueue(lambda e: None, maxsize=100)
        try:
            store = ExecutionStore(conn)
            stack = build_live_stack(
                trader=trader, account=_FakeAccount(), store=store,
                policy=_policy(), exposure_store=_DictStore(),
                event_queue=queue, trade_date="2026-08-15",
                runtime_confirmation_token="startup-token",
                config_live_enabled=True,
            )
            stack.activate(token="startup-token")
            result = stack.engine.send_buy(
                client_order_key="K1", symbol="510300.SH", qty=100,
                limit_price=4.6, order_remark="TG_510300SH_B001",
                now="t0", expected_available_cash=100000.0,
                reserved_cash=460.0,
            )
            self.assertEqual(result.status, OrderStatus.SUBMITTED)
        finally:
            queue.stop()
            queue.join(timeout=1.0)
            conn.close()

    def test_activate_fails_closed_on_ambiguous_recovery(self):
        trader = _FakeXtQuantTrader()
        conn = initialize(_temp_db_path())
        queue = EventQueue(lambda e: None, maxsize=100)
        try:
            store = ExecutionStore(conn)
            # Broker holds a tagged order with no local intent -> ambiguous.
            trader.order_stock(
                _FakeAccount(), "510300.SH", STOCK_BUY, 100, 11, 4.6,
                "TGRID", "TG_510300SH_B001",
            )
            stack = build_live_stack(
                trader=trader, account=_FakeAccount(), store=store,
                policy=_policy(), exposure_store=_DictStore(),
                event_queue=queue, trade_date="2026-08-15",
                runtime_confirmation_token="startup-token",
            )
            from tgrid.execution.recovery import reconcile_open_intents

            with self.assertRaises(Exception):
                stack.activate(token="startup-token",
                               reconcile_open_intents=reconcile_open_intents)
        finally:
            queue.stop()
            queue.join(timeout=1.0)
            conn.close()


if __name__ == "__main__":
    unittest.main()
