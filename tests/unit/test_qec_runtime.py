"""Cutover builder tests (migration Phase C): production-shaped qec runtime.

Builds ``MiniQmtRuntime`` through :func:`build_qec_runtime` with the TGrid
guard + sidecar and a fake XtQuant trader, and proves: the runtime is
order-capable only via the public core; the TGrid SQLite OrderIntent +
Reservation + daily exposure commit through the sidecar BEFORE the broker
side effect; snapshots fold back into the TGrid ledger; and zero TGrid-side
raw QMT call sites are involved (the broker adapter belongs to the public
core).
"""

import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from qmt_execution_core.domain import ExecutionRequest, Side
from qmt_execution_core.miniqmt.binding import QmtAccountBinding
from qmt_execution_core.miniqmt.runtime import MiniQmtRuntime

from tgrid.execution.models import BUY, OrderStatus
from tgrid.execution.store import ExecutionStore
from tgrid.integrations.daily_exposure import DailyExposureLedger
from tgrid.integrations.live_broker_adapter import LiveBrokerPolicy
from tgrid.integrations.qec_adapter import (
    TGridEvidenceSource,
    apply_snapshot,
)
from tgrid.integrations.qec_runtime import (
    QecRuntimeError,
    build_qec_runtime,
    default_cash_requirement_estimator,
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
    return "2026-08-16T11:00:00"


class TestBuildQecRuntime(unittest.TestCase):
    def _runtime(self, evidence=None):
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
        if evidence is None:

            def _ok():
                return True

            evidence = TGridEvidenceSource(
                environment_verified=_ok,
                account_verified=_ok,
                broker_snapshot_verified=_ok,
                position_verified=_ok,
                cash_verified=_ok,
                quote_verified=_ok,
                kill_switch_active=lambda: False,
                exposure_ready=_ok,
                exposure_used=lambda: 0.0,
            )
        runtime = build_qec_runtime(
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
            evidence=evidence,
            trader_factory=lambda path, sid: self.trader,
            stock_account_factory=lambda account_id: SimpleNamespace(account_id=account_id),
            xtconstant=XtConstant,
            callback_base=object,
            # Iteration 16: Core 0.4 shared account-level coordination.
            runtime_lock_mode="shared",
            coordination_path=os.path.join(self.tmp, "coordination.db"),
            cash_estimator=default_cash_requirement_estimator(),
        )
        return runtime

    def tearDown(self):
        try:
            self.runtime.close()
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass
        db_path = getattr(self, "db_path", None)
        if db_path and os.path.exists(db_path):
            os.remove(db_path)

    def test_runtime_is_order_capable_via_public_core_only(self):
        runtime = self._runtime()
        self.runtime = runtime
        self.assertIsInstance(runtime, MiniQmtRuntime)
        # Live gate OFF (simulation is ready without a live token, but the
        # stack never invokes a side effect without an explicit submit).
        request = ExecutionRequest(
            client_order_id="K1", symbol="510300.SH", side=Side.BUY, qty=100,
            limit_price=4.7, strategy_id="TGRID", order_remark="TG_510300SH_B001",
        )
        snap = runtime.submit(request)
        self.assertEqual(snap.state.value, "working")
        self.assertEqual(self.trader.place_calls, 1)
        # TGrid ledger committed through the sidecar before the broker call.
        intent = self.store.get_intent("K1")
        self.assertEqual(intent.status, OrderStatus.NEW)
        self.assertEqual(self.exposure.used, 470.0)
        reservations = tuple(self.store.list_active_reservations())
        self.assertEqual(len(reservations), 1)
        # Poll -> fold snapshot back into the TGrid ledger.
        self.trader.order.order_status = 56  # SUCCEEDED -> FILLED
        self.trader.order.filled_vol = 100
        self.trader.order.traded_volume = 100
        self.trader.order.traded_price = 4.69
        snap = runtime.poll()
        self.assertEqual(snap.state.value, "filled")
        apply_snapshot(self.store, snap, client_order_key="K1", now=_now())
        self.assertEqual(self.store.get_intent("K1").status, OrderStatus.FILLED)
        self.assertEqual(tuple(self.store.list_active_reservations()), ())

    def test_rejects_bad_environment(self):
        db = _temp_db_path()
        conn = initialize(db)
        try:
            with self.assertRaises(QecRuntimeError):
                build_qec_runtime(
                    environment="production",
                    qmt_path="x", binding_path="x", journal_path="x", lock_path="x",
                    strategy_name="TGRID", trade_date="2026-08-16",
                    store=ExecutionStore(conn),
                    exposure=DailyExposureLedger(trade_date="2026-08-16"),
                    policy=_policy(), now=_now,
                    evidence=TGridEvidenceSource(
                        environment_verified=lambda: True,
                        account_verified=lambda: True,
                        broker_snapshot_verified=lambda: True,
                        position_verified=lambda: True,
                        cash_verified=lambda: True,
                        quote_verified=lambda: True,
                        kill_switch_active=lambda: False,
                        exposure_ready=lambda: True,
                        exposure_used=lambda: 0.0,
                    ),
                )
        finally:
            conn.close()
            os.remove(db)

    def test_builder_refuses_missing_evidence_source(self):
        # P1-1: production construction fails closed without a live evidence
        # source (no self-certified defaults).
        db = _temp_db_path()
        conn = initialize(db)
        try:
            with self.assertRaises(QecRuntimeError):
                build_qec_runtime(
                    environment="simulation",
                    qmt_path="x", binding_path="x", journal_path="x", lock_path="x",
                    strategy_name="TGRID", trade_date="2026-08-16",
                    store=ExecutionStore(conn),
                    exposure=DailyExposureLedger(trade_date="2026-08-16"),
                    policy=_policy(), now=_now,
                    # evidence omitted -> must fail closed
                )
        finally:
            conn.close()
            os.remove(db)

    def test_evidence_false_blocks_submit_before_side_effects(self):
        # P1-1 negative: each critical false/unavailable evidence blocks the
        # order path BEFORE the TGrid sidecar / broker side effects.
        def _ok():
            return True

        # Session-level evidence: false -> the runtime session cannot even
        # open (fail closed at activation).
        for flag in ("environment_verified", "account_verified"):
            with self.subTest(flag=flag):
                kwargs = dict(
                    environment_verified=_ok, account_verified=_ok,
                    broker_snapshot_verified=_ok, position_verified=_ok,
                    cash_verified=_ok, quote_verified=_ok,
                    kill_switch_active=lambda: False, exposure_ready=_ok,
                    exposure_used=lambda: 0.0,
                )
                kwargs[flag] = lambda: False
                with self.assertRaises(Exception):
                    self._runtime(evidence=TGridEvidenceSource(**kwargs))

        # Precheck-level evidence: open succeeds, submit is rejected BEFORE
        # the sidecar persists anything and before any broker call.
        for flag in ("broker_snapshot_verified", "position_verified",
                     "cash_verified", "quote_verified", "exposure_ready"):
            with self.subTest(flag=flag):
                kwargs = dict(
                    environment_verified=_ok, account_verified=_ok,
                    broker_snapshot_verified=_ok, position_verified=_ok,
                    cash_verified=_ok, quote_verified=_ok,
                    kill_switch_active=lambda: False, exposure_ready=_ok,
                    exposure_used=lambda: 0.0,
                )
                kwargs[flag] = lambda: False
                runtime = self._runtime(evidence=TGridEvidenceSource(**kwargs))
                try:
                    request = ExecutionRequest(
                        client_order_id="K1", symbol="510300.SH", side=Side.BUY,
                        qty=100, limit_price=4.7, strategy_id="TGRID",
                        order_remark="TG_510300SH_B001",
                    )
                    snap = runtime.submit(request)
                    self.assertEqual(snap.state.value, "rejected", flag)
                    self.assertEqual(self.trader.place_calls, 0, flag)
                    with self.assertRaises(Exception):
                        self.store.get_intent("K1")  # sidecar never ran
                finally:
                    runtime.close()
                    self.conn.close()
                    if os.path.exists(self.db_path):
                        os.remove(self.db_path)

    def test_kill_switch_blocks_submit_before_side_effects(self):
        runtime = self._runtime(evidence=TGridEvidenceSource(
            environment_verified=lambda: True, account_verified=lambda: True,
            broker_snapshot_verified=lambda: True, position_verified=lambda: True,
            cash_verified=lambda: True, quote_verified=lambda: True,
            kill_switch_active=lambda: True, exposure_ready=lambda: True,
            exposure_used=lambda: 0.0,
        ))
        try:
            request = ExecutionRequest(
                client_order_id="K1", symbol="510300.SH", side=Side.BUY, qty=100,
                limit_price=4.7, strategy_id="TGRID", order_remark="TG_510300SH_B001",
            )
            snap = runtime.submit(request)
            self.assertEqual(snap.state.value, "rejected")
            self.assertEqual(self.trader.place_calls, 0)
            with self.assertRaises(Exception):
                self.store.get_intent("K1")
        finally:
            runtime.close()
            self.conn.close()
            if os.path.exists(self.db_path):
                os.remove(self.db_path)


if __name__ == "__main__":
    unittest.main()
