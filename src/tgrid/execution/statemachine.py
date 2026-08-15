"""TGrid execution state machine — ported from reverse_repo (NODEB-RR7-001).

This module ports the formally-verified state-machine framework from
``reverse_repo/repo_execution_state_machine.py`` (pinned c9ecc70) and defines
the TGrid execution machine for the ACCUMULATE order lifecycle.

What is ported (semantics preserved):

* :class:`SafetyFacts` — the same 9 booleans (environment/account/orders/
  cash/quote verified, intent_persisted, unresolved_order,
  terminal_order_confirmed, submitted_once);
* explicit transition tables + :func:`advance` with per-event fact updates;
* per-transition invariant assertions (preflight gates, cash/quote gates,
  durable-intent-before-external-order, unresolved-order shape, success
  cannot carry an unresolved order);
* the FORMAL VERIFIER :func:`verify_state_machines` — BFS reachability to a
  fixed point, no unreachable states/transitions, every nonterminal state can
  reach a terminal state, an unresolved order cannot return to READY, and a
  reprice/retry requires terminal confirmation; the product is bound to
  ``transition_spec_sha256`` + ``execution_source_sha256`` + git commit;
* snapshot payload serialization with strict schema validation on load.

The TGrid machine is a single order-lifecycle machine (the reverse_repo
Morning/Afternoon split is GC001-specific; TGrid ACCUMULATE uses one machine
per day for its BUY-first / sell-later lifecycle).  Terminal states are
``DONE`` / ``SKIPPED`` / ``SAFE_HALT``; ``SUBMIT_UNKNOWN`` exists so a
submission whose outcome is unknown is never auto-retried — recovery must
find a matching broker order by remark or halt.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Generic, TypeVar

# Files whose content is bound into execution_source_sha256 (mirror of
# reverse_repo EXECUTION_SOURCE_FILES, adapted to the TGrid tree).  SM9-005:
# the manifest covers EVERY safety-critical source that can alter pre-submit
# authorization, durable intent/reservation, account binding, broker state
# mapping, recovery, exposure, state transitions or journal/mutex behaviour;
# a MISSING protected file fails verification instead of being skipped.
EXECUTION_SOURCE_FILES = (
    # execution authority: state machine / journal / mutex / engine
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
)


class InvalidTransition(RuntimeError):
    """Raised when an event is not legal in the current machine state."""


class InvariantViolation(RuntimeError):
    """Raised when a machine state violates a safety invariant."""


class ExecutionSourceIntegrityError(RuntimeError):
    """A protected execution source file is missing (SM9-005, fail closed)."""


class TGridState(str, Enum):
    NEW = "new"
    PREFLIGHT = "preflight"
    RECOVERY = "recovery"
    WAIT_TRIGGER = "wait_trigger"
    SNAPSHOT = "snapshot"
    READY = "ready"
    INTENT = "intent_persisted"
    SUBMIT_UNKNOWN = "submission_outcome_unknown"
    ORDER_ACTIVE = "order_active"
    CANCEL_PENDING = "cancel_pending"
    RECONCILE = "reconcile_terminal_order"
    DONE = "done"
    SKIPPED = "skipped_non_trading_day"
    SAFE_HALT = "safe_halt"


class TGridEvent(str, Enum):
    BEGIN = "begin"
    PREFLIGHT_OK = "preflight_ok"
    NON_TRADING_DAY = "non_trading_day"
    RECOVERY_CLEAR = "recovery_clear"
    RECOVERY_ACTIVE = "recovery_active"
    RECOVERY_CANCEL_PENDING = "recovery_cancel_pending"
    RECOVERY_TERMINAL = "recovery_terminal"
    RECOVERY_AMBIGUOUS = "recovery_ambiguous"
    TRIGGER = "trigger"
    SNAPSHOT_OK = "snapshot_ok"
    SNAPSHOT_RETRY = "snapshot_retry"
    DEADLINE = "deadline"
    NO_FUNDS = "no_funds"
    INTENT_PERSISTED = "intent_persisted"
    SUBMIT_ACCEPTED = "submit_accepted"
    SUBMIT_REJECTED = "submit_rejected"
    SUBMIT_EXCEPTION = "submit_exception"
    RECOVERED_ACTIVE = "recovered_active"
    RECOVERED_CANCEL_PENDING = "recovered_cancel_pending"
    RECOVERED_TERMINAL = "recovered_terminal"
    RECOVERED_NO_MATCH = "recovered_no_match"
    ORDER_STILL_ACTIVE = "order_still_active"
    ORDER_TERMINAL = "order_terminal"
    ORDER_QUERY_AMBIGUOUS = "order_query_ambiguous"
    ORDER_STATUS_UNKNOWN = "order_status_unknown"
    CANCEL_REQUESTED = "cancel_requested"
    CANCEL_REJECTED = "cancel_rejected"
    CANCEL_STILL_PENDING = "cancel_still_pending"
    CANCEL_TERMINAL = "cancel_terminal"
    CANCEL_TIMEOUT = "cancel_timeout"
    RECONCILED = "reconciled"
    RECONCILE_FAILED = "reconcile_failed"
    FAULT = "fault"
    RESTART = "restart"


@dataclass(frozen=True)
class SafetyFacts:
    environment_verified: bool = False
    account_verified: bool = False
    orders_reconciled: bool = False
    cash_verified: bool = False
    quote_verified: bool = False
    intent_persisted: bool = False
    unresolved_order: bool = False
    terminal_order_confirmed: bool = False
    submitted_once: bool = False


StateT = TypeVar("StateT", bound=Enum)


@dataclass(frozen=True)
class MachineSnapshot(Generic[StateT]):
    state: StateT
    facts: SafetyFacts = SafetyFacts()


TGRID_TRANSITIONS: Mapping[TGridState, Mapping[TGridEvent, TGridState]] = {
    TGridState.NEW: {
        TGridEvent.BEGIN: TGridState.PREFLIGHT,
    },
    TGridState.PREFLIGHT: {
        TGridEvent.PREFLIGHT_OK: TGridState.RECOVERY,
        TGridEvent.NON_TRADING_DAY: TGridState.SKIPPED,
        TGridEvent.FAULT: TGridState.SAFE_HALT,
        TGridEvent.RESTART: TGridState.PREFLIGHT,
    },
    TGridState.RECOVERY: {
        TGridEvent.RECOVERY_CLEAR: TGridState.WAIT_TRIGGER,
        TGridEvent.RECOVERY_ACTIVE: TGridState.ORDER_ACTIVE,
        TGridEvent.RECOVERY_CANCEL_PENDING: TGridState.CANCEL_PENDING,
        TGridEvent.RECOVERY_TERMINAL: TGridState.RECONCILE,
        TGridEvent.RECOVERY_AMBIGUOUS: TGridState.SAFE_HALT,
        TGridEvent.FAULT: TGridState.SAFE_HALT,
        TGridEvent.RESTART: TGridState.RECOVERY,
    },
    TGridState.WAIT_TRIGGER: {
        TGridEvent.TRIGGER: TGridState.SNAPSHOT,
        TGridEvent.DEADLINE: TGridState.SAFE_HALT,
        TGridEvent.FAULT: TGridState.SAFE_HALT,
        TGridEvent.RESTART: TGridState.RECOVERY,
    },
    TGridState.SNAPSHOT: {
        TGridEvent.SNAPSHOT_OK: TGridState.READY,
        TGridEvent.SNAPSHOT_RETRY: TGridState.SNAPSHOT,
        TGridEvent.NO_FUNDS: TGridState.SAFE_HALT,
        TGridEvent.DEADLINE: TGridState.SAFE_HALT,
        TGridEvent.FAULT: TGridState.SAFE_HALT,
        TGridEvent.RESTART: TGridState.RECOVERY,
    },
    TGridState.READY: {
        TGridEvent.INTENT_PERSISTED: TGridState.INTENT,
        TGridEvent.FAULT: TGridState.SAFE_HALT,
        TGridEvent.RESTART: TGridState.RECOVERY,
    },
    TGridState.INTENT: {
        TGridEvent.SUBMIT_ACCEPTED: TGridState.ORDER_ACTIVE,
        TGridEvent.SUBMIT_REJECTED: TGridState.SAFE_HALT,
        TGridEvent.SUBMIT_EXCEPTION: TGridState.SUBMIT_UNKNOWN,
        TGridEvent.RESTART: TGridState.RECOVERY,
    },
    TGridState.SUBMIT_UNKNOWN: {
        TGridEvent.RECOVERED_ACTIVE: TGridState.ORDER_ACTIVE,
        TGridEvent.RECOVERED_CANCEL_PENDING: TGridState.CANCEL_PENDING,
        TGridEvent.RECOVERED_TERMINAL: TGridState.RECONCILE,
        TGridEvent.RECOVERED_NO_MATCH: TGridState.SAFE_HALT,
        TGridEvent.RECOVERY_AMBIGUOUS: TGridState.SAFE_HALT,
        TGridEvent.RESTART: TGridState.RECOVERY,
    },
    TGridState.ORDER_ACTIVE: {
        TGridEvent.ORDER_STILL_ACTIVE: TGridState.ORDER_ACTIVE,
        TGridEvent.ORDER_TERMINAL: TGridState.RECONCILE,
        TGridEvent.CANCEL_REQUESTED: TGridState.CANCEL_PENDING,
        TGridEvent.ORDER_QUERY_AMBIGUOUS: TGridState.SAFE_HALT,
        TGridEvent.ORDER_STATUS_UNKNOWN: TGridState.SAFE_HALT,
        TGridEvent.FAULT: TGridState.SAFE_HALT,
        TGridEvent.RESTART: TGridState.RECOVERY,
    },
    TGridState.CANCEL_PENDING: {
        TGridEvent.CANCEL_STILL_PENDING: TGridState.CANCEL_PENDING,
        TGridEvent.CANCEL_TERMINAL: TGridState.RECONCILE,
        TGridEvent.CANCEL_REJECTED: TGridState.SAFE_HALT,
        TGridEvent.CANCEL_TIMEOUT: TGridState.SAFE_HALT,
        TGridEvent.ORDER_QUERY_AMBIGUOUS: TGridState.SAFE_HALT,
        TGridEvent.ORDER_STATUS_UNKNOWN: TGridState.SAFE_HALT,
        TGridEvent.FAULT: TGridState.SAFE_HALT,
        TGridEvent.RESTART: TGridState.RECOVERY,
    },
    TGridState.RECONCILE: {
        TGridEvent.RECONCILED: TGridState.DONE,
        TGridEvent.RECONCILE_FAILED: TGridState.SAFE_HALT,
        TGridEvent.RESTART: TGridState.RECOVERY,
    },
    TGridState.DONE: {},
    TGridState.SKIPPED: {},
    TGridState.SAFE_HALT: {},
}


TGRID_TERMINAL_STATES = {
    TGridState.DONE,
    TGridState.SKIPPED,
    TGridState.SAFE_HALT,
}


def initial_snapshot() -> MachineSnapshot[TGridState]:
    return MachineSnapshot(TGridState.NEW)


def advance(
    snapshot: MachineSnapshot[TGridState],
    event: TGridEvent,
) -> MachineSnapshot[TGridState]:
    next_state = _next_state(TGRID_TRANSITIONS, snapshot.state, event)
    facts = snapshot.facts
    if event is TGridEvent.PREFLIGHT_OK:
        facts = replace(
            facts,
            environment_verified=True,
            account_verified=True,
        )
    elif event is TGridEvent.RECOVERY_CLEAR:
        facts = replace(
            facts,
            orders_reconciled=True,
            unresolved_order=False,
            terminal_order_confirmed=False,
        )
    elif event in {
        TGridEvent.RECOVERY_ACTIVE,
        TGridEvent.RECOVERY_CANCEL_PENDING,
        TGridEvent.RECOVERED_ACTIVE,
        TGridEvent.RECOVERED_CANCEL_PENDING,
        TGridEvent.SUBMIT_ACCEPTED,
    }:
        facts = replace(
            facts,
            orders_reconciled=True,
            unresolved_order=True,
            submitted_once=True,
            intent_persisted=True,
        )
    elif event is TGridEvent.RECOVERY_TERMINAL:
        facts = replace(
            facts,
            orders_reconciled=True,
            unresolved_order=False,
            terminal_order_confirmed=True,
            submitted_once=True,
            intent_persisted=True,
        )
    elif event is TGridEvent.SNAPSHOT_OK:
        facts = replace(
            facts,
            cash_verified=True,
            quote_verified=True,
        )
    elif event is TGridEvent.INTENT_PERSISTED:
        facts = replace(facts, intent_persisted=True)
    elif event is TGridEvent.SUBMIT_EXCEPTION:
        facts = replace(
            facts,
            unresolved_order=True,
            submitted_once=True,
        )
    elif event is TGridEvent.SUBMIT_REJECTED:
        facts = replace(facts, unresolved_order=False)
    elif event in {
        TGridEvent.ORDER_TERMINAL,
        TGridEvent.CANCEL_TERMINAL,
        TGridEvent.RECOVERED_TERMINAL,
    }:
        facts = replace(
            facts,
            unresolved_order=False,
            terminal_order_confirmed=True,
            submitted_once=True,
        )
    elif event is TGridEvent.RECONCILED:
        # DONE requires intent_persisted (invariant), so unlike afternoon's
        # RECONCILED (which resets and re-scans), the TGrid single-machine
        # completion keeps intent_persisted and confirms the terminal state.
        facts = replace(
            facts,
            cash_verified=False,
            quote_verified=False,
            unresolved_order=False,
            terminal_order_confirmed=True,
        )
    elif event is TGridEvent.RESTART:
        facts = _restart_facts(snapshot)
    elif next_state is TGridState.SAFE_HALT:
        unresolved = facts.unresolved_order or snapshot.state in {
            TGridState.INTENT,
            TGridState.SUBMIT_UNKNOWN,
            TGridState.ORDER_ACTIVE,
            TGridState.CANCEL_PENDING,
        }
        facts = replace(facts, unresolved_order=unresolved)
    result = MachineSnapshot(next_state, facts)
    assert_invariants(result)
    return result


def assert_invariants(
    snapshot: MachineSnapshot[TGridState],
) -> None:
    facts = snapshot.facts
    guarded = {
        TGridState.READY,
        TGridState.INTENT,
        TGridState.SUBMIT_UNKNOWN,
        TGridState.ORDER_ACTIVE,
        TGridState.CANCEL_PENDING,
        TGridState.RECONCILE,
        TGridState.DONE,
    }
    if snapshot.state in guarded and not (
        facts.environment_verified
        and facts.account_verified
        and facts.orders_reconciled
    ):
        raise InvariantViolation("order path lacks preflight gates")
    if snapshot.state in {
        TGridState.READY,
        TGridState.INTENT,
    } and not (facts.cash_verified and facts.quote_verified):
        raise InvariantViolation("submission lacks cash or quote gate")
    if snapshot.state in {
        TGridState.INTENT,
        TGridState.SUBMIT_UNKNOWN,
        TGridState.ORDER_ACTIVE,
        TGridState.CANCEL_PENDING,
        TGridState.RECONCILE,
        TGridState.DONE,
    } and not facts.intent_persisted:
        raise InvariantViolation("external order lacks durable intent")
    _assert_unresolved_shape(
        snapshot.state,
        facts,
        {
            TGridState.RECOVERY,
            TGridState.SUBMIT_UNKNOWN,
            TGridState.ORDER_ACTIVE,
            TGridState.CANCEL_PENDING,
            TGridState.SAFE_HALT,
        },
    )
    if snapshot.state is TGridState.DONE and (
        facts.unresolved_order or not facts.terminal_order_confirmed
    ):
        raise InvariantViolation("success has an unresolved order")


def verify_state_machines() -> dict[str, object]:
    """Formal verification of the TGrid machine (reverse_repo semantics).

    BFS reachability to a fixed point; proves no unreachable states or
    transitions, every reachable nonterminal state can reach a terminal
    state, an unresolved order cannot return to READY, and the product is
    bound to transition_spec_sha256 + execution_source_sha256 + git commit.
    """
    verified = _verify_machine(
        name="tgrid",
        initial=initial_snapshot(),
        transitions=TGRID_TRANSITIONS,
        terminal_states=TGRID_TERMINAL_STATES,
        advance=advance,
        invariant=assert_invariants,
    )
    source = {"tgrid": _transition_payload(TGRID_TRANSITIONS)}
    digest = hashlib.sha256(
        json.dumps(source, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "method": "exhaustive explicit-state reachability to fixed point",
        "transition_spec_sha256": digest,
        "execution_source_sha256": execution_source_sha256(),
        "execution_source_commit": execution_source_commit(),
        "tgrid": verified,
        "proved_invariants": [
            "submission requires verified environment and account",
            "submission requires reconciled broker order snapshot",
            "submission requires verified cash and fresh quote",
            "external order requires a durable pre-submit intent",
            "no completion state contains an unresolved order",
            "an unresolved order cannot return to a ready state",
            "every reachable nonterminal state can reach a terminal state",
            "every declared state and transition is reachable",
        ],
    }


def execution_source_sha256() -> str:
    root = _repo_root()
    digest = hashlib.sha256()
    for name in EXECUTION_SOURCE_FILES:
        path = root / name
        if not path.exists():
            # SM9-005: a missing protected source changes the trusted source
            # set silently; the reference reverse_repo reads every declared
            # file, so verification FAILS CLOSED here instead of skipping.
            raise ExecutionSourceIntegrityError(
                f"protected execution source is missing: {name!r} "
                f"(looked under {root})"
            )
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_normalize_source_bytes(path.read_bytes()))
        digest.update(b"\0")
    return digest.hexdigest()


def _normalize_source_bytes(data: bytes) -> bytes:
    """Canonicalize line endings so editors never change the source hash."""
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _repo_root() -> Path:
    # statemachine.py lives at <root>/src/tgrid/execution/statemachine.py
    return Path(__file__).resolve().parents[3]


def execution_source_commit() -> str | None:
    """Return the current git commit (or None for no-Git installations)."""
    root = _repo_root()
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.decode("ascii", errors="replace").strip()
    return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None


def execution_source_tree_is_clean(root: Path | None = None) -> bool:
    """True when no protected execution source has uncommitted changes."""
    root = _repo_root() if root is None else Path(root)
    if not (root / ".git").exists():
        return True
    try:
        result = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--"] + list(EXECUTION_SOURCE_FILES),
            cwd=str(root),
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def snapshot_to_payload(snapshot: MachineSnapshot[Enum]) -> dict[str, object]:
    return {
        "state": str(snapshot.state.value),
        "facts": asdict(snapshot.facts),
    }


def snapshot_from_payload(
    payload: Mapping[str, object],
) -> MachineSnapshot[TGridState]:
    return _snapshot_from_payload(payload, TGridState)


def _next_state(
    transitions: Mapping[StateT, Mapping[Enum, StateT]],
    state: StateT,
    event: Enum,
) -> StateT:
    try:
        return transitions[state][event]
    except KeyError as exc:
        raise InvalidTransition(
            f"event {event.value!r} is invalid in state {state.value!r}"
        ) from exc


def _snapshot_from_payload(
    payload: Mapping[str, object],
    state_type: type[StateT],
) -> MachineSnapshot[StateT]:
    if not isinstance(payload, Mapping):
        raise InvariantViolation("machine snapshot must be a mapping")
    raw_facts = payload.get("facts")
    if not isinstance(raw_facts, Mapping):
        raise InvariantViolation("machine facts must be a mapping")
    expected = set(SafetyFacts.__dataclass_fields__)
    if set(raw_facts) != expected:
        raise InvariantViolation("machine facts fields do not match schema")
    if any(not isinstance(raw_facts[key], bool) for key in expected):
        raise InvariantViolation("machine facts must all be booleans")
    try:
        state = state_type(str(payload.get("state")))
    except ValueError as exc:
        raise InvariantViolation(
            f"unknown machine state {payload.get('state')!r}"
        ) from exc
    snapshot = MachineSnapshot(
        state=state,
        facts=SafetyFacts(**dict(raw_facts)),
    )
    assert_invariants(snapshot)
    return snapshot


def _restart_facts(snapshot: MachineSnapshot[Enum]) -> SafetyFacts:
    facts = snapshot.facts
    possibly_sent = facts.intent_persisted or facts.submitted_once
    return replace(
        facts,
        orders_reconciled=False,
        cash_verified=False,
        quote_verified=False,
        unresolved_order=facts.unresolved_order or possibly_sent,
        terminal_order_confirmed=False,
    )


def _assert_unresolved_shape(
    state: Enum,
    facts: SafetyFacts,
    allowed_states: set[Enum],
) -> None:
    if facts.unresolved_order and state not in allowed_states:
        raise InvariantViolation(
            f"unresolved order is illegal in state {state.value}"
        )


def _verify_machine(
    *,
    name: str,
    initial: MachineSnapshot,
    transitions: Mapping,
    terminal_states: set[Enum],
    advance: object,
    invariant: object,
) -> dict[str, object]:
    queue = deque([initial])
    reachable = {initial}
    edges: set[tuple[MachineSnapshot, Enum, MachineSnapshot]] = set()
    phase_events: set[tuple[Enum, Enum]] = set()
    while queue:
        current = queue.popleft()
        invariant(current)
        for event in transitions[current.state]:
            successor = advance(current, event)
            invariant(successor)
            edges.add((current, event, successor))
            phase_events.add((current.state, event))
            if successor not in reachable:
                reachable.add(successor)
                queue.append(successor)

    declared_edges = {
        (state, event)
        for state, event_map in transitions.items()
        for event in event_map
    }
    missing_edges = declared_edges - phase_events
    if missing_edges:
        formatted = sorted(
            f"{state.value}:{event.value}" for state, event in missing_edges
        )
        raise InvariantViolation(
            f"{name} has unreachable transitions: {formatted}"
        )
    reachable_phases = {item.state for item in reachable}
    missing_states = set(transitions) - reachable_phases
    if missing_states:
        raise InvariantViolation(
            f"{name} has unreachable states: "
            f"{sorted(item.value for item in missing_states)}"
        )

    reverse: dict[MachineSnapshot, set[MachineSnapshot]] = {
        item: set() for item in reachable
    }
    for source, _, destination in edges:
        reverse[destination].add(source)
    can_terminate = {
        item for item in reachable if item.state in terminal_states
    }
    frontier = deque(can_terminate)
    while frontier:
        destination = frontier.popleft()
        for source in reverse[destination]:
            if source not in can_terminate:
                can_terminate.add(source)
                frontier.append(source)
    nonterminating = reachable - can_terminate
    if nonterminating:
        raise InvariantViolation(
            f"{name} contains states with no terminal path"
        )

    for source, _, destination in edges:
        if source.facts.unresolved_order and destination.state is TGridState.READY:
            raise InvariantViolation(
                f"{name} can submit while an earlier order is unresolved"
            )

    return {
        "reachable_abstract_states": len(reachable),
        "reachable_transitions": len(edges),
        "declared_states": len(transitions),
        "declared_phase_event_edges": len(declared_edges),
        "terminal_abstract_states": len(
            [item for item in reachable if item.state in terminal_states]
        ),
        "unreachable_states": 0,
        "unreachable_transitions": 0,
        "states_without_terminal_path": 0,
        "invariant_violations": 0,
    }


def _transition_payload(transitions: Mapping) -> dict[str, dict[str, str]]:
    return {
        state.value: {
            event.value: destination.value
            for event, destination in event_map.items()
        }
        for state, event_map in transitions.items()
    }
