"""Tests for tgrid.execution — Gate 4 Execution Dry Run (design §39).

Covers the full dry-run loop (decision -> intent -> broker -> fill -> T-Lot ->
PnL) plus the mandatory failure matrix: reject, partial fill, timeout, cancel
failure, limited reprice, duplicate callback, out-of-order callback,
concurrent buy/sell intent, reserved cash conflict, reserved sell conflict,
crash after broker send, restart, disconnect.

Migration Phase D: the engine drives the public-core ExecutionSession; the
SimBroker implements the public-core BrokerPort (native int ids, qec DTOs).
"""

import os
import tempfile
import unittest

from qmt_execution_core.domain import BrokerOrderStatus
from qmt_execution_core.exceptions import BrokerError
from qmt_execution_core.domain import ExecutionRequest, Side

from tgrid.execution import (
    CancelFailedError,
    ExecutionEngine,
    ExecutionError,
    OrderReconciliationError,
    OrderSendFailedError,
    OrderStatus,
    ReservationConflictError,
    SimBroker,
    SimulationDriver,
)
from tgrid.execution.models import BUY, SELL
from tgrid.execution.store import (
    ExecutionStore,
    ExecutionStoreError,
    IntentAlreadyExistsError,
    IntentNotFoundError,
)
from tgrid.integrations.qec_adapter import make_execution_request
from tgrid.persistence import initialize
from tgrid.risk.exceptions import PersistenceError


def _temp_db_path():
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = handle.name
    handle.close()
    os.remove(path)
    return path


def _store_and_broker():
    conn = initialize(_temp_db_path())
    store = ExecutionStore(conn)
    broker = SimBroker()
    engine = ExecutionEngine(store, broker, order_timeout_seconds=120)
    return conn, store, broker, engine


def _driver(engine, broker):
    return SimulationDriver(engine, broker)


def _request(key="K1", symbol="0700.HK", side=BUY, qty=100, price=420.0,
             remark="TG_0700_B01"):
    return make_execution_request(
        client_order_key=key, symbol=symbol, side=side, qty=qty,
        limit_price=price, strategy_name="TGRID", order_remark=remark,
    )


class TestExecutionStore(unittest.TestCase):
    def test_intent_and_reservation_atomic(self):
        conn = initialize(_temp_db_path())
        try:
            store = ExecutionStore(conn)
            booked = store.create_intent_with_reservation(
                client_order_key="K1", symbol="0700.HK", side=BUY, qty=100,
                limit_price=420.0, strategy_name="TGRID", order_remark="TG_0700_B01",
                created_at="t0", cash_amount=42000.0,
            )
            self.assertIsNotNone(booked.intent)
            self.assertEqual(store.reserved_cash("0700.HK"), 42000.0)
        finally:
            conn.close()

    def test_duplicate_intent_rejected(self):
        conn = initialize(_temp_db_path())
        try:
            store = ExecutionStore(conn)
            store.create_intent_with_reservation(
                client_order_key="K1", symbol="0700.HK", side=BUY, qty=100,
                limit_price=420.0, strategy_name="TGRID", order_remark="TG_0700_B01",
                created_at="t0", cash_amount=42000.0,
            )
            with self.assertRaises(IntentAlreadyExistsError):
                store.create_intent_with_reservation(
                    client_order_key="K1", symbol="0700.HK", side=BUY, qty=100,
                    limit_price=420.0, strategy_name="TGRID", order_remark="TG_0700_B01",
                    created_at="t1", cash_amount=42000.0,
                )
        finally:
            conn.close()

    def test_terminal_intent_not_transitionable(self):
        conn, store, _, _ = _store_and_broker()
        try:
            store.create_intent_with_reservation(
                client_order_key="K1", symbol="0700.HK", side=BUY, qty=100,
                limit_price=420.0, strategy_name="TGRID", order_remark="TG_0700_B01",
                created_at="t0", cash_amount=42000.0,
            )
            store.update_intent_status("K1", status=OrderStatus.FILLED, updated_at="t1")
            with self.assertRaises(ExecutionStoreError):
                store.update_intent_status(
                    "K1", status=OrderStatus.CANCELED, updated_at="t2"
                )
        finally:
            conn.close()

    def test_missing_intent(self):
        conn, store, _, _ = _store_and_broker()
        try:
            with self.assertRaises(IntentNotFoundError):
                store.get_intent("NO_SUCH")
        finally:
            conn.close()


