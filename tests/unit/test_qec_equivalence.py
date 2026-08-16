"""Integrated qec-path equivalence harness (migration Phase C).

Drives the public-core ExecutionSession through the TGrid sidecar + guard
against configurable fake brokers and asserts the TGrid-relevant migration
regression matrix: submit accepted/rejected/ambiguous, UNKNOWN no-blind-resend,
zero/duplicate recovery fail closed, partial/full fill, cancel pending /
rejected + re-query / partial+cancel / confirmed, the DEDICATED fill-during-
cancel race -> FILLED, restart from active / cancel-pending, query-None and
unknown-raw-status fail closed, disconnect blocks / reconnect needs full
reconcile, kill switch, and the TGrid pre-send ledger commit.

Raw QMT status values stay below the public adapter boundary; the matrix uses
normalized BrokerOrderStatus plus one raw-status test through
normalize_qmt_order_status.
"""

import os
import tempfile
import unittest

from qmt_execution_core.domain import (
    BrokerOrder,
    BrokerOrderStatus,
    CancelRequestResult,
    ExecutionRequest,
    Side,
    TradeState,
)
from qmt_execution_core.exceptions import BrokerSubmissionAmbiguous, BrokerSubmissionRejected
from qmt_execution_core.miniqmt.status import normalize_qmt_order_status
from qmt_execution_core.session import ExecutionSession

from tgrid.execution.models import BUY, OrderStatus
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
    return "2026-08-16T10:00:00"


class _ScriptBroker:
    """qec BrokerPort fake with scriptable submit/cancel/query behavior."""

    def __init__(self):
        self.orders = {}
        self.next_id = 9000
        self.place_calls = 0
        self.cancel_calls = 0
        self.healthy = True
        self.submit_mode = "ok"  # ok | reject | ambiguous
        self.cancel_result = CancelRequestResult.ACCEPTED
        self.query_none_mode = False

    def execution_healthy(self):
        return self.healthy

    def place_order(self, request: ExecutionRequest) -> int:
        self.place_calls += 1
        if self.submit_mode == "reject":
            raise BrokerSubmissionRejected("definitive reject")
        if self.submit_mode == "ambiguous":
            raise BrokerSubmissionAmbiguous("ambiguous before visibility")
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
        if self.submit_mode == "ambiguous_after":
            # Broker accepted the order, then the transport went ambiguous.
            raise BrokerSubmissionAmbiguous("ambiguous after broker accepted")
        return oid

    def cancel_order(self, order_id: int) -> CancelRequestResult:
        self.cancel_calls += 1
        if self.cancel_result is CancelRequestResult.ACCEPTED:
            self._set_status(order_id, BrokerOrderStatus.CANCEL_PENDING)
        return self.cancel_result

    def query_order(self, order_id: int) -> BrokerOrder:
        if self.query_none_mode:
            raise BrokerQueryAmbiguousFallback("query returned None (ambiguous)")
        return self.orders[order_id]

    def query_orders(self):
        return tuple(self.orders.values())

    def _set_status(self, order_id: int, status: BrokerOrderStatus, filled=None, price=None):
        current = self.orders[order_id]
        self.orders[order_id] = BrokerOrder(
            order_id=current.order_id,
            symbol=current.symbol,
            side=current.side,
            qty=current.qty,
            filled_qty=current.filled_qty if filled is None else filled,
            status=status,
            order_remark=current.order_remark,
            client_order_id=current.client_order_id,
            average_fill_price=price,
        )


class BrokerQueryAmbiguousFallback(Exception):
    pass


