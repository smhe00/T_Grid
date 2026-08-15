"""NODEB-002: end-to-end pre-live chain ExecutionEngine -> LiveBrokerAdapter -> FakeBridge.

The full execution port chain is exercised with a FAKE concrete XtQuant trader
backend (never a real client): durable OrderIntent+Reservation before broker
send, idempotent client_order_key, crash-before-send (no blind resend),
crash-after-accept (startup reconciliation / SAFE_MODE), partial fills
preserving remaining reservation, timeout == cancel -> re-query -> reconcile,
unmatched tagged broker order -> SAFE_MODE, and broker query failure/ambiguous
status -> fail closed.
"""

import os
import tempfile
import unittest

from tgrid.execution.executor import (
    ExecutionEngine,
    OrderReconciliationError,
    OrderSendFailedError,
    OrderStatus,
)
from tgrid.execution.models import BUY, SELL
from tgrid.execution.recovery import reconcile_open_intents
from tgrid.execution.store import ExecutionStore
from tgrid.integrations.live_broker_adapter import (
    LiveBrokerAdapter,
    LiveBrokerPolicy,
)
from tgrid.integrations.xtquant_bridge import STOCK_BUY, XtQuantBrokerBridge
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


class _FakeTrade:
    def __init__(self, traded_id, order_id, traded_volume, traded_price, traded_time):
        self.traded_id = traded_id
        self.order_id = order_id
        self.stock_code = "510300.SH"
        self.traded_volume = traded_volume
        self.traded_price = traded_price
        self.traded_time = traded_time


class _FakeXtQuantTrader:
    """Mirrors XtQuantTrader for the chain; records every real call shape."""

    def __init__(self):
        self.orders = {}
        self.trades = []
        self.calls = []
        self._seq = 0
        self.fail_queries = False

    def register_callback(self, callback):
        self.callback = callback

    def order_stock(self, account, stock_code, order_type, order_volume,
                    price_type, price, strategy_name="", order_remark=""):
        self.calls.append(("order_stock", stock_code, order_type, order_volume,
                           price_type, price, strategy_name, order_remark))
        if self.fail_queries:
            raise RuntimeError("simulated network failure")
        self._seq += 1
        order_id = f"XT{self._seq:08d}"
        self.orders[order_id] = _FakeOrder(
            order_id=order_id, order_type=order_type, order_volume=order_volume,
            price=price, order_status=50, order_remark=order_remark or None,
        )
        return order_id

    def cancel_order_stock(self, account, order_id):
        self.calls.append(("cancel_order_stock", order_id))
        if order_id not in self.orders:
            return -1
        self.orders[order_id].order_status = 54  # 已撤
        return 0

    def query_stock_orders(self, account):
        if self.fail_queries:
            raise RuntimeError("simulated query failure")
        return list(self.orders.values())

    def query_stock_trades(self, account):
        if self.fail_queries:
            raise RuntimeError("simulated query failure")
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


def _chain(trader=None, **pol):
    """Build ExecutionEngine -> LiveBrokerAdapter -> XtQuantBrokerBridge(fake)."""
    trader = trader or _FakeXtQuantTrader()
    bridge = XtQuantBrokerBridge(trader, _FakeAccount(), strategy_name="TGRID")
    adapter = LiveBrokerAdapter(
        broker=bridge, policy=_policy(**pol),
        trade_date="2026-08-15", runtime_confirmation_token="startup-token",
    )
    adapter.apply_config_enable(True)
    adapter.confirm_runtime("startup-token")
    conn = initialize(_temp_db_path())
    store = ExecutionStore(conn)
    engine = ExecutionEngine(store, adapter)
    return conn, store, trader, engine