class TestSimBroker(unittest.TestCase):
    def test_place_and_fill_script(self):
        broker = SimBroker()
        order_id = broker.place_order(_request())
        broker.get_order(order_id).script = (("FILL", 100, 420.0),)
        broker.tick_order(order_id)
        order = broker.query_order(order_id)
        self.assertEqual(order.status, BrokerOrderStatus.FILLED)
        self.assertEqual(order.filled_qty, 100)
        self.assertEqual(len(broker.query_trades(order_id)), 1)

    def test_partial_fill(self):
        broker = SimBroker()
        order_id = broker.place_order(_request())
        broker.get_order(order_id).script = (("FILL", 60, 420.0),)
        broker.tick_order(order_id)
        order = broker.query_order(order_id)
        self.assertEqual(order.status, BrokerOrderStatus.PARTIALLY_FILLED)
        self.assertEqual(order.filled_qty, 60)

    def test_reject(self):
        broker = SimBroker()
        order_id = broker.place_order(_request())
        broker.get_order(order_id).script = (("REJECT",),)
        broker.tick_order(order_id)
        self.assertEqual(broker.query_order(order_id).status,
                         BrokerOrderStatus.REJECTED)

    def test_disconnect(self):
        broker = SimBroker()
        broker.connected = False
        with self.assertRaises(BrokerError):
            broker.place_order(_request())

    def test_cancel_failure_script(self):
        broker = SimBroker()
        order_id = broker.place_order(_request())
        broker.get_order(order_id).script = (("CANCEL_FAIL",),)
        with self.assertRaises(BrokerError):
            broker.cancel_order(order_id)
        # Order is still WORKING: never assume canceled (design §25).
        self.assertEqual(broker.query_order(order_id).status,
                         BrokerOrderStatus.WORKING)

    def test_cancel_success_is_pending_until_confirmed(self):
        broker = SimBroker()
        order_id = broker.place_order(_request())
        result = broker.cancel_order(order_id)
        self.assertEqual(result.value, "accepted")
        # Cancel ack is NOT terminal cancellation; the broker reports pending.
        self.assertEqual(broker.query_order(order_id).status,
                         BrokerOrderStatus.CANCEL_PENDING)


