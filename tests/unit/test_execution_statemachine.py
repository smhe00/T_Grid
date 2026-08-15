"""Tests for the TGrid execution state machine + journal (reverse_repo port).

Verifies the formally-verified machine semantics:

* verify_state_machines() reaches a fixed point with 0 violations;
* every declared (state, event) edge is reachable; every declared state is
  reachable; every reachable nonterminal state can reach a terminal state;
* an unresolved order cannot return to READY;
* SUBMIT_UNKNOWN (submission outcome unknown) cannot auto-retry: only
  RECOVERED_* events leave it, RECOVERED_NO_MATCH halts;
* invalid events raise InvalidTransition in every state;
* snapshot payload round-trips with strict schema validation;
* journal: atomic write survives restart, strategy/trade_date mismatch is
  rejected (manual review), history is bounded, transition records carry
  sequence + machine payload, and the journal binds transition-spec +
  execution-source hashes (code change invalidates the journal).
"""

import os
import tempfile
import unittest

from tgrid.execution.execution_journal import (
    ExecutionJournal,
    JournalIntegrityError,
    JournalSchemaError,
    JournalVerification,
)
from tgrid.execution.port import (
    BrokerDisconnectedError,
    BrokerError,
    BrokerOrderRejectedError,
)
from tgrid.execution.simbroker import SimBroker
from tgrid.execution.statemachine import (
    InvariantViolation,
    InvalidTransition,
    MachineSnapshot,
    SafetyFacts,
    TGridEvent,
    TGridState,
    TGRID_TRANSITIONS,
    advance,
    assert_invariants,
    initial_snapshot,
    snapshot_from_payload,
    snapshot_to_payload,
    verify_state_machines,
)


def _temp_path():
    handle = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    path = handle.name
    handle.close()
    os.remove(path)
    return path


