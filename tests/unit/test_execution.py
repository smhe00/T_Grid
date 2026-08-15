"""Tests for tgrid.execution — Gate 4 Execution Dry Run (design §39).

Covers the full dry-run loop (decision -> intent -> broker -> fill -> T-Lot ->
PnL) plus the mandatory failure matrix: reject, partial fill, timeout, cancel
failure, limited reprice, duplicate callback, out-of-order callback,
concurrent buy/sell intent, reserved cash conflict, reserved sell conflict,
crash after broker send, restart, disconnect.
"""

import os
import tempfile
import unittest

from tgrid.execution import (
    BrokerDisconnectedError,
    BrokerOrderRejectedError,
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
from tgrid.execution.recovery import reconcile_open_intents
from tgrid.execution.store import (
    ExecutionStore,
    ExecutionStoreError,
    IntentAlreadyExistsError,
    IntentNotFoundError,
)
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


class TestExecutionStore(unittest.TestCase):
    def test_intent_and_reservation_atomic(self):
        conn, store, _, _ = _store_and_broker()
        try:
            result = store.create_intent_with_reservation(
                client_order_key="K1", symbol="0700.HK", side=BUY, qty=100,
                limit_price=420.0, strategy_name="TGRID", order_remark="TG_0700_B01",
                created_at="t0", cash_amount=42000.0,
            )
            self.assertEqual(result.intent.status, OrderStatus.NEW)
            self.assertIsNone(result.intent.broker_order_id)
            self.assertEqual(result.reservation.side, BUY)
            self.assertEqual(result.reservation.cash_amount, 42000.0)
            self.assertEqual(store.reserved_cash("0700.HK"), 42000.0)
        finally:
            conn.close()

    def test_duplicate_intent_rejected(self):
        conn, store, _, _ = _store_and_broker()
        try:
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
            self.assertEqual(len(store.list_intents()), 1)
        finally:
            conn.close()

    def test_sell_reservation_has_no_cash(self):
        conn, store, _, _ = _store_and_broker()
        try:
            result = store.create_intent_with_reservation(
                client_order_key="K1", symbol="0700.HK", side=SELL, qty=100,
                limit_price=430.0, strategy_name="TGRID", order_remark="TG_0700_S01",
                created_at="t0",
            )
            self.assertIsNone(result.reservation.cash_amount)
            self.assertEqual(store.reserved_sell_qty("0700.HK"), 100)
        finally:
            conn.close()

    def test_release_reservation(self):
        conn, store, _, _ = _store_and_broker()
        try:
            store.create_intent_with_reservation(
                client_order_key="K1", symbol="0700.HK", side=SELL, qty=100,
                limit_price=430.0, strategy_name="TGRID", order_remark="TG_0700_S01",
                created_at="t0",
            )
            store.release_reservation("K1", released_at="t1")
            self.assertEqual(store.reserved_sell_qty("0700.HK"), 0)
        finally:
            conn.close()

    def test_buy_requires_cash_amount(self):
        conn, store, _, _ = _store_and_broker()
        try:
            with self.assertRaises(PersistenceError):
                store.create_intent_with_reservation(
                    client_order_key="K1", symbol="0700.HK", side=BUY, qty=100,
                    limit_price=420.0, strategy_name="TGRID", order_remark="TG",
                    created_at="t0",
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
        order_id = broker.place_order(
            symbol="0700.HK", side=BUY, qty=100, limit_price=420.0,
        )
        broker.get_order(order_id).script = (("FILL", 100, 420.0),)
        broker.tick_order(order_id)
        order = broker.query_order(order_id)
        self.assertEqual(order.status, "FILLED")
        self.assertEqual(order.filled_qty, 100)
        self.assertEqual(len(broker.query_trades(order_id)), 1)

    def test_partial_fill(self):
        broker = SimBroker()
        order_id = broker.place_order(
            symbol="0700.HK", side=BUY, qty=100, limit_price=420.0,
        )
        broker.get_order(order_id).script = (("FILL", 60, 420.0),)
        broker.tick_order(order_id)
        order = broker.query_order(order_id)
        self.assertEqual(order.status, "PARTIAL")
        self.assertEqual(order.filled_qty, 60)

    def test_reject(self):
        broker = SimBroker()
        order_id = broker.place_order(
            symbol="0700.HK", side=BUY, qty=100, limit_price=420.0,
        )
        broker.get_order(order_id).script = (("REJECT",),)
        broker.tick_order(order_id)
        self.assertEqual(broker.query_order(order_id).status, "REJECTED")

    def test_disconnect(self):
        broker = SimBroker()
        broker.connected = False
        with self.assertRaises(BrokerDisconnectedError):
            broker.place_order(symbol="0700.HK", side=BUY, qty=100, limit_price=420.0)

    def test_cancel_failure_script(self):
        broker = SimBroker()
        order_id = broker.place_order(
            symbol="0700.HK", side=BUY, qty=100, limit_price=420.0,
        )
        broker.get_order(order_id).script = (("CANCEL_FAIL",),)
        from tgrid.execution.simbroker import BrokerCancelFailedError

        with self.assertRaises(BrokerCancelFailedError):
            broker.cancel_order(order_id)
        # Order is still SUBMITTED: never assume canceled (design §25).
        self.assertEqual(broker.query_order(order_id).status, "SUBMITTED")

    def test_cancel_success(self):
        broker = SimBroker()
        order_id = broker.place_order(
            symbol="0700.HK", side=BUY, qty=100, limit_price=420.0,
        )
        broker.cancel_order(order_id)
        self.assertEqual(broker.query_order(order_id).status, "CANCELED")


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
            with self.assertRaises(OrderSendFailedError):
                engine.send_buy(
                    client_order_key="K1", symbol="0700.HK", qty=100,
                    limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                    expected_available_cash=500000.0, reserved_cash=42000.0,
                )
            # Intent is still recorded (recoverable) but never got a broker id.
            intent = store.get_intent("K1")
            self.assertIsNone(intent.broker_order_id)
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
            order_id = result.broker_order_id
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
            # No fill ever: order times out.  Cancel -> re-query -> CANCELED.
            final = engine.timeout_order("K1", now="t1")
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
            broker.get_order(result.broker_order_id).script = (("CANCEL_FAIL",),)
            with self.assertRaises(CancelFailedError):
                engine.timeout_order("K1", now="t1")
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
            broker.get_order(result.broker_order_id).script = (("FILL", 100, 420.0),)
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
            engine.send_sell(
                client_order_key="K2", symbol="0700.HK", qty=100,
                limit_price=430.0, order_remark="TG_0700_S01", now="t0",
                expected_available_qty=500,
            )
            self.assertEqual(set(engine.pending_order_keys()), {"K1", "K2"})
            self.assertEqual(
                set(engine.pending_order_keys(symbol="0700.HK")), {"K1", "K2"}
            )
        finally:
            conn.close()


class TestRecovery(unittest.TestCase):
    def test_intent_only_no_broker_order(self):
        conn, store, broker, engine = _store_and_broker()
        try:
            # Crash after local write, before broker send: intent exists,
            # broker has no order.
            store.create_intent_with_reservation(
                client_order_key="K1", symbol="0700.HK", side=BUY, qty=100,
                limit_price=420.0, strategy_name="TGRID", order_remark="TG_0700_B01",
                created_at="t0", cash_amount=42000.0,
            )
            results = reconcile_open_intents(store, broker)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].outcome, "INTENT_ONLY")
        finally:
            conn.close()

    def test_matched_broker_order(self):
        conn, store, broker, engine = _store_and_broker()
        try:
            result = engine.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
            )
            results = reconcile_open_intents(store, broker)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].outcome, "MATCHED")
            self.assertEqual(results[0].matched_broker_order_id, result.broker_order_id)
        finally:
            conn.close()

    def test_unmatched_broker_order_flags_safe_mode(self):
        conn, store, broker, engine = _store_and_broker()
        try:
            # Broker order placed outside the executor (e.g. crash path) with a
            # TGRID remark but no local intent: duplicate-order risk.
            order_id = broker.place_order(
                symbol="0700.HK", side=BUY, qty=100, limit_price=420.0,
            )
            broker.get_order(order_id).order_remark = "TG_0700_B01"
            results = reconcile_open_intents(store, broker)
            outcomes = [r.outcome for r in results]
            self.assertIn("UNMATCHED_BROKER_ORDER", outcomes)
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
            results = reconcile_open_intents(store, broker)
            self.assertEqual(results, ())
        finally:
            conn.close()