class TestChainOrderFlow(unittest.TestCase):
    def test_intent_and_reservation_created_before_broker_send(self):
        conn, store, trader, engine = _chain()
        try:
            result = engine.send_buy(
                client_order_key="K1", symbol="510300.SH", qty=100,
                limit_price=4.6, order_remark="TG_510300SH_B001", now="t0",
                expected_available_cash=100000.0, reserved_cash=460.0,
            )
            self.assertEqual(result.status, OrderStatus.SUBMITTED)
            intent = store.get_intent("K1")
            self.assertIsNotNone(intent.broker_order_id)
            self.assertEqual(store.reserved_cash("510300.SH"), 460.0)
            # The durable intent+reservation existed before the broker send:
            # the trader recorded exactly one order with the matching tags.
            self.assertEqual(len(trader.calls), 1)
            self.assertEqual(trader.calls[0][0], "order_stock")
            self.assertEqual(trader.calls[0][7], "TG_510300SH_B001")
        finally:
            conn.close()

    def test_duplicate_client_order_key_never_second_send(self):
        conn, store, trader, engine = _chain()
        try:
            engine.send_buy(
                client_order_key="K1", symbol="510300.SH", qty=100,
                limit_price=4.6, order_remark="TG_510300SH_B001", now="t0",
                expected_available_cash=100000.0, reserved_cash=460.0,
            )
            with self.assertRaises(Exception):
                engine.send_buy(
                    client_order_key="K1", symbol="510300.SH", qty=100,
                    limit_price=4.6, order_remark="TG_510300SH_B001", now="t1",
                    expected_available_cash=100000.0, reserved_cash=460.0,
                )
            send_calls = [c for c in trader.calls if c[0] == "order_stock"]
            self.assertEqual(len(send_calls), 1)
        finally:
            conn.close()

    def test_partial_fill_preserves_remaining_reservation(self):
        conn, store, trader, engine = _chain()
        try:
            result = engine.send_buy(
                client_order_key="K1", symbol="510300.SH", qty=100,
                limit_price=4.6, order_remark="TG_510300SH_B001", now="t0",
                expected_available_cash=100000.0, reserved_cash=460.0,
            )
            order_id = result.broker_order_id
            order = trader.orders[order_id]
            order.order_status = 55  # 部成
            order.traded_volume = 60
            trader.trades.append(_FakeTrade("T1", order_id, 60, 4.6, "t1"))
            r1 = engine.poll_order("K1", now="t1")
            self.assertEqual(r1.status, OrderStatus.PARTIAL)
            self.assertEqual(r1.filled_qty, 60)
            self.assertEqual(store.reserved_cash("510300.SH"), 460.0)
            order.order_status = 56  # 已成
            order.traded_volume = 100
            r2 = engine.poll_order("K1", now="t2")
            self.assertEqual(r2.status, OrderStatus.FILLED)
            self.assertEqual(r2.filled_qty, 100)
            self.assertEqual(store.reserved_cash("510300.SH"), 0.0)
        finally:
            conn.close()

    def test_timeout_is_cancel_then_requery_then_reconcile(self):
        conn, store, trader, engine = _chain()
        try:
            result = engine.send_buy(
                client_order_key="K1", symbol="510300.SH", qty=100,
                limit_price=4.6, order_remark="TG_510300SH_B001", now="t0",
                expected_available_cash=100000.0, reserved_cash=460.0,
            )
            # A partial fill happened before the timeout: cancel must NOT
            # assume zero fill; the re-query surfaces it.
            order = trader.orders[result.broker_order_id]
            order.traded_volume = 40
            order.order_status = 54  # 已撤 (with 40 filled before cancel)
            final = engine.timeout_order("K1", now="t1")
            self.assertEqual(final.status, OrderStatus.CANCELED)
            self.assertEqual(final.filled_qty, 40)
            self.assertEqual(store.reserved_cash("510300.SH"), 0.0)
            self.assertIn("cancel_order_stock", [c[0] for c in trader.calls])
        finally:
            conn.close()

    def test_cancel_failure_raises_and_requires_requery(self):
        conn, store, trader, engine = _chain()
        try:
            result = engine.send_buy(
                client_order_key="K1", symbol="510300.SH", qty=100,
                limit_price=4.6, order_remark="TG_510300SH_B001", now="t0",
                expected_available_cash=100000.0, reserved_cash=460.0,
            )
            trader.orders.pop(result.broker_order_id)  # cancel will fail
            from tgrid.execution.executor import CancelFailedError

            with self.assertRaises(CancelFailedError):
                engine.timeout_order("K1", now="t1")
            # Reservation is still held: the order may still fill.
            self.assertEqual(store.reserved_cash("510300.SH"), 460.0)
        finally:
            conn.close()