class TestFormalVerification(unittest.TestCase):
    def test_verifier_reaches_fixed_point_without_violation(self):
        result = verify_state_machines()
        machine = result["tgrid"]
        self.assertEqual(machine["unreachable_states"], 0)
        self.assertEqual(machine["unreachable_transitions"], 0)
        self.assertEqual(machine["states_without_terminal_path"], 0)
        self.assertEqual(machine["invariant_violations"], 0)
        self.assertEqual(machine["declared_states"], len(TGRID_TRANSITIONS))
        self.assertGreater(machine["reachable_abstract_states"], 0)

    def test_every_declared_event_edge_is_executed(self):
        result = verify_state_machines()
        machine = result["tgrid"]
        # reachable_transitions >= declared_phase_event_edges (abstract states
        # may fan out); the verifier already raises if a declared edge is
        # unreachable, so reaching here means all edges execute.
        self.assertGreaterEqual(
            machine["reachable_transitions"],
            machine["declared_phase_event_edges"],
        )

    def test_invalid_events_rejected_in_every_state(self):
        for state in TGridState:
            allowed = set(TGRID_TRANSITIONS[state].keys())
            invalid = [e for e in TGridEvent if e not in allowed]
            snapshot = MachineSnapshot(state, SafetyFacts())
            for event in invalid:
                with self.assertRaises(InvalidTransition):
                    advance(snapshot, event)

    def test_unresolved_order_cannot_reach_ready(self):
        # Build to SUBMIT_UNKNOWN with unresolved=True, then try to return to
        # READY: there is no such transition, so it must raise.
        s = initial_snapshot()
        for ev in (TGridEvent.BEGIN, TGridEvent.PREFLIGHT_OK,
                   TGridEvent.RECOVERY_CLEAR, TGridEvent.TRIGGER,
                   TGridEvent.SNAPSHOT_OK, TGridEvent.INTENT_PERSISTED,
                   TGridEvent.SUBMIT_EXCEPTION):
            s = advance(s, ev)
        self.assertEqual(s.state, TGridState.SUBMIT_UNKNOWN)
        self.assertTrue(s.facts.unresolved_order)
        # No legal event returns SUBMIT_UNKNOWN to READY.
        with self.assertRaises(InvalidTransition):
            advance(s, TGridEvent.SNAPSHOT_OK)

    def test_submit_unknown_only_exits_via_recovered_events(self):
        s = initial_snapshot()
        for ev in (TGridEvent.BEGIN, TGridEvent.PREFLIGHT_OK,
                   TGridEvent.RECOVERY_CLEAR, TGridEvent.TRIGGER,
                   TGridEvent.SNAPSHOT_OK, TGridEvent.INTENT_PERSISTED,
                   TGridEvent.SUBMIT_EXCEPTION):
            s = advance(s, ev)
        allowed = set(TGRID_TRANSITIONS[s.state].keys())
        self.assertTrue(allowed <= {
            TGridEvent.RECOVERED_ACTIVE,
            TGridEvent.RECOVERED_CANCEL_PENDING,
            TGridEvent.RECOVERED_TERMINAL,
            TGridEvent.RECOVERED_NO_MATCH,
            TGridEvent.RECOVERY_AMBIGUOUS,
            TGridEvent.RESTART,
        })

    def test_recovered_no_match_halts(self):
        s = initial_snapshot()
        for ev in (TGridEvent.BEGIN, TGridEvent.PREFLIGHT_OK,
                   TGridEvent.RECOVERY_CLEAR, TGridEvent.TRIGGER,
                   TGridEvent.SNAPSHOT_OK, TGridEvent.INTENT_PERSISTED,
                   TGridEvent.SUBMIT_EXCEPTION):
            s = advance(s, ev)
        s = advance(s, TGridEvent.RECOVERED_NO_MATCH)
        self.assertEqual(s.state, TGridState.SAFE_HALT)
        self.assertTrue(s.facts.unresolved_order)

    def test_happy_path_reaches_done(self):
        s = initial_snapshot()
        for ev in (TGridEvent.BEGIN, TGridEvent.PREFLIGHT_OK,
                   TGridEvent.RECOVERY_CLEAR, TGridEvent.TRIGGER,
                   TGridEvent.SNAPSHOT_OK, TGridEvent.INTENT_PERSISTED,
                   TGridEvent.SUBMIT_ACCEPTED, TGridEvent.ORDER_TERMINAL,
                   TGridEvent.RECONCILED):
            s = advance(s, ev)
        self.assertEqual(s.state, TGridState.DONE)
        self.assertFalse(s.facts.unresolved_order)
        self.assertTrue(s.facts.terminal_order_confirmed)

    def test_restart_returns_to_recovery(self):
        s = initial_snapshot()
        for ev in (TGridEvent.BEGIN, TGridEvent.PREFLIGHT_OK,
                   TGridEvent.RECOVERY_CLEAR, TGridEvent.TRIGGER,
                   TGridEvent.SNAPSHOT_OK, TGridEvent.INTENT_PERSISTED,
                   TGridEvent.SUBMIT_ACCEPTED):
            s = advance(s, ev)
        self.assertEqual(s.state, TGridState.ORDER_ACTIVE)
        s = advance(s, TGridEvent.RESTART)
        self.assertEqual(s.state, TGridState.RECOVERY)
        self.assertTrue(s.facts.unresolved_order)  # possibly sent

    def test_invariants_violation_raises(self):
        # DONE with an unresolved order violates the success invariant.
        bad = MachineSnapshot(
            TGridState.DONE,
            SafetyFacts(environment_verified=True, account_verified=True,
                        orders_reconciled=True, intent_persisted=True,
                        unresolved_order=True, terminal_order_confirmed=True),
        )
        with self.assertRaises(InvariantViolation):
            assert_invariants(bad)


class TestSnapshotPayload(unittest.TestCase):
    def test_round_trip(self):
        s = initial_snapshot()
        for ev in (TGridEvent.BEGIN, TGridEvent.PREFLIGHT_OK):
            s = advance(s, ev)
        payload = snapshot_to_payload(s)
        restored = snapshot_from_payload(payload)
        self.assertEqual(restored.state, s.state)
        self.assertEqual(restored.facts, s.facts)

    def test_schema_strict(self):
        with self.assertRaises(InvariantViolation):
            snapshot_from_payload({"state": "ready"})  # missing facts
        with self.assertRaises(InvariantViolation):
            snapshot_from_payload({"state": "ready", "facts": {}})
        with self.assertRaises(InvariantViolation):
            snapshot_from_payload({
                "state": "ready",
                "facts": {k: "not-bool" for k in SafetyFacts.__dataclass_fields__},
            })
        with self.assertRaises(InvariantViolation):
            snapshot_from_payload({
                "state": "no_such_state",
                "facts": {k: False for k in SafetyFacts.__dataclass_fields__},
            })