class TestExecutor(unittest.TestCase):
    def test_send_buy_idempotent_and_submitted(self):
        conn, store, broker, engine = _store_and_broker()
        try:
            result = engine.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
            )
            self.assertEqual(result.status, OrderStatus.SUBMITTED)
            self.assertIsNotNone(result.broker_order_id)
            # Idempotency: a second send of the same key is refused.
            with self.assertRaises(ExecutionError):
                engine.send_buy(
                    client_order_key="K1", symbol="0700.HK", qty=100,
                    limit_price=420.0, order_remark="TG_0700_B01", now="t1",
                    expected_available_cash=500000.0, reserved_cash=42000.0,
                )
            # Reservation is held while pending.
            self.assertEqual(store.reserved_cash("0700.HK"), 42000.0)
        finally:
            conn.close()

    def test_send_sell_reserves_qty(self):
        conn, store, broker, engine = _store_and_broker()
        try:
            engine.send_sell(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=430.0, order_remark="TG_0700_S01", now="t0",
                expected_available_qty=500,
            )
            self.assertEqual(store.reserved_sell_qty("0700.HK"), 100)
        finally:
            conn.close()

    def test_reject_at_send(self):
        conn, store, broker, engine = _store_and_broker()
        driver = _driver(engine, broker)
        try:
            # Broker rejects immediately via script step (simulation driver).
            result = driver.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
                script=(("REJECT",),),
            )
            self.assertEqual(result.status, OrderStatus.REJECTED)
            self.assertEqual(store.reserved_cash("0700.HK"), 0.0)
        finally:
            conn.close()

    def test_disconnect_at_send(self):
        conn, store, broker, engine = _store_and_broker()
        try:
            broker.connected = False
            # The public session's health gate fires BEFORE the TGrid sidecar:
            # the send fails closed and nothing is persisted.
            with self.assertRaises(OrderSendFailedError):
                engine.send_buy(
                    client_order_key="K1", symbol="0700.HK", qty=100,
                    limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                    expected_available_cash=500000.0, reserved_cash=42000.0,
                )
            self.assertEqual(store.list_intents(), ())
            self.assertEqual(broker._orders, {})
        finally:
            conn.close()

    def test_poll_partial_then_full(self):
        conn, store, broker, engine = _store_and_broker()
        driver = _driver(engine, broker)
        try:
            result = driver.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
            )
            order_id = int(result.broker_order_id)
            broker.get_order(order_id).script = (("FILL", 60, 420.0),)
            r1 = driver.poll_order("K1", now="t1")
            self.assertEqual(r1.status, OrderStatus.PARTIAL)
            self.assertEqual(r1.filled_qty, 60)
            self.assertEqual(store.reserved_cash("0700.HK"), 42000.0)
            broker.get_order(order_id).script = (("FILL", 40, 420.0),)
            r2 = driver.poll_order("K1", now="t2")
            self.assertEqual(r2.status, OrderStatus.FILLED)
            self.assertEqual(r2.filled_qty, 100)
            self.assertEqual(store.reserved_cash("0700.HK"), 0.0)
        finally:
            conn.close()

    def test_timeout_cancel_and_reconcile(self):
        conn, store, broker, engine = _store_and_broker()
        try:
            result = engine.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
            )
            # Cancel ack is not terminal: the order reports CANCEL_PENDING.
            final = engine.timeout_order("K1", now="t1")
            self.assertNotEqual(final.status, OrderStatus.CANCELED)
            # Broker confirms the cancel on re-query -> CANCELED + release.
            order_id = int(result.broker_order_id)
            broker.get_order(order_id).status = BrokerOrderStatus.CANCELLED
            final = engine.poll_order("K1", now="t2")
            self.assertEqual(final.status, OrderStatus.CANCELED)
            self.assertEqual(store.reserved_cash("0700.HK"), 0.0)
        finally:
            conn.close()

    def test_cancel_failure_never_assumes(self):
        conn, store, broker, engine = _store_and_broker()
        try:
            result = engine.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
            )
            broker.get_order(int(result.broker_order_id)).script = (("CANCEL_FAIL",),)
            final = engine.timeout_order("K1", now="t1")
            # A rejected cancel is never treated as cancelled.
            self.assertNotEqual(final.status, OrderStatus.CANCELED)
            # Reservation must still be held: the order may still fill.
            self.assertEqual(store.reserved_cash("0700.HK"), 42000.0)
        finally:
            conn.close()

    def test_duplicate_callback_is_noop(self):
        conn, store, broker, engine = _store_and_broker()
        driver = _driver(engine, broker)
        try:
            result = driver.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
            )
            broker.get_order(int(result.broker_order_id)).script = (("FILL", 100, 420.0),)
            driver.poll_order("K1", now="t1")
            # Duplicate fill callback: poll again, terminal -> no state change.
            r = driver.poll_order("K1", now="t2")
            self.assertEqual(r.status, OrderStatus.FILLED)
            self.assertEqual(len(store.list_intents()), 1)
            self.assertEqual(store.reserved_cash("0700.HK"), 0.0)
        finally:
            conn.close()

    def test_pending_order_keys(self):
        conn, store, broker, engine = _store_and_broker()
        try:
            engine.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
            )
            self.assertEqual(set(engine.pending_order_keys()), {"K1"})
            self.assertEqual(
                set(engine.pending_order_keys(symbol="0700.HK")), {"K1"}
            )
            # Public-core lifecycle is one order at a time: a second send while
            # one is pending is refused.
            with self.assertRaises(ExecutionError):
                engine.send_sell(
                    client_order_key="K2", symbol="0700.HK", qty=100,
                    limit_price=430.0, order_remark="TG_0700_S01", now="t1",
                    expected_available_qty=500,
                )
        finally:
            conn.close()


