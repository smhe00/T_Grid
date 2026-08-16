"""TGrid <-> qmt-execution-core adapter tests (migration Phase B).

Covers the ExecutionRequest mapping, the TGrid ExecutionGuard evidence, the
sidecar's pre-broker durable-ledger commit (ordering + fail closed), snapshot
mapping back to the TGrid SQLite ledger, and one end-to-end public-core
session driven through the TGrid sidecar + guard (Phase-C seed).
"""

import os
import tempfile
import unittest

from qmt_execution_core.domain import (
    BrokerOrder,
    BrokerOrderStatus,
    CancelRequestResult,
    ExecutionRequest,
    ExecutionSnapshot,
    Side,
    TradeState,
)
from qmt_execution_core.session import ExecutionSession

from tgrid.execution.models import BUY, SELL, OrderStatus
from tgrid.execution.store import ExecutionStore
from tgrid.integrations.daily_exposure import DailyExposureLedger
from tgrid.integrations.live_broker_adapter import LiveBrokerPolicy
from tgrid.integrations.qec_adapter import (
    TGridExecutionGuard,
    TGridSidecar,
    apply_snapshot,
    make_execution_request,
    snapshot_status_to_tgrid,
)
from tgrid.persistence import initialize


def _temp_db_path() -> str:
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    return handle.name


def _policy(**overrides) -> LiveBrokerPolicy:
    cfg = dict(
        allowlist=frozenset({"510300.SH"}),
        max_order_qty=1000,
        max_cash_per_order=100000.0,
        max_cash_per_day=500000.0,
    )
    cfg.update(overrides)
    return LiveBrokerPolicy(**cfg)


class _DictStore:
    """Durable key/value surface for the DailyExposureLedger."""

    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value):
        self._data[key] = value


def _now() -> str:
    return "2026-08-16T09:30:00"


def _sidecar(conn, exposure=None):
    store = ExecutionStore(conn)
    sidecar = TGridSidecar(
        store=store,
        exposure=exposure or DailyExposureLedger(trade_date="2026-08-16"),
        strategy_name="TGRID",
        now=_now,
    )
    return store, sidecar


def _guard(**flags) -> TGridExecutionGuard:
    def _ok(*args):
        return True

    values = dict(
        environment_verified=True,
        account_verified=True,
        broker_snapshot_verified=True,
        position_verified=True,
        cash_verified=True,
        quote_verified=True,
        kill_switch_active=False,
        exposure_ready=True,
    )
    values.update(flags)

    def _cb(value):
        return lambda: value

    return TGridExecutionGuard(
        policy=_policy(),
        environment_verified=_cb(values["environment_verified"]),
        account_verified=_cb(values["account_verified"]),
        broker_snapshot_verified=_cb(values["broker_snapshot_verified"]),
        position_verified=_cb(values["position_verified"]),
        cash_verified=_cb(values["cash_verified"]),
        quote_verified=_cb(values["quote_verified"]),
        kill_switch_active=_cb(values["kill_switch_active"]),
        exposure_ready=_cb(values["exposure_ready"]),
        exposure_used=_cb(0.0),
    )


class _FakeQecBroker:
    """Minimal public-core BrokerPort fake (native int order ids)."""

    def __init__(self):
        self.orders = {}
        self.next_id = 9000
        self.place_calls = 0
        self.cancel_calls = 0
        self.healthy = True

    def execution_healthy(self):
        return self.healthy

    def place_order(self, request: ExecutionRequest) -> int:
        self.place_calls += 1
        self.next_id += 1
        oid = self.next_id
        self.orders[oid] = BrokerOrder(
            order_id=oid,
            symbol=request.symbol,
            side=request.side,
            qty=request.qty,
            filled_qty=0,
            status=BrokerOrderStatus.WORKING,
            order_remark=request.order_remark,
            client_order_id=request.client_order_id,
        )
        return oid

    def cancel_order(self, order_id: int) -> CancelRequestResult:
        self.cancel_calls += 1
        self.orders[order_id] = BrokerOrder(
            **{
                **self.orders[order_id].__dict__,
                "status": BrokerOrderStatus.CANCEL_PENDING,
            }
        )
        return CancelRequestResult.ACCEPTED

    def query_order(self, order_id: int) -> BrokerOrder:
        return self.orders[order_id]

    def query_orders(self):
        return tuple(self.orders.values())