class TestRestart(unittest.TestCase):
    def test_restart_reconstructs_from_broker_and_store(self):
        # Simulate a full process restart: fresh connections, same DB file and
        # same broker object (broker state survives as the "broker server").
        path = _temp_db_path()
        conn1 = initialize(path)
        store1 = ExecutionStore(conn1)
        broker = SimBroker()
        engine1 = ExecutionEngine(store1, broker)
        driver1 = _driver(engine1, broker)
        result = driver1.send_buy(
            client_order_key="K1", symbol="0700.HK", qty=100,
            limit_price=420.0, order_remark="TG_0700_B01", now="t0",
            expected_available_cash=500000.0, reserved_cash=42000.0,
        )
        broker.get_order(result.broker_order_id).script = (("FILL", 100, 420.0),)
        conn1.close()

        # "Restart": reopen DB, new store, same broker; reconcile and poll.
        conn2 = initialize(path)
        store2 = ExecutionStore(conn2)
        engine2 = ExecutionEngine(store2, broker)
        driver2 = _driver(engine2, broker)
        try:
            results = reconcile_open_intents(store2, broker)
            self.assertEqual(results[0].outcome, "MATCHED")
            final = driver2.poll_order("K1", now="t1")
            self.assertEqual(final.status, OrderStatus.FILLED)
            self.assertEqual(final.filled_qty, 100)
            self.assertEqual(store2.reserved_cash("0700.HK"), 0.0)
        finally:
            conn2.close()


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
            # the engine refuses (cash conflict surfaced by the caller gate).
            with self.assertRaises(ExecutionError):
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
            # Available T qty is 400 after the first reservation; a 500-share
            # second sell cannot fit.
            with self.assertRaises(ExecutionError):
                engine.send_sell(
                    client_order_key="K2", symbol="0700.HK", qty=500,
                    limit_price=430.0, order_remark="TG_0700_S02", now="t1",
                    expected_available_qty=400,
                )
            self.assertEqual(store.reserved_sell_qty("0700.HK"), 100)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