class TestJournal(unittest.TestCase):
    def test_initialize_and_reload(self):
        path = _temp_path()
        j = ExecutionJournal(path, strategy="TGRID", trade_date="2026-08-15")
        j.load_or_initialize()  # lazy: first touch loads/creates
        self.assertEqual(j.payload["schema_version"], 2)
        self.assertEqual(j.payload["strategy"], "TGRID")
        j.transition(TGridEvent.BEGIN, snapshot_to_payload(initial_snapshot()))
        j2 = ExecutionJournal(path, strategy="TGRID", trade_date="2026-08-15")
        self.assertEqual(j2.machine["state"], "new")  # lazy touch loads
        self.assertEqual(j2.payload["event_count"], 1)
        os.remove(path)

    def test_lazy_init_touches_nothing_before_first_use(self):
        # SM9-002: construction must not read/write the journal; the caller
        # acquires the execution mutex BEFORE the first touch.
        path = _temp_path()
        j = ExecutionJournal(path, strategy="TGRID", trade_date="2026-08-15")
        self.assertFalse(os.path.exists(path))
        self.assertEqual(j.payload, {})
        j.load_or_initialize()
        self.assertTrue(os.path.exists(path))
        os.remove(path)

    def test_strategy_mismatch_rejected(self):
        path = _temp_path()
        ExecutionJournal(path, strategy="TGRID",
                         trade_date="2026-08-15").load_or_initialize()
        with self.assertRaises(JournalSchemaError):
            ExecutionJournal(path, strategy="OTHER",
                             trade_date="2026-08-15").load_or_initialize()
        os.remove(path)

    def test_trade_date_mismatch_rejected(self):
        path = _temp_path()
        ExecutionJournal(path, strategy="TGRID",
                         trade_date="2026-08-15").load_or_initialize()
        with self.assertRaises(JournalSchemaError):
            ExecutionJournal(path, strategy="TGRID",
                             trade_date="2026-08-16").load_or_initialize()
        os.remove(path)

    def test_transition_history_bounded_and_sequenced(self):
        path = _temp_path()
        j = ExecutionJournal(path, strategy="TGRID", trade_date="2026-08-15")
        for i in range(20):
            j.transition(TGridEvent.RESTART,
                         snapshot_to_payload(initial_snapshot()),
                         details={"i": i})
        self.assertEqual(len(j.payload["history"]), 20)
        self.assertEqual(j.payload["history"][-1]["sequence"], 20)
        self.assertEqual(j.payload["event_count"], 20)
        os.remove(path)

    def test_verification_binding(self):
        path = _temp_path()
        j = ExecutionJournal(path, strategy="TGRID", trade_date="2026-08-15")
        v = JournalVerification(transition_spec_sha256="a" * 64,
                                execution_source_sha256="b" * 64)
        self.assertFalse(j.journal_matches_verification(v))
        j.bind_verification(v)
        j2 = ExecutionJournal(path, strategy="TGRID", trade_date="2026-08-15")
        self.assertTrue(j2.journal_matches_verification(v))
        wrong = JournalVerification(transition_spec_sha256="c" * 64,
                                    execution_source_sha256="b" * 64)
        self.assertFalse(j2.journal_matches_verification(wrong))
        os.remove(path)

    def test_corrupt_journal_rejected(self):
        path = _temp_path()
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(JournalIntegrityError):
            ExecutionJournal(path, strategy="TGRID",
                             trade_date="2026-08-15").load_or_initialize()
        os.remove(path)


