"""Iteration 15 integration tests (architect audit 93f8663).

* P1-1: production composition — exactly ONE ExecutionSession authority
  (TGridQecStack binds the engine to runtime.session; one submit -> one
  broker call; close releases once);
* P1-2: no recoverable public state terminalizes the TGrid ledger
  (table-driven invariant + cancel-rejected -> ambiguous -> recovery ->
  FILLED regression);
* P2-1: single-active-order-per-engine declared constraint.
"""

import os
import tempfile
import unittest
from types import SimpleNamespace

from qmt_execution_core.domain import (
    BrokerOrderStatus,
    ExecutionRequest,
    Side,
    TradeState,
)
from qmt_execution_core.miniqmt.binding import QmtAccountBinding

from tgrid.execution.models import BUY, OrderStatus
from tgrid.execution.store import ExecutionStore
from tgrid.integrations.daily_exposure import DailyExposureLedger
from tgrid.integrations.live_broker_adapter import LiveBrokerPolicy
from tgrid.integrations.qec_adapter import (
    TGridEvidenceSource,
    TGridSidecar,
    apply_snapshot,
    make_execution_request,
    snapshot_status_to_tgrid,
)
from tgrid.integrations.qec_runtime import (
    TGridQecStack,
    build_tgrid_qec_stack,
)
from tgrid.persistence import initialize


class XtConstant:
    SECURITY_ACCOUNT = 2
    ACCOUNT_STATUS_OK = 0
    FIX_PRICE = 11
    STOCK_BUY = 23
    STOCK_SELL = 24


class RawOrder:
    def __init__(self, order_id, status=50, filled=0, qty=0, remark="", strategy_name=""):
        self.order_id = order_id
        self.order_status = status
        self.filled_vol = filled
        self.order_volume = qty
        self.order_remark = remark
        self.strategy_name = strategy_name
        self.stock_code = "510300.SH"
        self.price = 4.7
        self.order_type = 23
        self.order_sysid = str(order_id)
        self.status_msg = ""
        self.traded_volume = 0
        self.traded_price = 0.0


class FakeTrader:
    def __init__(self):
        self.account_id = "A123"
        self.account_type = 2
        self.account_status = 0
        self.connect_result = 0
        self.subscribe_result = 0
        self.unsubscribe_result = 0
        self.place_calls = 0
        self.order = None
        self.cancel_result = 0
        self.callback = None

    def register_callback(self, callback):
        self.callback = callback

    def start(self):
        pass

    def stop(self):
        pass

    def connect(self):
        return self.connect_result

    def subscribe(self, account):
        return self.subscribe_result

    def unsubscribe(self, account):
        return self.unsubscribe_result

    def query_account_infos(self):
        return [SimpleNamespace(account_id=self.account_id, account_type=self.account_type)]

    def query_account_status(self):
        return [SimpleNamespace(
            account_id=self.account_id, account_type=self.account_type,
            status=self.account_status,
        )]

    def order_stock(self, account, symbol, order_type, qty, price_type, price, strategy, remark):
        self.place_calls += 1
        self.order = RawOrder(
            order_id=100 + self.place_calls, status=50, qty=qty,
            remark=remark, strategy_name=strategy,
        )
        return self.order.order_id

    def cancel_order_stock(self, account, order_id):
        if self.cancel_result == 0 and self.order is not None:
            self.order.order_status = 51
        return self.cancel_result

    def query_stock_order(self, account, order_id):
        return self.order

    def query_stock_orders(self, account, cancelable_only=False):
        return [] if self.order is None else [self.order]

    def query_stock_asset(self, account):
        return SimpleNamespace(cash=100000.0, frozen_cash=0.0, market_value=0.0, total_asset=100000.0)

    def query_stock_positions(self, account):
        return [SimpleNamespace(
            stock_code="510300.SH", volume=1000, can_use_volume=900,
            frozen_volume=100, market_value=4700.0, avg_price=4.5,
        )]

    def query_stock_trades(self, account):
        return []


def _temp_db_path() -> str:
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    return handle.name