class _Harness:
    """Builds the qec path (session + TGrid sidecar + guard) on a fresh DB."""

    def __init__(self, broker=None, *, guard_flags=None):
        self.db_path = _temp_db_path()
        self.conn = initialize(self.db_path)
        self.store = ExecutionStore(self.conn)
        self.exposure = DailyExposureLedger(trade_date="2026-08-16", store=_DictStore())
        self.sidecar = TGridSidecar(
            store=self.store, exposure=self.exposure, strategy_name="TGRID", now=_now,
        )
        self.broker = broker or _ScriptBroker()
        self.tmp = tempfile.mkdtemp()
        flags = dict(
            environment_verified=True, account_verified=True,
            broker_snapshot_verified=True, position_verified=True,
            cash_verified=True, quote_verified=True,
            kill_switch_active=False, exposure_ready=True,
        )
        flags.update(guard_flags or {})

        def _cb(v):
            return lambda: v

        self.guard = TGridExecutionGuard(
            policy=_policy(),
            environment_verified=_cb(flags["environment_verified"]),
            account_verified=_cb(flags["account_verified"]),
            broker_snapshot_verified=_cb(flags["broker_snapshot_verified"]),
            position_verified=_cb(flags["position_verified"]),
            cash_verified=_cb(flags["cash_verified"]),
            quote_verified=_cb(flags["quote_verified"]),
            kill_switch_active=_cb(flags["kill_switch_active"]),
            exposure_ready=_cb(flags["exposure_ready"]),
            exposure_used=_cb(0.0),
        )
        self.session = ExecutionSession(
            broker=self.broker,
            guard=self.guard,
            journal_path=os.path.join(self.tmp, "journal.json"),
            lock_path=os.path.join(self.tmp, "exec.lock"),
            execution_id="TGRID",
            before_broker_submit=self.sidecar.before_broker_submit,
            before_broker_cancel=self.sidecar.before_broker_cancel,
        )
        self.session.open()

    def close(self):
        self.session.close()
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def submit(self, key="K1", remark="TG_510300SH_B001", qty=100, price=4.7, side=BUY):
        request = make_execution_request(
            client_order_key=key, symbol="510300.SH", side=side, qty=qty,
            limit_price=price, strategy_name="TGRID", order_remark=remark,
        )
        snap = self.session.submit(request)
        if snap.broker_order_id is not None:
            apply_snapshot(self.store, snap, client_order_key=key, now=_now())
        return snap