class TestSourceManifestIntegrity(unittest.TestCase):
    """SM9-005: protected source manifest is complete and fail-closed."""

    def test_manifest_covers_safety_critical_sources(self):
        from tgrid.execution.statemachine import EXECUTION_SOURCE_FILES

        required = {
            # execution authority
            "src/tgrid/execution/statemachine.py",
            "src/tgrid/execution/execution_journal.py",
            "src/tgrid/execution/execution_mutex.py",
            "src/tgrid/execution/executor.py",
            "src/tgrid/execution/recovery.py",
            "src/tgrid/execution/store.py",
            "src/tgrid/execution/models.py",
            "src/tgrid/execution/port.py",
            # production wiring + account/session construction
            "src/tgrid/integrations/live_bootstrap.py",
            "src/tgrid/integrations/live_session.py",
            "src/tgrid/integrations/live_broker_adapter.py",
            "src/tgrid/integrations/xtquant_bridge.py",
            # durable daily exposure / exposure persistence
            "src/tgrid/integrations/daily_exposure.py",
            "src/tgrid/integrations/exposure_store.py",
        }
        self.assertTrue(
            required <= set(EXECUTION_SOURCE_FILES),
            f"manifest missing: {required - set(EXECUTION_SOURCE_FILES)}",
        )

    def test_missing_protected_file_fails_verification(self):
        import tgrid.execution.statemachine as sm

        original = sm.EXECUTION_SOURCE_FILES
        try:
            sm.EXECUTION_SOURCE_FILES = original + (
                "src/tgrid/execution/__no_such_protected_file__.py",
            )
            with self.assertRaises(sm.ExecutionSourceIntegrityError):
                sm.execution_source_sha256()
            # verify_state_machines() propagates the integrity failure.
            with self.assertRaises(sm.ExecutionSourceIntegrityError):
                sm.verify_state_machines()
        finally:
            sm.EXECUTION_SOURCE_FILES = original


