"""Iteration 16 integration tests — qmt-execution-core 0.4.1 / a68572d.

Authoritative plan: ``work/gates/QMT_EXECUTION_CORE/
CORE_0_4_TGRID_INTEGRATION_PLAN_20260816.md`` (Core 0.4 baseline) and the
final integration task ``work/control/CURRENT_TASK.md`` (Core 0.4.1 Runtime
Authority, independent audit PASS_PRELIVE).

Coverage (fake XtQuant / fake BrokerPort ONLY — zero QMT order/cancel calls):

* 9.1  three independent TGrid/Core stacks share one account-level
       coordination DB; A/B/C on distinct symbols are WORKING concurrently,
       session ids are distinct, closing one stack does not close another;
* 9.2  same-account/same-symbol second writer is rejected BEFORE the broker
       (broker submit count 0, no TGrid business intent), while another
       symbol on the same account stays WORKING;
* 9.3  deterministic shared-cash race: account-level active reservations can
       never exceed fresh broker cash (100); the second BUY is rejected
       before the broker;
* 9.4  UNKNOWN -> recovery failure -> FAILED / QUARANTINED: symbol claim
       stays held, Core cash reservation stays held, the TGrid business
       ledger stays pending (no release/terminal permission), no blind
       resend, another symbol on the same account may still proceed;
* 9.5  account isolation: same symbol on two distinct account bindings may
       both proceed; coordination state does not cross-contaminate;
* §8   bounded MiniQMT session-id leasing: distinct ids on the same qmt
       path, close isolation, exact collision fails closed, same-name
       bounded fallback;
* P1-5 old hash-bound (0.3.1-style) journal is REJECTED by the 0.4 build,
       never silently migrated; explicit archive -> new build succeeds;
* P1-4 table-driven Core state/finality -> TGrid business-terminality +
       sidecar-ordering proof (Core coordination COMMIT -> TGrid sidecar
       COMMIT -> broker submit).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from qmt_execution_core.coordination import (
    ConservativeCashRequirementEstimator,
    SQLiteExecutionCoordinator,
    account_key_from_binding_identity,
)
from qmt_execution_core.domain import (
    BrokerAsset,
    BrokerOrder,
    BrokerOrderStatus,
    CancelRequestResult,
    ExecutionRequest,
    Side,
    TradeState,
)
from qmt_execution_core.exceptions import (
    BrokerQueryAmbiguous,
    CoordinationIdentityError,
    RuntimeConfigurationError,
    SessionIdUnavailable,
)
from qmt_execution_core.finality import ExecutionFinality, execution_finality
from qmt_execution_core.miniqmt.binding import QmtAccountBinding
from qmt_execution_core.miniqmt.runtime import MiniQmtRuntime, MiniQmtRuntimeConfig
from qmt_execution_core import AccountRuntimeAuthority

from tgrid.execution.executor import ExecutionEngine
from tgrid.execution.models import BUY, OrderStatus
from tgrid.execution.store import ExecutionStore
from tgrid.integrations.daily_exposure import DailyExposureLedger
from tgrid.integrations.live_broker_adapter import LiveBrokerPolicy
from tgrid.integrations.qec_adapter import (
    TGridEvidenceSource,
    TGridExecutionGuard,
    TGridSidecar,
    apply_snapshot,
    make_execution_request,
    snapshot_is_tgrid_terminal,
)
from tgrid.integrations.qec_runtime import (
    QecRuntimeError,
    TGridQecStack,
    build_qec_runtime,
    build_tgrid_qec_stack,
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
    """Per-runtime fake XtQuant trader with configurable asset cash."""

    def __init__(self, *, cash=100000.0, account_id="A123"):
        self.account_id = account_id
        self.account_type = 2
        self.account_status = 0
        self.connect_result = 0
        self.subscribe_result = 0
        self.unsubscribe_result = 0
        self.place_calls = 0
        self.order = None
        self.cancel_result = 0
        self.callback = None
        self.cash = cash

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
        self.order.stock_code = symbol
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
        return SimpleNamespace(
            cash=self.cash, frozen_cash=0.0, market_value=0.0, total_asset=self.cash,
        )

    def query_stock_positions(self, account):
        return [SimpleNamespace(
            stock_code="510300.SH", volume=1000, can_use_volume=900,
            frozen_volume=100, market_value=4700.0, avg_price=4.5,
        )]

    def query_stock_trades(self, account):
        return []


class _ScriptBroker:
    """qec BrokerPort fake with scriptable submit/query/cancel behavior."""

    def __init__(self):
        self.orders = {}
        self.next_id = 9000
        self.place_calls = 0
        self.cancel_calls = 0
        self.healthy = True
        self.query_raise = False

    def execution_healthy(self):
        return self.healthy

    def place_order(self, request):
        self.place_calls += 1
        self.next_id += 1
        oid = self.next_id
        self.orders[oid] = BrokerOrder(
            order_id=oid, symbol=request.symbol, side=request.side,
            qty=request.qty, filled_qty=0, status=BrokerOrderStatus.WORKING,
            order_remark=request.order_remark,
            client_order_id=request.client_order_id,
        )
        return oid

    def cancel_order(self, order_id):
        self.cancel_calls += 1
        self._set_status(order_id, BrokerOrderStatus.CANCEL_PENDING)
        return CancelRequestResult.ACCEPTED

    def query_order(self, order_id):
        if self.query_raise:
            raise BrokerQueryAmbiguous("authoritative broker query failed")
        return self.orders[order_id]

    def query_orders(self):
        return tuple(self.orders.values())

    def _set_status(self, order_id, status, filled=None, price=None):
        current = self.orders[order_id]
        self.orders[order_id] = BrokerOrder(
            order_id=current.order_id, symbol=current.symbol,
            side=current.side, qty=current.qty,
            filled_qty=current.filled_qty if filled is None else filled,
            status=status, order_remark=current.order_remark,
            client_order_id=current.client_order_id,
            average_fill_price=price,
        )


class _RecordingCoordinator:
    """Delegating ExecutionCoordinator that records call order."""

    def __init__(self, inner, events=None):
        self.inner = inner
        self.events = events if events is not None else []

    def prepare(self, **kwargs):
        self.events.append(("coordinate", kwargs["request"].client_order_id))
        return self.inner.prepare(**kwargs)

    def restore(self, **kwargs):
        return self.inner.restore(**kwargs)

    def update_finality(self, **kwargs):
        return self.inner.update_finality(**kwargs)

    def has_claim(self, **kwargs):
        return self.inner.has_claim(**kwargs)


class _RecordingBroker(_ScriptBroker):
    def __init__(self, events=None):
        super().__init__()
        self.events = events if events is not None else []

    def place_order(self, request):
        self.events.append(("broker", request.client_order_id))
        return super().place_order(request)


class _DictStore:
    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value):
        self._data[key] = value


def _now() -> str:
    return "2026-08-16T14:00:00"


def _temp_db_path() -> str:
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    return handle.name


def _zero_estimator() -> ConservativeCashRequirementEstimator:
    return ConservativeCashRequirementEstimator(fee_rate=0.0, minimum_fee=0.0)


def _policy(*symbols) -> LiveBrokerPolicy:
    return LiveBrokerPolicy(
        allowlist=frozenset(symbols),
        max_order_qty=100000,
        max_cash_per_order=100000000.0,
        max_cash_per_day=100000000.0,
    )


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


def _binding(tmp: str, account_id: str) -> str:
    qmt = os.path.join(tmp, "qmt")
    os.makedirs(qmt, exist_ok=True)
    binding = QmtAccountBinding.create(
        environment="simulation", account_type=2, account_id=account_id,
        qmt_path=qmt,
    )
    path = os.path.join(tmp, "binding-%s.json" % account_id)
    binding.write(path)
    return path


def _account_key(binding_path: str) -> str:
    import json

    payload = json.loads(open(binding_path, encoding="utf-8").read())
    return account_key_from_binding_identity(
        environment=str(payload["environment"]),
        account_type=int(payload["account_type"]),
        account_id_sha256=str(payload["account_id_sha256"]),
    )


class _Stack:
    def __init__(self, stack, traders, store, conn, db_path):
        self.stack = stack
        self.traders = traders
        self.store = store
        self.conn = conn
        self.db_path = db_path

    @property
    def trader(self):
        return self.traders[-1]

    def close(self):
        try:
            self.stack.close()
        finally:
            try:
                self.conn.close()
            finally:
                if os.path.exists(self.db_path):
                    os.remove(self.db_path)


def _make_stack(
    tmp: str,
    *,
    strategy_name: str,
    symbol: str,
    binding_path: str,
    authority_root,
    cash: float = 100000.0,
    estimator=None,
    runtime_lock_mode: str = "shared",
    account_id: str = "A123",
    path_suffix: str | None = None,
    bootstrap: bool = True,
) -> _Stack:
    """Test-only composition with an INJECTED Authority root.

    Production ``build_tgrid_qec_stack`` resolves Core's OS-derived canonical
    Runtime Authority (no injection).  Tests use this helper to isolate the
    Authority root under ``tmp`` — the low-level ``connect(authority=...)``
    seam is exercised ONLY here (clearly isolated test code), never in the
    production builder.
    """
    import json

    suffix = path_suffix if path_suffix is not None else strategy_name
    db_path = os.path.join(tmp, "db-%s.db" % suffix)
    conn = initialize(db_path)
    store = ExecutionStore(conn)
    exposure = DailyExposureLedger(trade_date="2026-08-16", store=_DictStore())
    traders = []

    def factory(path, sid):
        trader = FakeTrader(cash=cash, account_id=account_id)
        traders.append(trader)
        return trader

    evidence = _evidence()
    guard = TGridExecutionGuard(
        policy=_policy(symbol),
        environment_verified=evidence.environment_verified,
        account_verified=evidence.account_verified,
        broker_snapshot_verified=evidence.broker_snapshot_verified,
        position_verified=evidence.position_verified,
        cash_verified=evidence.cash_verified,
        quote_verified=evidence.quote_verified,
        kill_switch_active=evidence.kill_switch_active,
        exposure_ready=evidence.exposure_ready,
        exposure_used=evidence.exposure_used,
    )
    sidecar = TGridSidecar(
        store=store, exposure=exposure, strategy_name=strategy_name, now=_now,
    )
    config = MiniQmtRuntimeConfig(
        environment="simulation",
        qmt_path=os.path.join(tmp, "qmt"),
        binding_path=binding_path,
        journal_path=os.path.join(tmp, "j-%s.json" % suffix),
        lock_path=os.path.join(tmp, "e-%s.lock" % suffix),
        strategy_name=strategy_name,
        runtime_lock_mode=runtime_lock_mode,
        query_delay_seconds=0,
    )
    store_auth = AccountRuntimeAuthority(Path(authority_root))
    if runtime_lock_mode == "shared" and bootstrap:
        payload = json.loads(open(binding_path, encoding="utf-8").read())
        store_auth.resolve(
            account_key=account_key_from_binding_identity(
                environment=str(payload["environment"]),
                account_type=int(payload["account_type"]),
                account_id_sha256=str(payload["account_id_sha256"]),
            ),
            environment=str(payload["environment"]),
            account_type=int(payload["account_type"]),
            account_id_sha256=str(payload["account_id_sha256"]),
            coordination_db_path=None,
            bootstrap=True,
        )
    runtime = MiniQmtRuntime.connect(
        config,
        guard=guard,
        trader_factory=factory,
        stock_account_factory=lambda aid: SimpleNamespace(account_id=aid),
        xtconstant=XtConstant,
        callback_base=object,
        before_broker_submit=sidecar.before_broker_submit,
        before_broker_cancel=sidecar.before_broker_cancel,
        cash_estimator=estimator if estimator is not None else _zero_estimator(),
        authority=store_auth if runtime_lock_mode == "shared" else None,
    )
    engine = ExecutionEngine(store, session=runtime.session, strategy_name=strategy_name)
    return _Stack(TGridQecStack(runtime=runtime, engine=engine), traders, store, conn, db_path)


def _submit(stack: _Stack, key: str, symbol: str, side, qty: int, price: float):
    request = ExecutionRequest(
        client_order_id=key, symbol=symbol, side=side, qty=qty,
        limit_price=price, strategy_id=stack.stack.runtime.config.strategy_name,
        order_remark=key,
    )
    return stack.stack.runtime.submit(request)


class TestBuilderFailClosed(unittest.TestCase):
    """Production builder exposes no DB/root override and fails closed."""

    def _paths(self):
        tmp = tempfile.mkdtemp()
        return tmp, _binding(tmp, "A123")

    def test_production_builder_has_no_db_or_root_override(self):
        # P1-2 / P1-3 acceptance 1: the production builder must not expose any
        # strategy DB path, authority root, or coordinator/authority injection.
        import inspect

        stack_sig = inspect.signature(build_tgrid_qec_stack)
        runtime_sig = inspect.signature(build_qec_runtime)
        for param in ("coordination_path", "authority_root", "coordinator", "authority"):
            self.assertNotIn(param, stack_sig.parameters)
            self.assertNotIn(param, runtime_sig.parameters)

    def test_shared_without_cash_estimator_refused(self):
        tmp, binding_path = self._paths()
        db_path = _temp_db_path()
        conn = initialize(db_path)
        try:
            with self.assertRaises(QecRuntimeError):
                build_tgrid_qec_stack(
                    environment="simulation",
                    qmt_path=os.path.join(tmp, "qmt"),
                    binding_path=binding_path,
                    journal_path=os.path.join(tmp, "j.json"),
                    lock_path=os.path.join(tmp, "e.lock"),
                    strategy_name="TG-A", trade_date="2026-08-16",
                    store=ExecutionStore(conn),
                    exposure=DailyExposureLedger(trade_date="2026-08-16"),
                    policy=_policy("510300.SH"), now=_now,
                    evidence=_evidence(),
                    trader_factory=lambda p, s: FakeTrader(),
                    stock_account_factory=lambda aid: SimpleNamespace(account_id=aid),
                    xtconstant=XtConstant, callback_base=object,
                    runtime_lock_mode="shared",
                    cash_estimator=None,
                )
        finally:
            conn.close()
            os.remove(db_path)

    def test_exclusive_mode_still_available(self):
        tmp, binding_path = self._paths()
        stack = _make_stack(
            tmp, strategy_name="TG-X", symbol="510300.SH",
            binding_path=binding_path, authority_root=os.path.join(tmp, "auth"),
            runtime_lock_mode="exclusive",
        )
        try:
            self.assertIsNone(stack.stack.runtime.session_id_lease)
            self.assertIsNotNone(stack.stack.runtime.runtime_mutex)
            # Exclusive mode does not require coordination config.
            from qmt_execution_core.session import ExecutionSession

            self.assertIsInstance(stack.stack.runtime.session, ExecutionSession)
        finally:
            stack.close()


class TestThreeRuntimeConcurrency(unittest.TestCase):
    """9.1: three independent stacks, distinct symbols, all WORKING together."""

    def test_three_stacks_three_symbols_concurrent(self):
        tmp = tempfile.mkdtemp()
        binding_path = _binding(tmp, "A123")
        authority_root = os.path.join(tmp, "authority")
        stacks = [
            _make_stack(
                tmp, strategy_name="TG-A", symbol="510300.SH",
                binding_path=binding_path, authority_root=authority_root,
            ),
            _make_stack(
                tmp, strategy_name="TG-B", symbol="510600.SH",
                binding_path=binding_path, authority_root=authority_root,
            ),
            _make_stack(
                tmp, strategy_name="TG-C", symbol="510900.SH",
                binding_path=binding_path, authority_root=authority_root,
            ),
        ]
        try:
            # One runtime-owned execution-session authority per stack, shared mode.
            for s in stacks:
                self.assertIs(s.stack.engine.session, s.stack.runtime.session)
                self.assertIsNone(s.stack.runtime.runtime_mutex)
                self.assertIsNotNone(s.stack.runtime.session_id_lease)
            session_ids = [s.stack.runtime.session_id for s in stacks]
            self.assertEqual(len(set(session_ids)), 3, session_ids)

            symbols = ["510300.SH", "510600.SH", "510900.SH"]
            snaps = [
                _submit(s, "K-%s" % i, symbols[i], Side.BUY, 100, 4.7)
                for i, s in enumerate(stacks)
            ]
            for snap in snaps:
                self.assertEqual(snap.state, TradeState.WORKING)
            # All three broker fakes saw exactly one submit; none blocked.
            for s in stacks:
                self.assertEqual(s.trader.place_calls, 1)

            coordinator = stacks[0].stack.runtime.session.coordinator
            account_key = _account_key(binding_path)
            for symbol in symbols:
                claim = coordinator.get_claim(account_key, symbol)
                self.assertIsNotNone(claim, symbol)
                self.assertEqual(claim.finality, ExecutionFinality.OPEN)
            self.assertAlmostEqual(coordinator.active_reserved_cash(account_key), 470.0 * 3)

            # Closing one stack does not close/corrupt the others.
            stacks[0].stack.close()
            self.assertTrue(stacks[0].stack.runtime._closed)
            self.assertFalse(stacks[1].stack.runtime._closed)
            self.assertFalse(stacks[2].stack.runtime._closed)
            polled = stacks[1].stack.runtime.poll()
            self.assertEqual(polled.state, TradeState.WORKING)
        finally:
            for s in stacks:
                s.close()


class TestSameSymbolExclusion(unittest.TestCase):
    """9.2: same account/symbol second writer rejected before the broker."""

    def test_same_symbol_second_writer_rejected_before_broker(self):
        tmp = tempfile.mkdtemp()
        binding_path = _binding(tmp, "A123")
        authority_root = os.path.join(tmp, "authority")
        stack_a = _make_stack(
            tmp, strategy_name="TG-A", symbol="510300.SH",
            binding_path=binding_path, authority_root=authority_root,
        )
        stack_b = _make_stack(
            tmp, strategy_name="TG-B", symbol="510300.SH",
            binding_path=binding_path, authority_root=authority_root,
        )
        stack_c = _make_stack(
            tmp, strategy_name="TG-C", symbol="510600.SH",
            binding_path=binding_path, authority_root=authority_root,
        )
        try:
            snap = _submit(stack_a, "K-A", "510300.SH", Side.BUY, 100, 4.7)
            self.assertEqual(snap.state, TradeState.WORKING)
            self.assertEqual(stack_a.trader.place_calls, 1)

            # Second writer on the SAME account/symbol: rejected before broker.
            rejected = _submit(stack_b, "K-B", "510300.SH", Side.BUY, 100, 4.7)
            self.assertEqual(rejected.state, TradeState.REJECTED)
            self.assertEqual(stack_b.trader.place_calls, 0)
            self.assertIn("symbol", rejected.reason.lower() or "")
            # TGrid business ledger was never touched (no sidecar commit).
            with self.assertRaises(Exception):
                stack_b.store.get_intent("K-B")

            # Engine-level contract: REJECTED result, broker submit count 0.
            result = stack_b.stack.engine.send_buy(
                client_order_key="K-B2", symbol="510300.SH", qty=100,
                limit_price=4.7, order_remark="K-B2", now=_now(),
                expected_available_cash=100000.0, reserved_cash=470.0,
            )
            self.assertEqual(result.status, OrderStatus.REJECTED)
            self.assertEqual(stack_b.trader.place_calls, 0)

            # Another symbol on the SAME account is NOT globally blocked.
            snap_c = _submit(stack_c, "K-C", "510600.SH", Side.BUY, 100, 4.7)
            self.assertEqual(snap_c.state, TradeState.WORKING)
            self.assertEqual(stack_c.trader.place_calls, 1)

            coordinator = stack_a.stack.runtime.session.coordinator
            account_key = _account_key(binding_path)
            self.assertIsNotNone(coordinator.get_claim(account_key, "510300.SH"))
            self.assertIsNotNone(coordinator.get_claim(account_key, "510600.SH"))
        finally:
            stack_a.close()
            stack_b.close()
            stack_c.close()


class TestSharedCashRace(unittest.TestCase):
    """9.3: account-level reservations cannot overcommit fresh broker cash."""

    def test_shared_cash_cannot_overcommit(self):
        tmp = tempfile.mkdtemp()
        binding_path = _binding(tmp, "A123")
        authority_root = os.path.join(tmp, "authority")
        # Deterministic fresh broker cash = 100 for BOTH stacks.
        stack_p0 = _make_stack(
            tmp, strategy_name="TG-P0", symbol="510300.SH",
            binding_path=binding_path, authority_root=authority_root,
            cash=100.0, estimator=_zero_estimator(),
        )
        stack_p1 = _make_stack(
            tmp, strategy_name="TG-P1", symbol="510600.SH",
            binding_path=binding_path, authority_root=authority_root,
            cash=100.0, estimator=_zero_estimator(),
        )
        try:
            account_key = _account_key(binding_path)
            coordinator = stack_p0.stack.runtime.session.coordinator

            # P0 reserves 60 (qty 60 @ 1.0); effective = 100 - 0 >= 60 -> OK.
            snap0 = _submit(stack_p0, "K-P0", "510300.SH", Side.BUY, 60, 1.0)
            self.assertEqual(snap0.state, TradeState.WORKING)
            self.assertEqual(stack_p0.trader.place_calls, 1)
            self.assertAlmostEqual(coordinator.active_reserved_cash(account_key), 60.0)
            # P1 needs 50 but only 40 remain -> rejected BEFORE the broker.
            snap1 = _submit(stack_p1, "K-P1", "510600.SH", Side.BUY, 50, 1.0)
            self.assertEqual(snap1.state, TradeState.REJECTED)
            self.assertEqual(stack_p1.trader.place_calls, 0)
            self.assertIn("cash", snap1.reason.lower() or "")
            self.assertAlmostEqual(coordinator.active_reserved_cash(account_key), 60.0)
            # No TGrid business intent for the rejected BUY (sidecar never ran).
            with self.assertRaises(Exception):
                stack_p1.store.get_intent("K-P1")

            # P1 with a smaller BUY that fits (40) succeeds (new cycle).
            stack_p1.stack.runtime.next_cycle()
            snap2 = _submit(stack_p1, "K-P2", "510600.SH", Side.BUY, 40, 1.0)
            self.assertEqual(snap2.state, TradeState.WORKING)
            self.assertAlmostEqual(coordinator.active_reserved_cash(account_key), 100.0)
        finally:
            stack_p0.close()
            stack_p1.close()


class TestQuarantineIsolation(unittest.TestCase):
    """9.4: UNKNOWN -> recovery failure -> FAILED/QUARANTINED isolation."""

    def _session(
        self, tmp, *, coordinator, account_key, execution_id, broker,
        store, symbol_allowlist=("510300.SH", "510600.SH"),
    ):
        sidecar = TGridSidecar(
            store=store, exposure=DailyExposureLedger(trade_date="2026-08-16"),
            strategy_name=execution_id, now=_now,
        )
        guard = TGridExecutionGuard(
            policy=_policy(*symbol_allowlist),
            environment_verified=lambda: True, account_verified=lambda: True,
            broker_snapshot_verified=lambda: True, position_verified=lambda: True,
            cash_verified=lambda: True, quote_verified=lambda: True,
            kill_switch_active=lambda: False, exposure_ready=lambda: True,
            exposure_used=lambda: 0.0,
        )
        from qmt_execution_core.coordinated_session import CoordinatedExecutionSession

        session = CoordinatedExecutionSession(
            broker=broker,
            guard=guard,
            journal_path=os.path.join(tmp, "j-%s.json" % execution_id),
            lock_path=os.path.join(tmp, "e-%s.lock" % execution_id),
            coordinator=coordinator,
            account_key=account_key,
            account_resource=_FakeAccountResource(cash=100000.0),
            cash_estimator=_zero_estimator(),
            execution_id=execution_id,
            before_broker_submit=sidecar.before_broker_submit,
            before_broker_cancel=sidecar.before_broker_cancel,
        )
        session.open()
        return session, sidecar

    def test_quarantined_claim_cash_and_ledger_stay_held(self):
        tmp = tempfile.mkdtemp()
        binding_path = _binding(tmp, "A123")
        account_key = _account_key(binding_path)
        authority_root = os.path.join(tmp, "authority")
        coordinator = SQLiteExecutionCoordinator(os.path.join(tmp, "quarantine-coord.db"))

        store_a = ExecutionStore(initialize(_temp_db_path()))
        broker_a = _ScriptBroker()
        session_a, sidecar_a = self._session(
            tmp, coordinator=coordinator, account_key=account_key,
            execution_id="TG-A", broker=broker_a, store=store_a,
        )
        try:
            snap = session_a.submit(make_execution_request(
                client_order_key="K-A", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.7, strategy_name="TG-A", order_remark="K-A",
            ))
            self.assertEqual(snap.state, TradeState.WORKING)
            self.assertEqual(broker_a.place_calls, 1)
            oid = snap.broker_order_id
            apply_snapshot(store_a, snap, client_order_key="K-A", now=_now(),
                           finality=execution_finality(session_a.machine))

            # Ambiguous observation -> UNKNOWN (recoverable, claim held).
            broker_a._set_status(oid, BrokerOrderStatus.UNKNOWN)
            snap = session_a.poll()
            self.assertEqual(snap.state, TradeState.UNKNOWN)
            claim = coordinator.get_claim(account_key, "510300.SH")
            self.assertEqual(claim.finality, ExecutionFinality.OPEN)
            self.assertAlmostEqual(coordinator.active_reserved_cash(account_key), 470.0)

            # Authoritative recovery fails -> FAILED with unresolved order ->
            # Core finality QUARANTINED.
            broker_a.query_raise = True
            snap = session_a.reconcile()
            self.assertEqual(snap.state, TradeState.FAILED)
            finality = execution_finality(session_a.machine)
            self.assertIs(finality, ExecutionFinality.QUARANTINED)
            self.assertEqual(broker_a.place_calls, 1)  # no blind resend

            # Core claim + reservation stay held for the quarantined execution.
            claim = coordinator.get_claim(account_key, "510300.SH")
            self.assertEqual(claim.finality, ExecutionFinality.QUARANTINED)
            self.assertAlmostEqual(coordinator.active_reserved_cash(account_key), 470.0)

            # TGrid business ledger stays PENDING; reservation NOT released.
            apply_snapshot(store_a, snap, client_order_key="K-A", now=_now(),
                           finality=finality)
            intent = store_a.get_intent("K-A")
            self.assertEqual(intent.status, OrderStatus.SUBMITTED)
            reservations = tuple(store_a.list_active_reservations())
            self.assertEqual(len(reservations), 1)

            # Engine over the quarantined session folds FAILED/QUARANTINED
            # without terminalizing (poll short-circuits via snapshot()).
            engine = ExecutionEngine(store_a, session=session_a,
                                     strategy_name="TG-A")
            try:
                result = engine.poll_order("K-A", now=_now())
                self.assertEqual(result.status, OrderStatus.SUBMITTED)
            finally:
                engine.close()

            # Another strategy on a DIFFERENT symbol can proceed on the same
            # account (shared cash still permits).
            store_b = ExecutionStore(initialize(_temp_db_path()))
            broker_b = _ScriptBroker()
            session_b, _ = self._session(
                tmp, coordinator=coordinator, account_key=account_key,
                execution_id="TG-B", broker=broker_b, store=store_b,
            )
            try:
                snap_b = session_b.submit(make_execution_request(
                    client_order_key="K-B", symbol="510600.SH", side=BUY, qty=10,
                    limit_price=4.7, strategy_name="TG-B", order_remark="K-B",
                ))
                self.assertEqual(snap_b.state, TradeState.WORKING)
                self.assertEqual(broker_b.place_calls, 1)
            finally:
                session_b.close()

            # The quarantined symbol stays BLOCKED for a THIRD execution.
            store_c = ExecutionStore(initialize(_temp_db_path()))
            broker_c = _ScriptBroker()
            session_c, _ = self._session(
                tmp, coordinator=coordinator, account_key=account_key,
                execution_id="TG-C", broker=broker_c, store=store_c,
            )
            try:
                snap_c = session_c.submit(make_execution_request(
                    client_order_key="K-C", symbol="510300.SH", side=BUY, qty=10,
                    limit_price=4.7, strategy_name="TG-C", order_remark="K-C",
                ))
                self.assertEqual(snap_c.state, TradeState.REJECTED)
                self.assertEqual(broker_c.place_calls, 0)
            finally:
                session_c.close()
        finally:
            session_a.close()


class _FakeAccountResource:
    def __init__(self, cash=100000.0):
        self.cash = cash

    def query_asset(self):
        return BrokerAsset(
            cash=self.cash, frozen_cash=0.0, market_value=0.0, total_asset=self.cash,
        )


class TestAccountIsolation(unittest.TestCase):
    """9.5: same symbol on two distinct accounts proceeds independently."""

    def test_same_symbol_different_accounts_both_working(self):
        tmp = tempfile.mkdtemp()
        binding_a = _binding(tmp, "A1")
        binding_b = _binding(tmp, "A2")
        authority_root = os.path.join(tmp, "authority")
        stack_a = _make_stack(
            tmp, strategy_name="TG-A1", symbol="510300.SH",
            binding_path=binding_a, authority_root=authority_root,
            account_id="A1",
        )
        stack_b = _make_stack(
            tmp, strategy_name="TG-A2", symbol="510300.SH",
            binding_path=binding_b, authority_root=authority_root,
            account_id="A2",
        )
        try:
            key_a = _account_key(binding_a)
            key_b = _account_key(binding_b)
            self.assertNotEqual(key_a, key_b)

            snap_a = _submit(stack_a, "K-A", "510300.SH", Side.BUY, 100, 4.7)
            snap_b = _submit(stack_b, "K-B", "510300.SH", Side.BUY, 100, 4.7)
            self.assertEqual(snap_a.state, TradeState.WORKING)
            self.assertEqual(snap_b.state, TradeState.WORKING)
            self.assertEqual(stack_a.trader.place_calls, 1)
            self.assertEqual(stack_b.trader.place_calls, 1)

            # Coordination state is scoped per account_key: both claims exist
            # in the two DIFFERENT per-account Authority-certified DBs.
            coordinator_a = stack_a.stack.runtime.session.coordinator
            coordinator_b = stack_b.stack.runtime.session.coordinator
            self.assertIsNotNone(coordinator_a.get_claim(key_a, "510300.SH"))
            self.assertIsNotNone(coordinator_b.get_claim(key_b, "510300.SH"))
            self.assertAlmostEqual(coordinator_a.active_reserved_cash(key_a), 470.0)
            self.assertAlmostEqual(coordinator_b.active_reserved_cash(key_b), 470.0)
        finally:
            stack_a.close()
            stack_b.close()


class TestSessionIdLeasing(unittest.TestCase):
    """Plan §8: bounded MiniQMT session-id leasing with fake XtQuant."""

    def test_two_shared_runtimes_same_qmt_path_distinct_session_ids(self):
        tmp = tempfile.mkdtemp()
        binding_path = _binding(tmp, "A123")
        authority_root = os.path.join(tmp, "authority")
        stack_a = _make_stack(
            tmp, strategy_name="TG-S1", symbol="510300.SH",
            binding_path=binding_path, authority_root=authority_root,
        )
        stack_b = _make_stack(
            tmp, strategy_name="TG-S2", symbol="510600.SH",
            binding_path=binding_path, authority_root=authority_root,
        )
        try:
            self.assertNotEqual(
                stack_a.stack.runtime.session_id, stack_b.stack.runtime.session_id
            )
            # Closing one runtime releases only its own lease; the other works.
            stack_a.stack.close()
            self.assertFalse(stack_b.stack.runtime._closed)
            snap = _submit(stack_b, "K-B", "510600.SH", Side.BUY, 100, 4.7)
            self.assertEqual(snap.state, TradeState.WORKING)
            self.assertEqual(stack_b.trader.place_calls, 1)
        finally:
            stack_b.close()

    def test_exact_session_id_collision_fails_closed(self):
        from qmt_execution_core.miniqmt.runtime import (
            MiniQmtRuntime,
            MiniQmtRuntimeConfig,
        )

        tmp = tempfile.mkdtemp()
        qmt = os.path.join(tmp, "qmt")
        os.makedirs(qmt, exist_ok=True)
        binding = QmtAccountBinding.create(
            environment="simulation", account_type=2, account_id="A123",
            qmt_path=qmt,
        )
        binding_path = os.path.join(tmp, "binding.json")
        binding.write(binding_path)
        coordinator = SQLiteExecutionCoordinator(os.path.join(tmp, "collision-coord.db"))
        traders = []

        def factory(path, sid):
            trader = FakeTrader()
            traders.append(trader)
            return trader

        def connect_once():
            config = MiniQmtRuntimeConfig(
                environment="simulation", qmt_path=qmt, binding_path=binding_path,
                journal_path=os.path.join(tmp, "j.json"),
                lock_path=os.path.join(tmp, "e.lock"),
                strategy_name="TG-COLLIDE",
                runtime_lock_mode="shared",
                session_id=100_000_007,
            )
            return MiniQmtRuntime.connect(
                config, guard=_permissive_guard(),
                trader_factory=factory,
                stock_account_factory=lambda aid: SimpleNamespace(account_id=aid),
                xtconstant=XtConstant, callback_base=object,
                coordinator=coordinator,
                cash_estimator=_zero_estimator(),
            )

        first = connect_once()
        try:
            self.assertEqual(first.session_id, 100_000_007)
            with self.assertRaises(SessionIdUnavailable):
                connect_once()  # exact id already leased -> fails closed
        finally:
            first.close()

    def test_same_strategy_name_bounded_fallback(self):
        tmp = tempfile.mkdtemp()
        binding_path = _binding(tmp, "A123")
        authority_root = os.path.join(tmp, "authority")
        # Same strategy_name -> identical session-id candidate list; the
        # second runtime must fall back to the next bounded candidate (Core
        # behavior).  Distinct journal/lock paths keep the two runtimes
        # independent except for the session-id pool and coordination DB.
        stack_a = _make_stack(
            tmp, strategy_name="TG-SAME", symbol="510300.SH",
            binding_path=binding_path, authority_root=authority_root,
            path_suffix="a",
        )
        stack_b = _make_stack(
            tmp, strategy_name="TG-SAME", symbol="510600.SH",
            binding_path=binding_path, authority_root=authority_root,
            path_suffix="b",
        )
        try:
            self.assertNotEqual(
                stack_a.stack.runtime.session_id, stack_b.stack.runtime.session_id
            )
            self.assertGreaterEqual(len(stack_b.traders), 1)
        finally:
            stack_a.close()
            stack_b.close()


def _permissive_guard():
    from qmt_execution_core.domain import PrecheckEvidence, SessionEvidence

    class _Guard:
        def verify_session(self):
            return SessionEvidence(ready=True, environment_verified=True,
                                   account_verified=True)

        def verify(self, request):
            return PrecheckEvidence(
                allowed=True, environment_verified=True, account_verified=True,
                broker_snapshot_verified=True, position_verified=True,
                cash_verified=True, quote_verified=True,
            )

    return _Guard()


class TestJournalRejection(unittest.TestCase):
    """P1-5 / acceptance 10: old hash-bound journal is rejected, never migrated."""

    def _build_exclusive(self, tmp, binding_path, suffix):
        db_path = os.path.join(tmp, "db-%s.db" % suffix)
        conn = initialize(db_path)
        store = ExecutionStore(conn)
        exposure = DailyExposureLedger(trade_date="2026-08-16", store=_DictStore())
        runtime = build_qec_runtime(
            environment="simulation",
            qmt_path=os.path.join(tmp, "qmt"),
            binding_path=binding_path,
            journal_path=os.path.join(tmp, "j-%s.json" % suffix),
            lock_path=os.path.join(tmp, "e-%s.lock" % suffix),
            strategy_name="TG-J", trade_date="2026-08-16",
            store=store, exposure=exposure, policy=_policy("510300.SH"),
            now=_now, evidence=_evidence(),
            trader_factory=lambda p, s: FakeTrader(),
            stock_account_factory=lambda aid: SimpleNamespace(account_id=aid),
            xtconstant=XtConstant, callback_base=object,
            runtime_lock_mode="exclusive",
        )
        return runtime, conn, db_path

    def test_old_hash_bound_journal_rejected_then_archive_and_rebuild(self):
        tmp = tempfile.mkdtemp()
        binding_path = _binding(tmp, "A123")
        journal_path = os.path.join(tmp, "j-iter16.json")

        # First build through the PRODUCTION builder (exclusive mode — no
        # Authority needed) creates and binds a 0.4.1 journal.
        first, conn1, db1 = self._build_exclusive(tmp, binding_path, "iter16")
        first.close()
        conn1.close()
        self.assertTrue(os.path.exists(journal_path))

        # Simulate an older-core-bound journal by rewriting the
        # formal_verification hash binding (a deployment invariant that must
        # never be disabled or silently migrated).
        import json

        payload = json.loads(open(journal_path, encoding="utf-8").read())
        payload["data"]["formal_verification"] = {
            "transition_spec_sha256": "0" * 64,
            "execution_source_sha256": "0" * 64,
        }
        with open(journal_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

        # Rebuild on the SAME journal path must REJECT via the production
        # builder's fail-closed wrap (QecRuntimeError), never silently migrate.
        with self.assertRaises(QecRuntimeError) as ctx:
            self._build_exclusive(tmp, binding_path, "iter16")
        self.assertIn("journal", str(ctx.exception).lower())
        self.assertTrue(os.path.exists(journal_path))

        # Documented cutover: archive the old journal -> new 0.4.1 path.
        archived = journal_path + ".stale-20260816"
        os.rename(journal_path, archived)
        self.assertTrue(os.path.exists(archived))
        rebuilt, conn2, db2 = self._build_exclusive(tmp, binding_path, "iter16-new")
        try:
            self.assertIsNotNone(rebuilt.session)
        finally:
            rebuilt.close()
            conn2.close()


class TestFinalityTerminalityTable(unittest.TestCase):
    """P1-4: table-driven Core state/finality -> TGrid business-terminality."""

    def test_terminality_table(self):
        cases = [
            # (state, finality, expected_terminal)
            (TradeState.FILLED, ExecutionFinality.RESOLVED, True),
            (TradeState.CANCELLED, ExecutionFinality.RESOLVED, True),
            (TradeState.REJECTED, ExecutionFinality.RESOLVED, True),
            (TradeState.FAILED, ExecutionFinality.RESOLVED, True),
            (TradeState.FAILED, ExecutionFinality.QUARANTINED, False),
            (TradeState.UNKNOWN, ExecutionFinality.OPEN, False),
            (TradeState.CANCEL_REJECTED, ExecutionFinality.OPEN, False),
            (TradeState.WORKING, ExecutionFinality.OPEN, False),
            (TradeState.PARTIALLY_FILLED, ExecutionFinality.OPEN, False),
            (TradeState.PENDING_CANCEL, ExecutionFinality.OPEN, False),
        ]
        for state, finality, expected in cases:
            with self.subTest(state=state.value, finality=finality.value):
                self.assertEqual(
                    snapshot_is_tgrid_terminal(state, finality=finality), expected
                )

    def test_apply_snapshot_quarantined_keeps_pending_and_reservation(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            store = ExecutionStore(conn)
            sidecar = TGridSidecar(
                store=store, exposure=DailyExposureLedger(trade_date="2026-08-16"),
                strategy_name="TGRID", now=_now,
            )
            request = make_execution_request(
                client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.7, strategy_name="TGRID", order_remark="R1",
            )
            sidecar.before_broker_submit(request)
            store.update_intent_status(
                "K1", status=OrderStatus.SUBMITTED, updated_at=_now(),
                broker_order_id="9001",
            )

            # QUARANTINED FAILED: pending status preserved, reservation kept.
            snap = _snap(TradeState.FAILED, oid=9001)
            apply_snapshot(store, snap, client_order_key="K1", now=_now(),
                           finality=ExecutionFinality.QUARANTINED)
            self.assertEqual(store.get_intent("K1").status, OrderStatus.SUBMITTED)
            self.assertEqual(len(tuple(store.list_active_reservations())), 1)

            # RESOLVED FAILED: terminal UNKNOWN (recovery failure, proven).
            apply_snapshot(store, snap, client_order_key="K1", now=_now(),
                           finality=ExecutionFinality.RESOLVED)
            self.assertEqual(store.get_intent("K1").status, OrderStatus.UNKNOWN)

            # FILLED releases the business reservation (fresh key K2).
            request2 = make_execution_request(
                client_order_key="K2", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.7, strategy_name="TGRID", order_remark="R2",
            )
            sidecar.before_broker_submit(request2)
            apply_snapshot(store, _snap(TradeState.FILLED, oid=9002, filled=100,
                                        key="K2"),
                           client_order_key="K2", now=_now(),
                           finality=ExecutionFinality.RESOLVED)
            self.assertEqual(store.get_intent("K2").status, OrderStatus.FILLED)
            # K2's business reservation was released (K1's quarantined
            # reservation is intentionally retained — fail closed).
            active_k2 = [
                r for r in store.list_active_reservations()
                if r.client_order_key == "K2"
            ]
            self.assertEqual(active_k2, [])
        finally:
            conn.close()
            os.remove(path)


def _snap(state, oid=9001, filled=0, key="K1"):
    from qmt_execution_core.domain import ExecutionSnapshot

    return ExecutionSnapshot(state=state, client_order_id=key,
                             broker_order_id=oid, ordered_qty=100,
                             filled_qty=filled)


class TestCoordinatedSidecarOrdering(unittest.TestCase):
    """Plan §5: Core coordination COMMIT -> TGrid sidecar COMMIT -> broker."""

    def _session(self, tmp, *, coordinator, account_key, execution_id, broker,
                 store, events=None):
        sidecar = TGridSidecar(
            store=store, exposure=DailyExposureLedger(trade_date="2026-08-16"),
            strategy_name=execution_id, now=_now,
        )

        def before_submit(request):
            if events is not None:
                events.append(("sidecar", request.client_order_id))
            return sidecar.before_broker_submit(request)

        guard = TGridExecutionGuard(
            policy=_policy("510300.SH", "510600.SH"),
            environment_verified=lambda: True, account_verified=lambda: True,
            broker_snapshot_verified=lambda: True, position_verified=lambda: True,
            cash_verified=lambda: True, quote_verified=lambda: True,
            kill_switch_active=lambda: False, exposure_ready=lambda: True,
            exposure_used=lambda: 0.0,
        )
        from qmt_execution_core.coordinated_session import CoordinatedExecutionSession

        session = CoordinatedExecutionSession(
            broker=broker,
            guard=guard,
            journal_path=os.path.join(tmp, "j-%s.json" % execution_id),
            lock_path=os.path.join(tmp, "e-%s.lock" % execution_id),
            coordinator=coordinator,
            account_key=account_key,
            account_resource=_FakeAccountResource(cash=100000.0),
            cash_estimator=_zero_estimator(),
            execution_id=execution_id,
            before_broker_submit=before_submit,
            before_broker_cancel=sidecar.before_broker_cancel,
        )
        session.open()
        return session, sidecar

    def test_order_is_coordinate_then_sidecar_then_broker(self):
        tmp = tempfile.mkdtemp()
        binding_path = _binding(tmp, "A123")
        account_key = _account_key(binding_path)
        authority_root = os.path.join(tmp, "authority")
        inner = SQLiteExecutionCoordinator(os.path.join(tmp, "order-coord.db"))
        events = []
        coordinator = _RecordingCoordinator(inner, events)
        broker = _RecordingBroker(events)
        store = ExecutionStore(initialize(_temp_db_path()))
        session, _ = self._session(
            tmp, coordinator=coordinator, account_key=account_key,
            execution_id="TG-O", broker=broker, store=store, events=events,
        )
        try:
            snap = session.submit(make_execution_request(
                client_order_key="K-O", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.7, strategy_name="TG-O", order_remark="K-O",
            ))
            self.assertEqual(snap.state, TradeState.WORKING)
            # Exact ordering: Core coordination COMMIT -> TGrid sidecar
            # COMMIT -> broker submit (plan §5).
            self.assertEqual(events, [
                ("coordinate", "K-O"),
                ("sidecar", "K-O"),
                ("broker", "K-O"),
            ])
            # The TGrid sidecar created the business intent + reservation.
            self.assertEqual(store.get_intent("K-O").status, OrderStatus.NEW)
            self.assertEqual(len(tuple(store.list_active_reservations())), 1)
            # Folding the WORKING snapshot moves it to SUBMITTED.
            apply_snapshot(store, snap, client_order_key="K-O", now=_now(),
                           finality=execution_finality(session.machine))
            self.assertEqual(store.get_intent("K-O").status, OrderStatus.SUBMITTED)
        finally:
            session.close()

    def test_conflict_stops_at_coordination_before_sidecar_and_broker(self):
        tmp = tempfile.mkdtemp()
        binding_path = _binding(tmp, "A123")
        account_key = _account_key(binding_path)
        authority_root = os.path.join(tmp, "authority")
        inner = SQLiteExecutionCoordinator(os.path.join(tmp, "order-coord.db"))
        broker_a = _ScriptBroker()
        store_a = ExecutionStore(initialize(_temp_db_path()))
        session_a, _ = self._session(
            tmp, coordinator=inner, account_key=account_key,
            execution_id="TG-A", broker=broker_a, store=store_a,
        )
        events_b = []
        coordinator_b = _RecordingCoordinator(inner, events_b)
        broker_b = _RecordingBroker(events_b)
        store_b = ExecutionStore(initialize(_temp_db_path()))
        session_b, _ = self._session(
            tmp, coordinator=coordinator_b, account_key=account_key,
            execution_id="TG-B", broker=broker_b, store=store_b, events=events_b,
        )
        try:
            snap_a = session_a.submit(make_execution_request(
                client_order_key="K-A", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.7, strategy_name="TG-A", order_remark="K-A",
            ))
            self.assertEqual(snap_a.state, TradeState.WORKING)

            snap_b = session_b.submit(make_execution_request(
                client_order_key="K-B", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.7, strategy_name="TG-B", order_remark="K-B",
            ))
            self.assertEqual(snap_b.state, TradeState.REJECTED)
            # Coordination ran; the TGrid sidecar and the broker did NOT.
            self.assertEqual(events_b, [("coordinate", "K-B")])
            self.assertEqual(broker_b.place_calls, 0)
            with self.assertRaises(Exception):
                store_b.get_intent("K-B")  # no business intent was created
        finally:
            session_a.close()
            session_b.close()


class TestRuntimeAuthorityStartupMatrix(unittest.TestCase):
    """Final integration: missing/corrupt/replaced Authority fails closed."""

    def test_missing_authority_fails_closed_no_broker(self):
        # Acceptance 2: normal TGrid runtime MUST NOT bootstrap a missing
        # Authority; construction fails closed with no broker side effect.
        tmp = tempfile.mkdtemp()
        binding_path = _binding(tmp, "A123")
        authority_root = os.path.join(tmp, "authority")
        with self.assertRaises(RuntimeConfigurationError):
            _make_stack(
                tmp, strategy_name="TG-NOBOOT", symbol="510300.SH",
                binding_path=binding_path, authority_root=authority_root,
                bootstrap=False,
            )
        root = Path(authority_root)
        self.assertFalse(list(root.glob("*.authority.json")))
        self.assertFalse(list(root.glob("*.coordination.db")))

    def test_db_replaced_at_same_path_fails_closed_before_broker(self):
        # Acceptance 5: delete + recreate the certified DB at the same path ->
        # construction fails closed before any broker side effect.
        import json

        tmp = tempfile.mkdtemp()
        binding_path = _binding(tmp, "A123")
        authority_root = os.path.join(tmp, "authority")
        first = _make_stack(
            tmp, strategy_name="TG-R", symbol="510300.SH",
            binding_path=binding_path, authority_root=authority_root,
        )
        try:
            db_path = Path(first.stack.runtime.session.coordinator.path)
        finally:
            first.close()
        self.assertTrue(db_path.exists())
        db_path.unlink()
        import sqlite3

        sqlite3.connect(str(db_path)).close()  # recreate empty at same path
        with self.assertRaises(CoordinationIdentityError):
            _make_stack(
                tmp, strategy_name="TG-R2", symbol="510300.SH",
                binding_path=binding_path, authority_root=authority_root,
            )


if __name__ == "__main__":
    unittest.main()