class TestRequestMapping(unittest.TestCase):
    def test_maps_all_fields(self):
        request = make_execution_request(
            client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
            limit_price=4.7, strategy_name="TGRID",
            order_remark="TG_510300SH_B001",
        )
        self.assertEqual(request.client_order_id, "K1")
        self.assertEqual(request.symbol, "510300.SH")
        self.assertEqual(request.side, Side.BUY)
        self.assertEqual(request.qty, 100)
        self.assertEqual(request.limit_price, 4.7)
        self.assertEqual(request.strategy_id, "TGRID")
        self.assertEqual(request.order_remark, "TG_510300SH_B001")

    def test_rejects_bad_side(self):
        with self.assertRaises(ValueError):
            make_execution_request(
                client_order_key="K1", symbol="510300.SH", side="HOLD",
                qty=100, limit_price=4.7, strategy_name="TGRID",
                order_remark="R1",
            )


class TestTGridExecutionGuard(unittest.TestCase):
    def test_allows_when_all_gates_pass(self):
        request = make_execution_request(
            client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
            limit_price=4.7, strategy_name="TGRID", order_remark="R1",
        )
        evidence = _guard().verify(request)
        evidence.validate()
        self.assertTrue(evidence.allowed)

    def test_rejects_allowlist_miss(self):
        request = make_execution_request(
            client_order_key="K1", symbol="600000.SH", side=BUY, qty=100,
            limit_price=4.7, strategy_name="TGRID", order_remark="R1",
        )
        self.assertFalse(_guard().verify(request).allowed)

    def test_rejects_qty_cap(self):
        request = make_execution_request(
            client_order_key="K1", symbol="510300.SH", side=BUY, qty=5000,
            limit_price=4.7, strategy_name="TGRID", order_remark="R1",
        )
        self.assertFalse(_guard().verify(request).allowed)

    def test_rejects_cash_cap(self):
        request = make_execution_request(
            client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
            limit_price=4000.0, strategy_name="TGRID", order_remark="R1",
        )
        self.assertFalse(_guard().verify(request).allowed)

    def test_rejects_daily_cap_via_exposure_used(self):
        values = dict(exposure_used=480000.0)
        request = make_execution_request(
            client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
            limit_price=470.0, strategy_name="TGRID", order_remark="R1",
        )  # 47000 + 480000 > 500000
        guard = TGridExecutionGuard(
            policy=_policy(),
            environment_verified=lambda: True,
            account_verified=lambda: True,
            broker_snapshot_verified=lambda: True,
            position_verified=lambda: True,
            cash_verified=lambda: True,
            quote_verified=lambda: True,
            kill_switch_active=lambda: False,
            exposure_ready=lambda: True,
            exposure_used=lambda: values["exposure_used"],
        )
        self.assertFalse(guard.verify(request).allowed)

    def test_rejects_kill_switch_and_unverified(self):
        request = make_execution_request(
            client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
            limit_price=4.7, strategy_name="TGRID", order_remark="R1",
        )
        self.assertFalse(_guard(kill_switch_active=True).verify(request).allowed)
        self.assertFalse(_guard(quote_verified=False).verify(request).allowed)
        self.assertFalse(_guard(exposure_ready=False).verify(request).allowed)

    def test_verify_session(self):
        ok = _guard().verify_session()
        ok.validate()
        self.assertTrue(ok.ready)
        bad = _guard(account_verified=False).verify_session()
        self.assertFalse(bad.ready)