class TestEngineStateMachineIntegration(unittest.TestCase):
    """State-machine + journal drive the ExecutionEngine order lifecycle."""

    def _engine(self, path, broker=None):
        from tgrid.execution.executor import ExecutionEngine
        from tgrid.execution.execution_journal import ExecutionJournal
        from tgrid.execution.simbroker import SimBroker
        from tgrid.execution.store import ExecutionStore
        from tgrid.persistence import initialize

        conn = initialize(path)
        store = ExecutionStore(conn)
        broker = broker or SimBroker()
        journal = ExecutionJournal(
            _temp_path(), strategy="TGRID", trade_date="2026-08-15"
        )
        from tgrid.execution.statemachine import initial_snapshot

        engine = ExecutionEngine(
            store, broker, machine=initial_snapshot(), journal=journal,
        )
        return conn, store, broker, engine, journal

    def _run_to_ready(self, engine, journal):
        from tgrid.execution.statemachine import TGridEvent

        for ev in (TGridEvent.BEGIN, TGridEvent.PREFLIGHT_OK,
                   TGridEvent.RECOVERY_CLEAR, TGridEvent.TRIGGER,
                   TGridEvent.SNAPSHOT_OK):
            engine._advance_machine(ev)
        return engine.machine

    def test_engine_send_drives_machine_and_journal(self):
        path = _temp_path()
        conn, store, broker, engine, journal = self._engine(path)
        try:
            self._run_to_ready(engine, journal)
            result = engine.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
            )
            self.assertEqual(result.status, "SUBMITTED")
            # INTENT_PERSISTED + SUBMIT_ACCEPTED -> ORDER_ACTIVE.
            self.assertEqual(engine.machine.state.value, "order_active")
            self.assertTrue(engine.machine.facts.intent_persisted)
            self.assertTrue(engine.machine.facts.unresolved_order)
            # Journal persisted every transition with sequence numbers.
            self.assertGreaterEqual(journal.payload["event_count"], 7)
            self.assertEqual(journal.machine["state"], "order_active")
            # Restart: journal reloads the machine state.
            from tgrid.execution.execution_journal import ExecutionJournal

            reloaded = ExecutionJournal(
                journal.path, strategy="TGRID", trade_date="2026-08-15"
            )
            self.assertEqual(reloaded.machine["state"], "order_active")
        finally:
            conn.close()
            os.remove(path)

    def test_engine_submit_exception_lands_in_submit_unknown(self):
        from tgrid.execution.executor import OrderSendFailedError
        from tgrid.execution.simbroker import SimBroker
        from tgrid.execution.statemachine import TGridEvent, initial_snapshot
        from tgrid.execution.store import ExecutionStore
        from tgrid.persistence import initialize

        path = _temp_path()
        conn = initialize(path)
        store = ExecutionStore(conn)
        broker = SimBroker()
        broker.connected = False  # force disconnect on send
        journal = ExecutionJournal(_temp_path(), strategy="TGRID",
                                   trade_date="2026-08-15")
        from tgrid.execution.executor import ExecutionEngine

        engine = ExecutionEngine(store, broker, machine=initial_snapshot(),
                                 journal=journal)
        self._run_to_ready(engine, journal)
        try:
            with self.assertRaises(OrderSendFailedError):
                engine.send_buy(
                    client_order_key="K1", symbol="0700.HK", qty=100,
                    limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                    expected_available_cash=500000.0, reserved_cash=42000.0,
                )
            # SUBMIT_EXCEPTION -> SUBMIT_UNKNOWN (outcome unknown, no retry).
            self.assertEqual(engine.machine.state.value, "submission_outcome_unknown")
            self.assertTrue(engine.machine.facts.unresolved_order)
            # Only RECOVERED_* events may exit SUBMIT_UNKNOWN.
            allowed = set(
                __import__("tgrid.execution.statemachine",
                           fromlist=["TGRID_TRANSITIONS"]).TGRID_TRANSITIONS[
                               engine.machine.state].keys()
            )
            self.assertTrue(allowed <= {
                TGridEvent.RECOVERED_ACTIVE,
                TGridEvent.RECOVERED_CANCEL_PENDING,
                TGridEvent.RECOVERED_TERMINAL,
                TGridEvent.RECOVERED_NO_MATCH,
                TGridEvent.RECOVERY_AMBIGUOUS,
                TGridEvent.RESTART,
            })
        finally:
            conn.close()
            os.remove(path)

    def test_engine_poll_terminal_advances_machine_to_reconcile(self):
        from tgrid.execution.simbroker import SimBroker
        from tgrid.execution.statemachine import TGridEvent, initial_snapshot
        from tgrid.execution.store import ExecutionStore
        from tgrid.persistence import initialize

        path = _temp_path()
        conn = initialize(path)
        store = ExecutionStore(conn)
        broker = SimBroker()
        journal = ExecutionJournal(_temp_path(), strategy="TGRID",
                                   trade_date="2026-08-15")
        from tgrid.execution.executor import ExecutionEngine

        engine = ExecutionEngine(store, broker, machine=initial_snapshot(),
                                 journal=journal)
        self._run_to_ready(engine, journal)
        try:
            result = engine.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
            )
            # Sim broker fills deterministically on poll.
            broker.get_order(result.broker_order_id).script = (("FILL", 100, 420.0),)
            broker.tick_order(result.broker_order_id)
            engine.poll_order("K1", now="t1")
            # ORDER_TERMINAL -> RECONCILE.
            self.assertEqual(engine.machine.state.value, "reconcile_terminal_order")
            # Reconciled -> DONE.
            engine._advance_machine(TGridEvent.RECONCILED)
            self.assertEqual(engine.machine.state.value, "done")
            self.assertFalse(engine.machine.facts.unresolved_order)
            self.assertTrue(engine.machine.facts.terminal_order_confirmed)
        finally:
            conn.close()
            os.remove(path)

    def test_send_requires_trusted_preflight(self):
        """SM9-003A: send_* must NOT synthesize TRIGGER/SNAPSHOT_OK."""
        from tgrid.execution.executor import ExecutionError

        conn, store, broker, engine, journal = self._engine(_temp_path())
        try:
            # Machine at WAIT_TRIGGER only (BEGIN..RECOVERY_CLEAR).
            for ev in (TGridEvent.BEGIN, TGridEvent.PREFLIGHT_OK,
                       TGridEvent.RECOVERY_CLEAR):
                engine._advance_machine(ev)
            self.assertEqual(engine.machine.state.value, "wait_trigger")
            with self.assertRaises(ExecutionError):
                engine.send_buy(
                    client_order_key="K1", symbol="0700.HK", qty=100,
                    limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                    expected_available_cash=500000.0, reserved_cash=42000.0,
                )
            # No self-certified snapshot: the machine never moved to READY.
            self.assertEqual(engine.machine.state.value, "wait_trigger")
        finally:
            conn.close()

    def test_canceled_observed_from_order_active_uses_order_terminal(self):
        """SM9-003B: a spontaneous broker CANCELED from ORDER_ACTIVE uses
        ORDER_TERMINAL (CANCEL_TERMINAL is only valid from CANCEL_PENDING)."""
        conn, store, broker, engine, journal = self._engine(_temp_path())
        try:
            self._run_to_ready(engine, journal)
            result = engine.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
            )
            self.assertEqual(engine.machine.state.value, "order_active")
            broker.get_order(result.broker_order_id).status = "CANCELED"
            outcome = engine.poll_order("K1", now="t1")
            self.assertEqual(outcome.status, "CANCELED")
            self.assertEqual(engine.machine.state.value, "reconcile_terminal_order")
        finally:
            conn.close()

    def test_poll_after_cancel_uses_cancel_pending_events(self):
        """SM9-003B: while CANCEL_PENDING, pending outcomes map to
        CANCEL_STILL_PENDING and terminal outcomes to CANCEL_TERMINAL."""
        broker = _AsyncCancelBroker()
        conn, store, broker, engine, journal = self._engine(_temp_path(), broker)
        try:
            self._run_to_ready(engine, journal)
            result = engine.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
            )
            engine.timeout_order("K1", now="t1")  # async cancel: stays pending
            self.assertEqual(engine.machine.state.value, "cancel_pending")
            self.assertEqual(broker.get_order(result.broker_order_id).status,
                             "CANCEL_REQUESTED")
            # Cancel completes asynchronously -> CANCEL_TERMINAL -> RECONCILE.
            broker.get_order(result.broker_order_id).status = "CANCELED"
            outcome = engine.poll_order("K1", now="t2")
            self.assertEqual(outcome.status, "CANCELED")
            self.assertEqual(engine.machine.state.value, "reconcile_terminal_order")
        finally:
            conn.close()

    def test_definitive_rejection_maps_submit_rejected(self):
        """SM9-003D: a definitive rejection (BrokerOrderRejectedError) maps to
        SUBMIT_REJECTED -> SAFE_HALT and closes the intent, never to the
        ambiguous SUBMIT_EXCEPTION."""
        from tgrid.execution.executor import OrderSendFailedError
        from tgrid.execution.port import BrokerOrderRejectedError

        broker = _RejectingBroker()
        conn, store, broker, engine, journal = self._engine(_temp_path(), broker)
        try:
            self._run_to_ready(engine, journal)
            with self.assertRaises(OrderSendFailedError):
                engine.send_buy(
                    client_order_key="K1", symbol="0700.HK", qty=100,
                    limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                    expected_available_cash=500000.0, reserved_cash=42000.0,
                )
            self.assertEqual(engine.machine.state.value, "safe_halt")
            self.assertEqual(store.get_intent("K1").status, "REJECTED")
            # Definitive rejection released the reservation.
            self.assertEqual(tuple(store.list_active_reservations()), ())
        finally:
            conn.close()