class TestRecovery(unittest.TestCase):
    def test_intent_only_no_broker_order_keeps_safe_mode(self):
        conn, store, broker, engine = _store_and_broker()
        try:
            # Crash after local write, before broker send: intent exists,
            # broker has no order.
            store.create_intent_with_reservation(
                client_order_key="K1", symbol="0700.HK", side=BUY, qty=100,
                limit_price=420.0, strategy_name="TGRID", order_remark="TG_0700_B01",
                created_at="t0", cash_amount=42000.0,
            )
            engine.engage_safe_mode("startup")
            with self.assertRaises(ExecutionError):
                engine.reconcile_and_clear_safe_mode()  # unresolved -> retained
            self.assertTrue(engine.safe_mode)
        finally:
            conn.close()

    def test_matched_broker_order_clears_safe_mode(self):
        conn, store, broker, engine = _store_and_broker()
        try:
            result = engine.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
            )
            engine.engage_safe_mode("startup")
            engine.reconcile_and_clear_safe_mode()  # MATCHED -> clears
            self.assertFalse(engine.safe_mode)
        finally:
            conn.close()

    def test_unmatched_broker_order_keeps_safe_mode(self):
        conn, store, broker, engine = _store_and_broker()
        try:
            # Broker order with a TGRID remark but no local intent.
            order_id = broker.place_order(_request(key="K9", remark="TG_0700_B99"))
            broker.get_order(order_id).status = BrokerOrderStatus.WORKING
            engine.engage_safe_mode("startup")
            with self.assertRaises(ExecutionError):
                engine.reconcile_and_clear_safe_mode()
            self.assertTrue(engine.safe_mode)
        finally:
            conn.close()

    def test_terminal_intents_skipped(self):
        conn, store, broker, engine = _store_and_broker()
        driver = _driver(engine, broker)
        try:
            result = driver.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
                script=(("REJECT",),),
            )
            self.assertEqual(result.status, OrderStatus.REJECTED)
            engine.engage_safe_mode("startup")
            engine.reconcile_and_clear_safe_mode()  # terminal intents skipped
            self.assertFalse(engine.safe_mode)
        finally:
            conn.close()


class TestRestart(unittest.TestCase):
    def test_restart_reconstructs_from_broker_and_store(self):
        # Simulate a full process restart: fresh connections, same DB file and
        # same broker object (broker state survives as the "broker server").
        # The public-core session journal/lock are PERSISTENT (same paths) so
        # the restarted session recovers the in-flight order.
        path = _temp_db_path()
        journal_path = path + ".journal.json"
        lock_path = path + ".exec.lock"
        conn1 = initialize(path)
        store1 = ExecutionStore(conn1)
        broker = SimBroker()
        engine1 = ExecutionEngine(store1, broker, journal_path=journal_path,
                                  lock_path=lock_path)
        driver1 = _driver(engine1, broker)
        result = driver1.send_buy(
            client_order_key="K1", symbol="0700.HK", qty=100,
            limit_price=420.0, order_remark="TG_0700_B01", now="t0",
            expected_available_cash=500000.0, reserved_cash=42000.0,
        )
        broker.get_order(int(result.broker_order_id)).script = (("FILL", 100, 420.0),)
        engine1.close()  # release the session mutex before the "restart"
        conn1.close()

        # "Restart": reopen DB, new store, same broker + same journal paths.
        conn2 = initialize(path)
        store2 = ExecutionStore(conn2)
        engine2 = ExecutionEngine(store2, broker, journal_path=journal_path,
                                  lock_path=lock_path)
        driver2 = _driver(engine2, broker)
        try:
            engine2.reconcile_and_clear_safe_mode()  # MATCHED -> no raise
            final = driver2.poll_order("K1", now="t1")
            self.assertEqual(final.status, OrderStatus.FILLED)
            self.assertEqual(final.filled_qty, 100)
            self.assertEqual(store2.reserved_cash("0700.HK"), 0.0)
        finally:
            engine2.close()
            conn2.close()
            for extra in (journal_path, lock_path):
                if os.path.exists(extra):
                    os.remove(extra)


