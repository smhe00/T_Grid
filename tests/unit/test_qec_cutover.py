"""Phase C capability scan + old-vs-new lifecycle comparison (migration).

* capability scan: prove TGrid production code has ZERO raw QMT order/cancel
  call sites (the public core is the only QMT side-effect authority); the
  legacy ``xtquant_bridge.py`` remains only as the retained equivalence path;
* old-vs-new: drive the legacy TGrid ExecutionEngine (SimBroker) and the
  public-core ExecutionSession (TGrid sidecar + guard) against the same TGrid
  store and compare the terminal OrderIntent lifecycle + reservation release.
"""

import ast
import glob
import os
import tempfile
import unittest

from tgrid.execution.models import BUY, OrderStatus
from tgrid.execution.executor import ExecutionEngine
from tgrid.execution.simbroker import SimBroker
from tgrid.execution.store import ExecutionStore
from tgrid.integrations.daily_exposure import DailyExposureLedger
from tgrid.integrations.live_broker_adapter import LiveBrokerPolicy
from tgrid.integrations.qec_adapter import (
    TGridExecutionGuard,
    TGridSidecar,
    apply_snapshot,
    make_execution_request,
)
from tgrid.persistence import initialize

RAW_QMT_CALLS = ("order_stock", "order_stock_async",
                 "cancel_order_stock", "cancel_order_stock_async")

_SRC_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "src")
)


def _temp_db_path() -> str:
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    return handle.name


def _now() -> str:
    return "2026-08-16T11:30:00"


class _DictStore:
    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value):
        self._data[key] = value


class TestCapabilityScan(unittest.TestCase):
    """Zero TGrid production raw QMT order/cancel call sites after cutover."""

    def _raw_call_sites(self):
        sites = []
        for path in glob.glob(os.path.join(_SRC_ROOT, "**", "*.py"), recursive=True):
            rel = os.path.relpath(path, _SRC_ROOT).replace("\\", "/")
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = ""
                    if isinstance(func, ast.Name):
                        name = func.id
                    elif isinstance(func, ast.Attribute):
                        name = func.attr
                    if name in RAW_QMT_CALLS:
                        sites.append((rel, node.lineno, name))
        return sites

    def test_zero_raw_qmt_call_sites_in_production_modules(self):
        sites = self._raw_call_sites()
        # The ONLY allowed owner of raw QMT side effects is the legacy bridge
        # (retained for equivalence during migration); the qec adapter/runtime
        # and everything else must have ZERO.
        offending = [s for s in sites if not s[0].endswith("xtquant_bridge.py")]
        self.assertEqual(
            offending, [],
            f"raw QMT call sites outside the retained legacy bridge: {offending}",
        )
        self.assertTrue(any(s[0].endswith("xtquant_bridge.py") for s in sites))


class _FakeQecBroker:
    """Public-core BrokerPort fake (native int order ids) for the new path."""

    def __init__(self):
        self.orders = {}
        self.next_id = 9000
        self.place_calls = 0
        self.healthy = True

    def execution_healthy(self):
        return self.healthy

    def place_order(self, request):
        self.place_calls += 1
        self.next_id += 1
        from qmt_execution_core.domain import BrokerOrder, BrokerOrderStatus

        self.orders[self.next_id] = BrokerOrder(
            order_id=self.next_id, symbol=request.symbol, side=request.side,
            qty=request.qty, filled_qty=0, status=BrokerOrderStatus.WORKING,
            order_remark=request.order_remark,
        )
        return self.next_id

    def cancel_order(self, order_id):
        from qmt_execution_core.domain import CancelRequestResult

        return CancelRequestResult.ACCEPTED

    def query_order(self, order_id):
        return self.orders[order_id]

    def query_orders(self):
        return tuple(self.orders.values())


class TestOldVsNewLifecycleEquivalence(unittest.TestCase):
    """Terminal OrderIntent lifecycle parity between the two paths."""

    def _new_path_cycle(self, conn):
        """Public-core path: sidecar + guard + fake broker -> FILLED."""
        from qmt_execution_core.domain import BrokerOrder, BrokerOrderStatus, Side
        from qmt_execution_core.session import ExecutionSession

        store = ExecutionStore(conn)
        exposure = DailyExposureLedger(trade_date="2026-08-16", store=_DictStore())
        sidecar = TGridSidecar(store=store, exposure=exposure,
                               strategy_name="TGRID", now=_now)
        broker = _FakeQecBroker()

        def _ok():
            return True

        guard = TGridExecutionGuard(
            policy=LiveBrokerPolicy(
                allowlist=frozenset({"510300.SH"}), max_order_qty=1000,
                max_cash_per_order=100000.0, max_cash_per_day=500000.0,
            ),
            environment_verified=_ok, account_verified=_ok,
            broker_snapshot_verified=_ok, position_verified=_ok,
            cash_verified=_ok, quote_verified=_ok,
            kill_switch_active=lambda: False, exposure_ready=_ok,
            exposure_used=lambda: 0.0,
        )
        tmp = tempfile.mkdtemp()
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
        broker.orders[oid] = BrokerOrder(
            order_id=oid, symbol="510300.SH", side=Side.BUY, qty=100,
            filled_qty=100, status=BrokerOrderStatus.FILLED,
            order_remark="R1", average_fill_price=4.69,
        )
        filled = session.poll()
        apply_snapshot(store, filled, client_order_key="K1", now=_now())
        session.close()
        return store

    def _old_path_cycle(self, conn):
        """Legacy TGrid path: ExecutionEngine + SimBroker -> FILLED."""
        store = ExecutionStore(conn)
        broker = SimBroker()
        engine = ExecutionEngine(store, broker, strategy_name="TGRID")
        result = engine.send_buy(
            client_order_key="K1", symbol="510300.SH", qty=100,
            limit_price=4.7, order_remark="R1", now="t0",
            expected_available_cash=100000.0, reserved_cash=470.0,
        )
        broker.get_order(result.broker_order_id).script = (("FILL", 100, 4.69),)
        broker.tick_order(result.broker_order_id)
        engine.poll_order("K1", now="t1")
        return store

    def test_both_paths_land_in_filled_with_released_reservation(self):
        db_new = _temp_db_path()
        db_old = _temp_db_path()
        conn_new = initialize(db_new)
        conn_old = initialize(db_old)
        try:
            store_new = self._new_path_cycle(conn_new)
            store_old = self._old_path_cycle(conn_old)
            for label, store in (("new", store_new), ("old", store_old)):
                intent = store.get_intent("K1")
                self.assertEqual(intent.status, OrderStatus.FILLED, label)
                self.assertIsNotNone(intent.broker_order_id, label)
                self.assertEqual(tuple(store.list_active_reservations()), (), label)
        finally:
            conn_new.close()
            conn_old.close()
            for db in (db_new, db_old):
                if os.path.exists(db):
                    os.remove(db)


if __name__ == "__main__":
    unittest.main()