class TestUnknownSubmissionRecovery(unittest.TestCase):
    """reverse_repo _recover_unknown_submission port: SUBMIT_UNKNOWN by remark."""

    def _engine(self, broker=None):
        from tgrid.execution.executor import ExecutionEngine
        from tgrid.execution.execution_journal import ExecutionJournal
        from tgrid.execution.simbroker import SimBroker
        from tgrid.execution.store import ExecutionStore
        from tgrid.execution.statemachine import initial_snapshot
        from tgrid.persistence import initialize

        conn = initialize(_temp_path())
        store = ExecutionStore(conn)
        broker = broker or SimBroker()
        journal = ExecutionJournal(_temp_path(), strategy="TGRID",
                                   trade_date="2026-08-15")
        engine = ExecutionEngine(store, broker, machine=initial_snapshot(),
                                 journal=journal)
        return conn, store, broker, engine, journal

    def _run_to_ready(self, engine):
        from tgrid.execution.statemachine import TGridEvent

        for ev in (TGridEvent.BEGIN, TGridEvent.PREFLIGHT_OK,
                   TGridEvent.RECOVERY_CLEAR, TGridEvent.TRIGGER,
                   TGridEvent.SNAPSHOT_OK):
            engine._advance_machine(ev)

    def _failed_send(self, engine):
        from tgrid.execution.executor import OrderSendFailedError

        with self.assertRaises(OrderSendFailedError):
            engine.send_buy(
                client_order_key="K1", symbol="0700.HK", qty=100,
                limit_price=420.0, order_remark="TG_0700_B01", now="t0",
                expected_available_cash=500000.0, reserved_cash=42000.0,
            )
        self.assertEqual(engine.machine.state.value, "submission_outcome_unknown")

    def test_recovered_active_by_remark(self):
        broker = _FailAfterPlaceBroker()
        conn, store, broker, engine, journal = self._engine(broker)
        try:
            self._run_to_ready(engine)
            self._failed_send(engine)
            result = engine.recover_unknown_submission("K1", now="t1")
            self.assertEqual(result.status, "SUBMITTED")
            self.assertEqual(engine.machine.state.value, "order_active")
            self.assertTrue(engine.machine.facts.unresolved_order)
            intent = store.get_intent("K1")
            self.assertEqual(intent.status, "SUBMITTED")
            self.assertEqual(intent.broker_order_id, result.broker_order_id)
            self.assertTrue(result.broker_order_id.startswith("SIM"))
            # Journal persisted the recovery transition.
            self.assertEqual(journal.machine["state"], "order_active")
        finally:
            conn.close()

    def test_recovered_cancel_pending_by_remark(self):
        broker = _FailAfterPlaceBroker(status_override="CANCEL_REQUESTED")
        conn, store, broker, engine, journal = self._engine(broker)
        try:
            self._run_to_ready(engine)
            self._failed_send(engine)
            result = engine.recover_unknown_submission("K1", now="t1")
            self.assertEqual(result.status, "CANCEL_REQUESTED")
            self.assertEqual(engine.machine.state.value, "cancel_pending")
        finally:
            conn.close()

    def test_recovered_terminal_rejected_by_remark(self):
        broker = _FailAfterPlaceBroker(status_override="REJECTED")
        conn, store, broker, engine, journal = self._engine(broker)
        try:
            self._run_to_ready(engine)
            self._failed_send(engine)
            result = engine.recover_unknown_submission("K1", now="t1")
            self.assertEqual(result.status, "REJECTED")
            self.assertEqual(engine.machine.state.value, "reconcile_terminal_order")
            intent = store.get_intent("K1")
            self.assertEqual(intent.status, "REJECTED")
            # Terminal recovery released the reservation (REJECTED path).
            self.assertEqual(
                tuple(store.list_active_reservations()), ()
            )
        finally:
            conn.close()

    def test_recovered_no_match_halts_no_retry(self):
        from tgrid.execution.executor import OrderReconciliationError
        from tgrid.execution.simbroker import SimBroker

        broker = SimBroker()
        broker.connected = False  # send raises before any broker order exists
        conn, store, broker, engine, journal = self._engine(broker)
        try:
            self._run_to_ready(engine)
            self._failed_send(engine)
            with self.assertRaises(OrderReconciliationError):
                engine.recover_unknown_submission("K1", now="t1")
            # RECOVERED_NO_MATCH -> SAFE_HALT: automatic retry forbidden.
            self.assertEqual(engine.machine.state.value, "safe_halt")
        finally:
            conn.close()

    def test_multiple_remark_matches_fail_closed(self):
        from tgrid.execution.executor import OrderReconciliationError

        broker = _FailAfterPlaceBroker(duplicate_remark=True)
        conn, store, broker, engine, journal = self._engine(broker)
        try:
            self._run_to_ready(engine)
            self._failed_send(engine)
            with self.assertRaises(OrderReconciliationError):
                engine.recover_unknown_submission("K1", now="t1")
            self.assertEqual(engine.machine.state.value, "safe_halt")
            self.assertTrue(engine.safe_mode)
        finally:
            conn.close()

    def test_identity_mismatch_fails_closed(self):
        from tgrid.execution.executor import OrderReconciliationError

        broker = _FailAfterPlaceBroker(symbol_override="600000.SH")
        conn, store, broker, engine, journal = self._engine(broker)
        try:
            self._run_to_ready(engine)
            self._failed_send(engine)
            with self.assertRaises(OrderReconciliationError):
                engine.recover_unknown_submission("K1", now="t1")
            self.assertEqual(engine.machine.state.value, "safe_halt")
            self.assertTrue(engine.safe_mode)
        finally:
            conn.close()

    def test_query_failure_fails_closed(self):
        from tgrid.execution.executor import OrderReconciliationError

        broker = _FailAfterPlaceBroker()
        broker.query_orders = lambda *, symbol=None: (_ for _ in ()).throw(
            BrokerError("simulated all-orders query failure")
        )
        conn, store, broker, engine, journal = self._engine(broker)
        try:
            self._run_to_ready(engine)
            self._failed_send(engine)
            with self.assertRaises(OrderReconciliationError):
                engine.recover_unknown_submission("K1", now="t1")
            self.assertEqual(engine.machine.state.value, "safe_halt")
            self.assertTrue(engine.safe_mode)
        finally:
            conn.close()

    def test_recovery_requires_submit_unknown_state(self):
        from tgrid.execution.executor import ExecutionError

        conn, store, broker, engine, journal = self._engine()
        try:
            self._run_to_ready(engine)
            with self.assertRaises(ExecutionError):
                engine.recover_unknown_submission("K1", now="t1")
        finally:
            conn.close()

    def test_recovery_requires_state_machine_mode(self):
        from tgrid.execution.executor import ExecutionEngine, ExecutionError
        from tgrid.execution.simbroker import SimBroker
        from tgrid.execution.store import ExecutionStore
        from tgrid.persistence import initialize

        conn = initialize(_temp_path())
        store = ExecutionStore(conn)
        engine = ExecutionEngine(store, SimBroker())  # plain mode
        try:
            with self.assertRaises(ExecutionError):
                engine.recover_unknown_submission("K1", now="t1")
        finally:
            conn.close()

    def test_recovery_has_no_caller_remark_override(self):
        """SM9-004: the persisted intent remark is the SOLE recovery identity;
        a caller-supplied remark selector no longer exists."""
        conn, store, broker, engine, journal = self._engine(
            _FailAfterPlaceBroker()
        )
        try:
            self._run_to_ready(engine)
            self._failed_send(engine)
            with self.assertRaises(TypeError):
                engine.recover_unknown_submission(
                    "K1", now="t1", remark="ATTACKER_CHOSEN_REMARK"
                )
        finally:
            conn.close()