class TestTGridSidecar(unittest.TestCase):
    def test_submit_persists_intent_reservation_and_exposure(self):
        path = _temp_db_path()
        conn = initialize(path)
        exposure = DailyExposureLedger(trade_date="2026-08-16", store=_DictStore())
        try:
            store, sidecar = _sidecar(conn, exposure=exposure)
            request = make_execution_request(
                client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.7, strategy_name="TGRID",
                order_remark="TG_510300SH_B001",
            )
            sidecar.before_broker_submit(request)
            intent = store.get_intent("K1")
            self.assertEqual(intent.symbol, "510300.SH")
            self.assertEqual(intent.side, "BUY")
            self.assertEqual(intent.order_remark, "TG_510300SH_B001")
            self.assertEqual(intent.status, OrderStatus.NEW)
            reservations = tuple(store.list_active_reservations())
            self.assertEqual(len(reservations), 1)
            self.assertEqual(reservations[0].cash_amount, 470.0)
            self.assertEqual(exposure.used, 470.0)  # 100 * 4.7
        finally:
            conn.close()
            os.remove(path)

    def test_submit_failure_fails_closed(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            store, sidecar = _sidecar(conn)
            request = make_execution_request(
                client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.7, strategy_name="TGRID", order_remark="R1",
            )
            sidecar.before_broker_submit(request)
            # duplicate client_order_key -> the hook raises; the broker is
            # never reached by the public session (fail closed).
            with self.assertRaises(Exception):
                sidecar.before_broker_submit(request)
        finally:
            conn.close()
            os.remove(path)

    def test_sell_does_not_record_exposure(self):
        path = _temp_db_path()
        conn = initialize(path)
        exposure = DailyExposureLedger(trade_date="2026-08-16", store=_DictStore())
        try:
            store, sidecar = _sidecar(conn, exposure=exposure)
            request = make_execution_request(
                client_order_key="K1", symbol="510300.SH", side=SELL, qty=100,
                limit_price=4.7, strategy_name="TGRID", order_remark="R1",
            )
            sidecar.before_broker_submit(request)
            self.assertEqual(exposure.used, 0.0)
        finally:
            conn.close()
            os.remove(path)

    def test_cancel_marks_intent(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            store, sidecar = _sidecar(conn)
            request = make_execution_request(
                client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.7, strategy_name="TGRID", order_remark="R1",
            )
            sidecar.before_broker_submit(request)
            store.update_intent_status("K1", status=OrderStatus.SUBMITTED,
                                       updated_at=_now(), broker_order_id="9001")
            sidecar.before_broker_cancel(9001)
            self.assertEqual(store.get_intent("K1").status,
                             OrderStatus.CANCEL_REQUESTED)
        finally:
            conn.close()
            os.remove(path)


class TestSnapshotMapping(unittest.TestCase):
    def test_status_map_covers_all_trade_states(self):
        for state in TradeState:
            snapshot_status_to_tgrid(state)  # must not raise

    def test_apply_snapshot_updates_intent_and_releases_on_filled(self):
        conn = initialize(_temp_db_path())
        try:
            store, sidecar = _sidecar(conn)
            request = make_execution_request(
                client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.7, strategy_name="TGRID", order_remark="R1",
            )
            sidecar.before_broker_submit(request)
            working = ExecutionSnapshot(
                state=TradeState.WORKING,
                client_order_id="K1",
                broker_order_id=9001,
                ordered_qty=100,
                filled_qty=0,
            )
            apply_snapshot(store, working, client_order_key="K1", now=_now())
            intent = store.get_intent("K1")
            self.assertEqual(intent.status, OrderStatus.SUBMITTED)
            self.assertEqual(intent.broker_order_id, "9001")
            filled = ExecutionSnapshot(
                state=TradeState.FILLED,
                client_order_id="K1",
                broker_order_id=9001,
                ordered_qty=100,
                filled_qty=100,
                average_fill_price=4.69,
            )
            apply_snapshot(store, filled, client_order_key="K1", now=_now())
            self.assertEqual(store.get_intent("K1").status, OrderStatus.FILLED)
            self.assertEqual(tuple(store.list_active_reservations()), ())
        finally:
            conn.close()


class TestQecIntegration(unittest.TestCase):
    """Phase-C seed: public-core session driven through the TGrid sidecar."""

    def test_full_cycle_through_tgrid_sidecar_and_guard(self):
        import tempfile as _tf

        conn = initialize(_temp_db_path())
        exposure = DailyExposureLedger(trade_date="2026-08-16", store=_DictStore())
        tmp = _tf.mkdtemp()
        try:
            store, sidecar = _sidecar(conn, exposure=exposure)
            broker = _FakeQecBroker()
            session = ExecutionSession(
                broker=broker,
                guard=_guard(),
                journal_path=os.path.join(tmp, "journal.json"),
                lock_path=os.path.join(tmp, "exec.lock"),
                execution_id="TGRID",
                before_broker_submit=sidecar.before_broker_submit,
                before_broker_cancel=sidecar.before_broker_cancel,
            )
            session.open()
            request = make_execution_request(
                client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.7, strategy_name="TGRID",
                order_remark="TG_510300SH_B001",
            )
            snap = session.submit(request)
            self.assertEqual(snap.state, TradeState.WORKING)
            self.assertEqual(broker.place_calls, 1)
            # TGrid ledger committed before the broker call (sidecar).
            intent = store.get_intent("K1")
            self.assertEqual(intent.status, OrderStatus.NEW)
            self.assertEqual(exposure.used, 470.0)
            apply_snapshot(store, snap, client_order_key="K1", now=_now())
            self.assertEqual(store.get_intent("K1").broker_order_id,
                             str(snap.broker_order_id))
            # Broker fills -> poll -> FILLED -> TGrid ledger folds.
            broker.orders[snap.broker_order_id] = BrokerOrder(
                order_id=snap.broker_order_id,
                symbol="510300.SH",
                side=Side.BUY,
                qty=100,
                filled_qty=100,
                status=BrokerOrderStatus.FILLED,
                order_remark="TG_510300SH_B001",
                average_fill_price=4.69,
            )
            filled = session.poll()
            self.assertEqual(filled.state, TradeState.FILLED)
            apply_snapshot(store, filled, client_order_key="K1", now=_now())
            self.assertEqual(store.get_intent("K1").status, OrderStatus.FILLED)
            self.assertEqual(tuple(store.list_active_reservations()), ())
            session.close()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