def _policy() -> LiveBrokerPolicy:
    return LiveBrokerPolicy(
        allowlist=frozenset({"510300.SH"}),
        max_order_qty=1000,
        max_cash_per_order=100000.0,
        max_cash_per_day=500000.0,
    )


class _DictStore:
    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value):
        self._data[key] = value


def _now() -> str:
    return "2026-08-16T14:00:00"


def _evidence() -> TGridEvidenceSource:
    def _ok():
        return True

    return TGridEvidenceSource(
        environment_verified=_ok, account_verified=_ok,
        broker_snapshot_verified=_ok, position_verified=_ok,
        cash_verified=_ok, quote_verified=_ok,
        kill_switch_active=lambda: False, exposure_ready=_ok,
        exposure_used=lambda: 0.0,
    )


class TestTGridQecStack(unittest.TestCase):
    """P1-1: one and only one execution-session authority."""

    def _stack(self):
        self.tmp = tempfile.mkdtemp()
        self.qmt = os.path.join(self.tmp, "qmt")
        os.makedirs(self.qmt, exist_ok=True)
        binding = QmtAccountBinding.create(
            environment="simulation", account_type=2, account_id="A123",
            qmt_path=self.qmt,
        )
        self.binding_path = os.path.join(self.tmp, "binding.json")
        binding.write(self.binding_path)
        self.db_path = _temp_db_path()
        self.conn = initialize(self.db_path)
        self.store = ExecutionStore(self.conn)
        self.exposure = DailyExposureLedger(trade_date="2026-08-16", store=_DictStore())
        self.trader = FakeTrader()
        stack = build_tgrid_qec_stack(
            environment="simulation",
            qmt_path=self.qmt,
            binding_path=self.binding_path,
            journal_path=os.path.join(self.tmp, "journal.json"),
            lock_path=os.path.join(self.tmp, "exec.lock"),
            strategy_name="TGRID",
            trade_date="2026-08-16",
            store=self.store,
            exposure=self.exposure,
            policy=_policy(),
            now=_now,
            evidence=_evidence(),
            trader_factory=lambda path, sid: self.trader,
            stock_account_factory=lambda account_id: SimpleNamespace(account_id=account_id),
            xtconstant=XtConstant,
            callback_base=object,
        )
        return stack

    def tearDown(self):
        try:
            self.stack.close()
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass
        db_path = getattr(self, "db_path", None)
        if db_path and os.path.exists(db_path):
            os.remove(db_path)

    def test_single_session_authority(self):
        stack = self._stack()
        self.stack = stack
        self.assertIsInstance(stack, TGridQecStack)
        # The engine IS bound to the runtime's session — one authority.
        self.assertIs(stack.engine.session, stack.runtime.session)
        request = ExecutionRequest(
            client_order_id="K1", symbol="510300.SH", side=Side.BUY, qty=100,
            limit_price=4.7, strategy_id="TGRID", order_remark="TG_510300SH_B001",
        )
        snap = stack.runtime.submit(request)
        self.assertEqual(snap.state.value, "working")
        # One fake submit -> exactly one broker-side call.
        self.assertEqual(self.trader.place_calls, 1)

    def test_engine_ops_go_through_runtime_session(self):
        stack = self._stack()
        self.stack = stack
        # Engine send_buy drives the SAME runtime session (no second session).
        result = stack.engine.send_buy(
            client_order_key="K1", symbol="510300.SH", qty=100,
            limit_price=4.7, order_remark="TG_510300SH_B001", now=_now(),
            expected_available_cash=100000.0, reserved_cash=470.0,
        )
        self.assertEqual(result.status, OrderStatus.SUBMITTED)
        self.assertEqual(self.trader.place_calls, 1)
        # TGrid ledger committed via the runtime-bound sidecar.
        self.assertEqual(self.exposure.used, 470.0)
        self.assertEqual(self.store.get_intent("K1").status, OrderStatus.SUBMITTED)

    def test_close_releases_runtime_exactly_once(self):
        stack = self._stack()
        stack.close()
        self.assertTrue(stack.runtime._closed)
        # Closing again is a no-op (runtime close is idempotent).
        stack.close()
        self.assertTrue(stack.runtime._closed)