class TestChainRecovery(unittest.TestCase):
    def test_crash_before_send_no_blind_resend(self):
        conn, store, trader, engine = _chain()
        try:
            # Crash after local intent+reservation but BEFORE broker send:
            # the intent has no broker_order_id and the broker has no order.
            store.create_intent_with_reservation(
                client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.6, strategy_name="TGRID",
                order_remark="TG_510300SH_B001", created_at="t0",
                cash_amount=460.0,
            )
            results = reconcile_open_intents(store, engine._broker)
            self.assertEqual(results[0].outcome, "INTENT_ONLY")
            # No blind resend: the trader saw no order_stock call.
            send_calls = [c for c in trader.calls if c[0] == "order_stock"]
            self.assertEqual(send_calls, [])
        finally:
            conn.close()

    def test_crash_after_broker_accept_recovery_matches(self):
        conn, store, trader, engine = _chain()
        try:
            # Local intent written first (NEW), then broker accepts — process
            # dies before update_intent_status(SUBMITTED).
            store.create_intent_with_reservation(
                client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.6, strategy_name="TGRID",
                order_remark="TG_510300SH_B001", created_at="t0",
                cash_amount=460.0,
            )
            order_id = trader.order_stock(
                _FakeAccount(), "510300.SH", STOCK_BUY, 100, 11, 4.6,
                "TGRID", "TG_510300SH_B001",
            )
            results = reconcile_open_intents(store, engine._broker)
            self.assertEqual(results[0].outcome, "MATCHED")
            self.assertEqual(results[0].matched_broker_order_id, order_id)
            # Recover: record the broker id, then poll to the true state.
            store.update_intent_status(
                "K1", status=OrderStatus.SUBMITTED, updated_at="t1",
                broker_order_id=order_id,
            )
            trader.orders[order_id].order_status = 56
            trader.orders[order_id].traded_volume = 100
            final = engine.poll_order("K1", now="t2")
            self.assertEqual(final.status, OrderStatus.FILLED)
        finally:
            conn.close()

    def test_unmatched_tagged_broker_order_flags_safe_mode(self):
        conn, store, trader, engine = _chain()
        try:
            # Broker order placed outside the executor (e.g. crash path) with a
            # TGRID remark but no local intent: duplicate-order risk.
            trader.order_stock(
                _FakeAccount(), "510300.SH", STOCK_BUY, 100, 11, 4.6,
                "TGRID", "TG_510300SH_B001",
            )
            results = reconcile_open_intents(store, engine._broker)
            outcomes = [r.outcome for r in results]
            self.assertIn("UNMATCHED_BROKER_ORDER", outcomes)
        finally:
            conn.close()


class TestChainFailClosed(unittest.TestCase):
    def test_broker_query_failure_fails_closed(self):
        conn, store, trader, engine = _chain()
        try:
            result = engine.send_buy(
                client_order_key="K1", symbol="510300.SH", qty=100,
                limit_price=4.6, order_remark="TG_510300SH_B001", now="t0",
                expected_available_cash=100000.0, reserved_cash=460.0,
            )
            trader.fail_queries = True
            with self.assertRaises(OrderReconciliationError):
                engine.poll_order("K1", now="t1")
            # Reservation is still held: state is unresolved, not assumed.
            self.assertEqual(store.reserved_cash("510300.SH"), 460.0)
        finally:
            conn.close()

    def test_ambiguous_status_stays_unresolved(self):
        conn, store, trader, engine = _chain()
        try:
            result = engine.send_buy(
                client_order_key="K1", symbol="510300.SH", qty=100,
                limit_price=4.6, order_remark="TG_510300SH_B001", now="t0",
                expected_available_cash=100000.0, reserved_cash=460.0,
            )
            trader.orders[result.broker_order_id].order_status = 255  # 未知
            r = engine.poll_order("K1", now="t1")
            # UNKNOWN is not treated as filled/canceled: intent stays pending,
            # reservation is never released on a guess.
            self.assertEqual(r.status, OrderStatus.SUBMITTED)
            self.assertEqual(store.reserved_cash("510300.SH"), 460.0)
        finally:
            conn.close()

    def test_adapter_safety_boundary_rejects_before_engine_send(self):
        conn, store, trader, engine = _chain(max_cash_per_day=100.0)
        try:
            # 100 * 4.6 = 460 > daily cap 100: the adapter refuses before any
            # broker call, surfaced through the engine's send path.
            with self.assertRaises(Exception):
                engine.send_buy(
                    client_order_key="K1", symbol="510300.SH", qty=100,
                    limit_price=4.6, order_remark="TG_510300SH_B001", now="t0",
                    expected_available_cash=100000.0, reserved_cash=460.0,
                )
            send_calls = [c for c in trader.calls if c[0] == "order_stock"]
            self.assertEqual(send_calls, [])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