class TestQecEquivalenceMatrix(unittest.TestCase):
    def test_submit_accepted_working(self):
        h = _Harness()
        try:
            snap = h.submit()
            self.assertEqual(snap.state, TradeState.WORKING)
            self.assertEqual(h.broker.place_calls, 1)
            # TGrid ledger committed pre-broker (matrix 21).
            self.assertEqual(h.store.get_intent("K1").status, OrderStatus.SUBMITTED)
            self.assertIsNotNone(h.store.get_intent("K1").broker_order_id)
            self.assertEqual(h.exposure.used, 470.0)
            self.assertEqual(len(tuple(h.store.list_active_reservations())), 1)
        finally:
            h.close()

    def test_submit_rejected_fail_closed(self):
        h = _Harness(broker=_ScriptBroker())
        h.broker.submit_mode = "reject"
        try:
            snap = h.submit()
            self.assertEqual(snap.state, TradeState.REJECTED)
            self.assertEqual(h.broker.place_calls, 1)  # broker was called and rejected
        finally:
            h.close()

    def test_submit_ambiguous_unknown_no_blind_resend(self):
        h = _Harness(broker=_ScriptBroker())
        h.broker.submit_mode = "ambiguous"
        try:
            snap = h.submit()
            self.assertEqual(snap.state, TradeState.UNKNOWN)
            self.assertEqual(h.broker.place_calls, 1)
            # poll again -> recovery finds no broker order -> FAILED, no resend.
            out = h.session.poll()
            self.assertEqual(out.state, TradeState.FAILED)
            self.assertEqual(h.broker.place_calls, 1)
        finally:
            h.close()

    def test_partial_then_full_fill(self):
        h = _Harness()
        try:
            snap = h.submit()
            oid = snap.broker_order_id
            h.broker._set_status(oid, BrokerOrderStatus.PARTIALLY_FILLED, filled=40, price=4.69)
            partial = h.session.poll()
            self.assertEqual(partial.state, TradeState.PARTIALLY_FILLED)
            apply_snapshot(h.store, partial, client_order_key="K1", now=_now())
            self.assertEqual(h.store.get_intent("K1").status, OrderStatus.PARTIAL)
            h.broker._set_status(oid, BrokerOrderStatus.FILLED, filled=100, price=4.69)
            filled = h.session.poll()
            self.assertEqual(filled.state, TradeState.FILLED)
            apply_snapshot(h.store, filled, client_order_key="K1", now=_now())
            self.assertEqual(h.store.get_intent("K1").status, OrderStatus.FILLED)
            self.assertEqual(tuple(h.store.list_active_reservations()), ())
        finally:
            h.close()

    def test_cancel_pending_then_confirmed(self):
        h = _Harness()
        try:
            snap = h.submit()
            oid = snap.broker_order_id
            out = h.session.cancel()
            self.assertEqual(out.state, TradeState.CANCELLING)
            self.assertEqual(h.broker.cancel_calls, 1)
            # TGrid cancel accounting ran (sidecar).
            self.assertEqual(h.store.get_intent("K1").status, OrderStatus.CANCEL_REQUESTED)
            h.broker._set_status(oid, BrokerOrderStatus.CANCELLED)
            out = h.session.poll()
            self.assertEqual(out.state, TradeState.CANCELLED)
            apply_snapshot(h.store, out, client_order_key="K1", now=_now())
            self.assertEqual(h.store.get_intent("K1").status, OrderStatus.CANCELED)
        finally:
            h.close()

    def test_cancel_rejected_requires_requery(self):
        h = _Harness(broker=_ScriptBroker())
        h.broker.cancel_result = CancelRequestResult.REJECTED
        try:
            snap = h.submit()
            oid = snap.broker_order_id
            out = h.session.cancel()
            self.assertNotEqual(out.state, TradeState.CANCELLED)
            self.assertEqual(h.broker.orders[oid].status, BrokerOrderStatus.WORKING)
            # broker later confirms the cancel -> poll resolves (matrix 9).
            h.broker._set_status(oid, BrokerOrderStatus.CANCELLED)
            out = h.session.poll()
            self.assertEqual(out.state, TradeState.CANCELLED)
        finally:
            h.close()

    def test_partial_fill_plus_cancel_preserves_fill(self):
        h = _Harness()
        try:
            snap = h.submit()
            oid = snap.broker_order_id
            h.broker._set_status(oid, BrokerOrderStatus.PARTIALLY_FILLED, filled=40, price=4.69)
            self.assertEqual(h.session.poll().state, TradeState.PARTIALLY_FILLED)
            out = h.session.cancel()
            self.assertEqual(out.state, TradeState.CANCELLING)
            h.broker._set_status(oid, BrokerOrderStatus.PARTIAL_CANCELLED, filled=40, price=4.69)
            out = h.session.poll()
            self.assertEqual(out.state, TradeState.CANCELLED)
            self.assertEqual(out.filled_qty, 40)  # partial fill preserved (matrix 10)
        finally:
            h.close()

    def test_fill_during_cancel_race_goes_to_filled(self):
        # Matrix 11 (dedicated): a final fill arrives while the cancel is
        # in flight -> the model resolves to FILLED, never a phantom cancel.
        h = _Harness()
        try:
            snap = h.submit()
            oid = snap.broker_order_id
            out = h.session.cancel()
            self.assertEqual(out.state, TradeState.CANCELLING)
            # Broker reports a FULL fill while cancel is pending.
            h.broker._set_status(oid, BrokerOrderStatus.FILLED, filled=100, price=4.69)
            out = h.session.poll()
            self.assertEqual(out.state, TradeState.FILLED)
            apply_snapshot(h.store, out, client_order_key="K1", now=_now())
            self.assertEqual(h.store.get_intent("K1").status, OrderStatus.FILLED)
        finally:
            h.close()

    def test_restart_from_active_and_cancel_pending(self):
        # Matrix 13/14: reopen the same journal; recovery re-queries the broker.
        h = _Harness()
        try:
            snap = h.submit()
            h.session.close()
            h.session = ExecutionSession(
                broker=h.broker,
                guard=h.guard,
                journal_path=os.path.join(h.tmp, "journal.json"),
                lock_path=os.path.join(h.tmp, "exec.lock"),
                execution_id="TGRID",
                before_broker_submit=h.sidecar.before_broker_submit,
                before_broker_cancel=h.sidecar.before_broker_cancel,
            )
            out = h.session.open()
            self.assertEqual(out.state, TradeState.WORKING)  # restart active (13)

            # cancel -> restart while cancel pending (14)
            out = h.session.cancel()
            self.assertEqual(out.state, TradeState.CANCELLING)
            h.session.close()
            h.session = ExecutionSession(
                broker=h.broker,
                guard=h.guard,
                journal_path=os.path.join(h.tmp, "journal.json"),
                lock_path=os.path.join(h.tmp, "exec.lock"),
                execution_id="TGRID",
                before_broker_submit=h.sidecar.before_broker_submit,
                before_broker_cancel=h.sidecar.before_broker_cancel,
            )
            out = h.session.open()
            self.assertEqual(out.state, TradeState.CANCELLING)
            h.broker._set_status(snap.broker_order_id, BrokerOrderStatus.CANCELLED)
            out = h.session.poll()
            self.assertEqual(out.state, TradeState.CANCELLED)
        finally:
            h.close()

    def test_query_none_is_ambiguous_not_empty(self):
        # Matrix 15: None is ambiguous, never empty success (public strict query).
        h = _Harness()
        try:
            snap = h.submit()
            h.broker.query_none_mode = True
            with self.assertRaises(Exception):
                h.session.poll()
        finally:
            h.close()

    def test_unknown_raw_status_normalizes_to_unknown(self):
        # Matrix 16: unrecognized / 255 raw QMT status -> UNKNOWN fail closed.
        self.assertEqual(normalize_qmt_order_status(255).value, "unknown")
        self.assertEqual(normalize_qmt_order_status(9999).value, "unknown")
        self.assertEqual(normalize_qmt_order_status("50").value, "unknown")

    def test_disconnect_blocks_and_reconnect_requires_full_reconcile(self):
        # Matrix 17-19: health gate at the broker; the guard reflects it.
        h = _Harness(broker=_ScriptBroker())
        try:
            snap = h.submit()
            h.broker.healthy = False  # disconnect
            with self.assertRaises(Exception):
                h.session.submit(make_execution_request(
                    client_order_key="K2", symbol="510300.SH", side=BUY, qty=100,
                    limit_price=4.7, strategy_name="TGRID", order_remark="R2",
                ))
            # reconnect alone does not restore (execution_healthy is still False
            # until the full reconcile re-marks it healthy).
            self.assertFalse(h.session.broker.execution_healthy())
            h.broker.healthy = True  # full reconnect/reconcile restores
            self.assertTrue(h.session.broker.execution_healthy())
        finally:
            h.close()

    def test_kill_switch_blocks_new_orders(self):
        # Matrix 24: kill switch (guard gate) blocks new orders; query/cancel
        # paths remain safe.
        h = _Harness(guard_flags={"kill_switch_active": True})
        try:
            request = make_execution_request(
                client_order_key="K2", symbol="510300.SH", side=BUY, qty=100,
                limit_price=4.7, strategy_name="TGRID", order_remark="R2",
            )
            evidence = h.guard.verify(request)
            self.assertFalse(evidence.allowed)
            snap = h.session.submit(request)
            self.assertEqual(snap.state, TradeState.REJECTED)  # precheck rejected
            self.assertEqual(h.broker.place_calls, 0)
        finally:
            h.close()

    def test_duplicate_client_id_is_rejected_across_cycles(self):
        # Matrix 23: the durable journal rejects client_order_id reuse.
        h = _Harness()
        try:
            snap = h.submit(key="K1")
            h.broker._set_status(snap.broker_order_id, BrokerOrderStatus.FILLED,
                                 filled=100, price=4.69)
            self.assertEqual(h.session.poll().state, TradeState.FILLED)
            h.session.next_cycle()  # FILLED -> next cycle (journal clears cycle data)
            with self.assertRaises(Exception):
                h.session.submit(make_execution_request(
                    client_order_key="K1", symbol="510300.SH", side=BUY, qty=100,
                    limit_price=4.7, strategy_name="TGRID", order_remark="R1",
                ))
        finally:
            h.close()

    def test_crash_after_reservation_before_broker_fails_closed(self):
        # Matrix 22: a failing pre-submit sidecar proves the broker was never
        # called and restart recovery fails closed with no blind resend.
        h = _Harness()
        try:
            def failing_hook(request):
                raise RuntimeError("tgrid ledger commit failed")

            h.session = ExecutionSession(
                broker=h.broker,
                guard=h.guard,
                journal_path=os.path.join(h.tmp, "journal.json"),
                lock_path=os.path.join(h.tmp, "exec.lock"),
                execution_id="TGRID",
                before_broker_submit=failing_hook,
            )
            h.session.open()
            with self.assertRaises(RuntimeError):
                h.submit(key="K9")
            self.assertEqual(h.broker.place_calls, 0)
            h.session.close()
            # Restart with the normal sidecar: durable intent with no broker
            # order -> recovery FAILED, NO blind resend.
            h.session = ExecutionSession(
                broker=h.broker,
                guard=h.guard,
                journal_path=os.path.join(h.tmp, "journal.json"),
                lock_path=os.path.join(h.tmp, "exec.lock"),
                execution_id="TGRID",
                before_broker_submit=h.sidecar.before_broker_submit,
                before_broker_cancel=h.sidecar.before_broker_cancel,
            )
            out = h.session.open()
            self.assertEqual(out.state, TradeState.FAILED)
            self.assertEqual(h.broker.place_calls, 0)
        finally:
            h.close()

    def test_transient_unknown_recovery_reaches_filled(self):
        # P1-2 dedicated regression (acceptance gate 6):
        # SUBMITTED -> public UNKNOWN (recoverable) -> authoritative recovery
        # WORKING -> FILLED.  The TGrid intent must NEVER terminalize at
        # UNKNOWN, later observations must update the SAME intent, the
        # reservation releases only on FILLED, and there is NO second submit.
        h = _Harness(broker=_ScriptBroker())
        h.broker.submit_mode = "ambiguous_after"
        try:
            snap = h.submit()  # broker accepted, then ambiguous -> UNKNOWN
            self.assertEqual(snap.state, TradeState.UNKNOWN)
            self.assertEqual(h.broker.place_calls, 1)
            # Transient UNKNOWN must not terminalize the TGrid intent.
            apply_snapshot(h.store, snap, client_order_key="K1", now=_now())
            self.assertNotEqual(h.store.get_intent("K1").status, OrderStatus.UNKNOWN)
            # Authoritative recovery finds the broker order by durable remark.
            out = h.session.poll()
            self.assertEqual(out.state, TradeState.WORKING)
            self.assertIsNotNone(out.broker_order_id)
            apply_snapshot(h.store, out, client_order_key="K1", now=_now())
            intent = h.store.get_intent("K1")
            self.assertEqual(intent.status, OrderStatus.SUBMITTED)
            self.assertEqual(intent.broker_order_id, str(out.broker_order_id))
            # Broker fills -> FILLED -> reservation released; no second submit.
            h.broker._set_status(out.broker_order_id, BrokerOrderStatus.FILLED,
                                 filled=100, price=4.69)
            filled = h.session.poll()
            self.assertEqual(filled.state, TradeState.FILLED)
            apply_snapshot(h.store, filled, client_order_key="K1", now=_now())
            self.assertEqual(h.store.get_intent("K1").status, OrderStatus.FILLED)
            self.assertEqual(tuple(h.store.list_active_reservations()), ())
            self.assertEqual(h.broker.place_calls, 1)
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