class TestLedgerTerminalityInvariant(unittest.TestCase):
    """P1-2: recoverable public states never terminalize the TGrid ledger."""

    def test_no_recoverable_public_state_maps_to_terminal_tgrid_status(self):
        terminal_tgrid = {"FILLED", "CANCELED", "REJECTED", "UNKNOWN"}
        # CANCEL_REJECTED is recoverable -> must map to a NONTERMINAL status.
        mapped = snapshot_status_to_tgrid(TradeState.CANCEL_REJECTED)
        self.assertNotIn(mapped, terminal_tgrid)
        self.assertEqual(mapped, OrderStatus.CANCEL_REQUESTED)
        # Only terminal public outcomes map to terminal TGrid statuses.
        for state in (TradeState.FILLED, TradeState.CANCELLED,
                      TradeState.REJECTED, TradeState.FAILED):
            self.assertIn(snapshot_status_to_tgrid(state), terminal_tgrid)
        # UNKNOWN is recoverable: its protection is at apply_snapshot
        # (covered by test_apply_snapshot_never_terminalizes_on_recoverable_states).

    def test_apply_snapshot_never_terminalizes_on_recoverable_states(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            store = ExecutionStore(conn)
            sidecar = TGridSidecar(store=store, exposure=DailyExposureLedger(),
                                   strategy_name="TGRID", now=_now)
            request = make_execution_request(
                client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.7, strategy_name="TGRID", order_remark="R1",
            )
            sidecar.before_broker_submit(request)
            store.update_intent_status("K1", status=OrderStatus.SUBMITTED,
                                       updated_at=_now(), broker_order_id="9001")
            for state in (TradeState.UNKNOWN, TradeState.CANCEL_REJECTED,
                          TradeState.WORKING, TradeState.PARTIALLY_FILLED,
                          TradeState.CANCELLING, TradeState.PENDING_CANCEL):
                apply_snapshot(store, _snap(state, 9001),
                               client_order_key="K1", now=_now())
                self.assertNotEqual(store.get_intent("K1").status,
                                    OrderStatus.UNKNOWN, state.value)
        finally:
            conn.close()
            os.remove(path)


def _snap(state, oid=9001, filled=0):
    from qmt_execution_core.domain import ExecutionSnapshot

    return ExecutionSnapshot(state=state, client_order_id="K1",
                             broker_order_id=oid, ordered_qty=100,
                             filled_qty=filled)


class TestCancelRejectedRecovery(unittest.TestCase):
    """P1-2 regression: WORKING -> cancel rejected -> UNKNOWN -> WORKING/FILLED."""

    def test_cancel_rejected_ambiguous_recovery_reaches_filled(self):
        from qmt_execution_core.session import ExecutionSession

        from tgrid.integrations.qec_adapter import TGridExecutionGuard

        def _ok():
            return True

        guard = TGridExecutionGuard(
            policy=_policy(),
            environment_verified=_ok, account_verified=_ok,
            broker_snapshot_verified=_ok, position_verified=_ok,
            cash_verified=_ok, quote_verified=_ok,
            kill_switch_active=lambda: False, exposure_ready=_ok,
            exposure_used=lambda: 0.0,
        )
        broker = _ScriptBroker()
        path = _temp_db_path()
        conn = initialize(path)
        tmp = tempfile.mkdtemp()
        try:
            store = ExecutionStore(conn)
            exposure = DailyExposureLedger(trade_date="2026-08-16", store=_DictStore())
            sidecar = TGridSidecar(store=store, exposure=exposure,
                                   strategy_name="TGRID", now=_now)
            session = ExecutionSession(
                broker=broker, guard=guard,
                journal_path=os.path.join(tmp, "j.json"),
                lock_path=os.path.join(tmp, "e.lock"), execution_id="TGRID",
                before_broker_submit=sidecar.before_broker_submit,
                before_broker_cancel=sidecar.before_broker_cancel,
            )
            session.open()
            snap = session.submit(make_execution_request(
                client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.7, strategy_name="TGRID", order_remark="R1",
            ))
            apply_snapshot(store, snap, client_order_key="K1", now=_now())
            oid = snap.broker_order_id
            # Cancel request REJECTED -> CANCEL_REJECTED (recoverable); the
            # session's trailing poll immediately recovers to WORKING.
            broker.cancel_result = "rejected"
            out = session.cancel()
            self.assertEqual(out.state, TradeState.WORKING)
            apply_snapshot(store, out, client_order_key="K1", now=_now())
            self.assertNotEqual(store.get_intent("K1").status, OrderStatus.UNKNOWN)
            # Ambiguous UNKNOWN observation -> recoverable; status preserved.
            broker._set_status(oid, BrokerOrderStatus.UNKNOWN)
            out = session.poll()
            self.assertEqual(out.state, TradeState.UNKNOWN)
            apply_snapshot(store, out, client_order_key="K1", now=_now())
            self.assertNotEqual(store.get_intent("K1").status, OrderStatus.UNKNOWN)
            # Authoritative recovery -> WORKING -> FILLED (one submit only).
            broker._set_status(oid, BrokerOrderStatus.WORKING)
            out = session.poll()
            self.assertEqual(out.state, TradeState.WORKING)
            apply_snapshot(store, out, client_order_key="K1", now=_now())
            broker._set_status(oid, BrokerOrderStatus.FILLED, filled=100, price=4.69)
            out = session.poll()
            self.assertEqual(out.state, TradeState.FILLED)
            apply_snapshot(store, out, client_order_key="K1", now=_now())
            self.assertEqual(store.get_intent("K1").status, OrderStatus.FILLED)
            self.assertEqual(tuple(store.list_active_reservations()), ())
            self.assertEqual(broker.place_calls, 1)
            session.close()
        finally:
            conn.close()
            os.remove(path)


class _ScriptBroker:
    def __init__(self):
        self.orders = {}
        self.next_id = 9000
        self.place_calls = 0
        self.cancel_result = "accepted"

    def execution_healthy(self):
        return True

    def place_order(self, request):
        from qmt_execution_core.domain import BrokerOrder, BrokerOrderStatus

        self.place_calls += 1
        self.next_id += 1
        self.orders[self.next_id] = BrokerOrder(
            order_id=self.next_id, symbol=request.symbol, side=request.side,
            qty=request.qty, filled_qty=0, status=BrokerOrderStatus.WORKING,
            order_remark=request.order_remark,
        )
        return self.next_id

    def cancel_order(self, order_id):
        from qmt_execution_core.domain import CancelRequestResult

        if self.cancel_result == "rejected":
            return CancelRequestResult.REJECTED
        self._set_status(order_id, BrokerOrderStatus.CANCEL_PENDING)
        return CancelRequestResult.ACCEPTED

    def query_order(self, order_id):
        return self.orders[order_id]

    def query_orders(self):
        return tuple(self.orders.values())

    def _set_status(self, order_id, status, filled=None, price=None):
        from qmt_execution_core.domain import BrokerOrder

        current = self.orders[order_id]
        self.orders[order_id] = BrokerOrder(
            order_id=current.order_id, symbol=current.symbol,
            side=current.side, qty=current.qty,
            filled_qty=current.filled_qty if filled is None else filled,
            status=status, order_remark=current.order_remark,
            client_order_id=current.client_order_id,
            average_fill_price=price,
        )


class TestSingleActiveOrderConstraint(unittest.TestCase):
    """P2-1: single-active-order-per-engine is an explicit design constraint."""

    def test_engine_refuses_concurrent_second_order(self):
        from tgrid.execution.executor import ExecutionEngine
        from tgrid.execution.simbroker import SimBroker

        conn = initialize(_temp_db_path())
        try:
            store = ExecutionStore(conn)
            engine = ExecutionEngine(store, SimBroker(), strategy_name="TGRID")
            try:
                engine.send_buy(
                    client_order_key="K1", symbol="510300.SH", qty=100,
                    limit_price=4.7, order_remark="R1", now=_now(),
                    expected_available_cash=100000.0, reserved_cash=470.0,
                )
                with self.assertRaises(Exception):
                    engine.send_buy(
                        client_order_key="K2", symbol="510300.SH", qty=100,
                        limit_price=4.7, order_remark="R2", now=_now(),
                        expected_available_cash=100000.0, reserved_cash=470.0,
                    )
            finally:
                engine.close()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