class _FailAfterPlaceBroker(SimBroker):
    """SimBroker that records the order, then raises (post-send ambiguity)."""

    def __init__(self, *, status_override=None, symbol_override=None,
                 duplicate_remark=False):
        super().__init__()
        self.status_override = status_override
        self.symbol_override = symbol_override
        self.duplicate_remark = duplicate_remark

    def place_order(self, **kwargs):
        order_id = super().place_order(**kwargs)
        order = self.get_order(order_id)
        if self.symbol_override is not None:
            order.symbol = self.symbol_override
        if self.duplicate_remark:
            super().place_order(**dict(kwargs))
        if self.status_override is not None:
            order.status = self.status_override
        raise BrokerDisconnectedError("simulated post-send failure")


class _AsyncCancelBroker(SimBroker):
    """cancel_order marks CANCEL_REQUESTED; the order stays pending (async)."""

    def cancel_order(self, order_id: str) -> None:
        order = self.get_order(order_id)
        if order.status in ("FILLED", "CANCELED", "REJECTED"):
            raise BrokerError("cannot cancel a terminal order")
        order.status = "CANCEL_REQUESTED"


class _RejectingBroker(SimBroker):
    """place_order always returns a definitive broker rejection."""

    def place_order(self, **kwargs):
        raise BrokerOrderRejectedError("broker rejected the order at send time")


if __name__ == "__main__":
    unittest.main()