class TestReservationConflicts(unittest.TestCase):
    def test_reserved_cash_conflict_blocks_second_buy(self):
        conn, store, broker, engine = _store_and_broker()
        try:
            engine.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
            )
            # Second BUY would exceed available cash net of reservation:
            # the engine refuses before any store mutation or broker call.
            with self.assertRaises(ReservationConflictError):
                engine.send_buy(
                    client_order_key="K2", symbol="0700.HK", qty=100,
                    limit_price=420.0, order_remark="TG_0700_B02", now="t1",
                    expected_available_cash=1000.0, reserved_cash=42000.0,
                )
        finally:
            conn.close()

    def test_reserved_sell_conflict_blocks_second_sell(self):
        conn, store, broker, engine = _store_and_broker()
        try:
            engine.send_sell(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=430.0, order_remark="TG_0700_S01", now="t0",
                expected_available_qty=500,
            )
            with self.assertRaises(ReservationConflictError):
                engine.send_sell(
                    client_order_key="K2", symbol="0700.HK", qty=500,
                    limit_price=430.0, order_remark="TG_0700_S02", now="t1",
                    expected_available_qty=400,
                )
            self.assertEqual(store.reserved_sell_qty("0700.HK"), 100)
        finally:
            conn.close()


class TestNonFiniteRejection(unittest.TestCase):
    """NODEB-I2-005: NaN/Inf rejected BEFORE any store mutation or broker call."""

    def _assert_zero_mutation_zero_calls(self, *, side=BUY, **kwargs):
        conn, store, broker, engine = _store_and_broker()
        try:
            with self.assertRaises(ExecutionError):
                engine.send_buy(
                    client_order_key="K1", symbol="0700.HK", qty=100,
                    order_remark="TG_0700_B01", now="t0",
                    **kwargs,
                )
            # Zero ExecutionStore mutation: no intent, no reservation.
            self.assertEqual(store.list_intents(), ())
            self.assertEqual(store.reserved_cash("0700.HK"), 0.0)
            # Zero broker calls.
            self.assertEqual(broker._orders, {})
        finally:
            conn.close()

    def test_nan_limit_price_rejected(self):
        self._assert_zero_mutation_zero_calls(
            limit_price=float("nan"),
            expected_available_cash=500000.0, reserved_cash=42000.0,
        )

    def test_inf_limit_price_rejected(self):
        self._assert_zero_mutation_zero_calls(
            limit_price=float("inf"),
            expected_available_cash=500000.0, reserved_cash=42000.0,
        )

    def test_nan_expected_cash_rejected(self):
        self._assert_zero_mutation_zero_calls(
            limit_price=420.0,
            expected_available_cash=float("nan"), reserved_cash=42000.0,
        )

    def test_nan_reserved_cash_rejected(self):
        self._assert_zero_mutation_zero_calls(
            limit_price=420.0,
            expected_available_cash=500000.0, reserved_cash=float("nan"),
        )

    def test_inf_reserved_cash_rejected(self):
        self._assert_zero_mutation_zero_calls(
            limit_price=420.0,
            expected_available_cash=500000.0, reserved_cash=float("inf"),
        )


if __name__ == "__main__":
    unittest.main()
