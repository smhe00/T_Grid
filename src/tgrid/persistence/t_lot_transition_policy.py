"""Offline, fail-closed T-Lot business transition policy guard (G2-T005).

G2-T004's :func:`transition_t_lot_status` intentionally only guarantees an
atomic compare-and-set between two valid schema statuses; it does not decide
which business edges are legal.  This module closes that gap: the high-level
caller can no longer pass an arbitrary ``new_status``, only one of a closed set
of business ``action`` values.  The pure :func:`resolve_t_lot_transition` maps an
action + expected status to the unique target status/event_type, and the guarded
:func:`apply_t_lot_transition` resolves first (rejecting before any database
write) then calls the G2-T004 writer exactly once.

Deliberate boundaries: this is the minimal V1 closed set, not a guess at every
future legal edge.  ``KEEP_SUSPENDED`` is a no-op review decision (never faked as
``SUSPENDED -> SUSPENDED``), and ``CONVERT_TO_STRATEGIC`` / ``MANUAL_EXIT`` need
a real explicit manual-authorization mechanism that does not exist yet, so they
are deliberately non-executable here.  ``CLOSED`` / ``CONVERTED_TO_STRATEGIC`` /
``ERROR`` have no automatic outbound edges.
"""

from __future__ import annotations

from dataclasses import dataclass

from tgrid.persistence.migrations import T_LOT_STATUSES
from tgrid.persistence.t_lot_writer import (
    TLotTransitionResult,
    TLotWriterError,
    transition_t_lot_status,
)

# Closed set of business actions that may be submitted by callers.
T_LOT_ACTIONS = frozenset(
    {
        "BUY_FILL_CONFIRMED",  # PENDING_BUY  -> OPEN
        "PREPARE_SELL",        # OPEN         -> PENDING_SELL
        "SELL_FILL_CONFIRMED",  # PENDING_SELL -> CLOSED
        "SUSPEND_T",           # OPEN         -> SUSPENDED
        "RESUME_T",            # SUSPENDED    -> OPEN
    }
)

# Fixed action -> (to_status, event_type).  event_type is derived solely from
# the action; callers never supply it.
_T_LOT_TRANSITIONS = {
    ("BUY_FILL_CONFIRMED", "PENDING_BUY"): ("OPEN", "BUY_FILL_CONFIRMED"),
    ("PREPARE_SELL", "OPEN"): ("PENDING_SELL", "PREPARE_SELL"),
    ("SELL_FILL_CONFIRMED", "PENDING_SELL"): ("CLOSED", "SELL_FILL_CONFIRMED"),
    ("SUSPEND_T", "OPEN"): ("SUSPENDED", "SUSPEND_T"),
    ("RESUME_T", "SUSPENDED"): ("OPEN", "RESUME_T"),
}

# Design §16.1 / §7.1: these require explicit human authorization or are no-op
# review decisions; they must never be disguised as a status transition.
_MANUAL_OR_NOOP_ACTIONS = frozenset(
    {"KEEP_SUSPENDED", "CONVERT_TO_STRATEGIC", "MANUAL_EXIT"}
)

# No automatic outbound edges in V1.
_TERMINAL_STATUSES = frozenset({"CLOSED", "CONVERTED_TO_STRATEGIC", "ERROR"})


class TLotTransitionPolicyError(TLotWriterError):
    """Base class for T-Lot business transition policy failures."""


class TLotTransitionRejectedError(TLotTransitionPolicyError):
    """The action/status combination is not an approved V1 transition."""


@dataclass(frozen=True)
class TLotTransitionPlan:
    """Data-only resolution of an action to a unique transition edge."""

    action: str
    expected_status: str
    to_status: str
    event_type: str


def _require_exact_nonempty_str(value, name: str) -> None:
    """Require an exact non-empty ``str`` without invoking any user dunder."""
    if type(value) is not str or value == "":
        raise TLotTransitionRejectedError(f"{name} must be a non-empty string")


def resolve_t_lot_transition(action, expected_status) -> TLotTransitionPlan:
    """Resolve ``action`` + ``expected_status`` to a unique frozen transition plan.

    Pure: performs no database access.  Any unapproved combination is rejected
    before the writer could be called.
    """
    _require_exact_nonempty_str(action, "action")
    _require_exact_nonempty_str(expected_status, "expected_status")

    if action in _MANUAL_OR_NOOP_ACTIONS:
        raise TLotTransitionRejectedError(
            "manual/no-op actions KEEP_SUSPENDED, CONVERT_TO_STRATEGIC and "
            "MANUAL_EXIT are not executable in V1; they require explicit manual "
            "authorization and must never be faked as a status transition"
        )
    if action not in T_LOT_ACTIONS:
        raise TLotTransitionRejectedError(
            "unknown action; only the closed five-edge action set is allowed"
        )
    if expected_status not in T_LOT_STATUSES:
        raise TLotTransitionRejectedError(
            "expected_status must be one of the seven approved T-Lot statuses"
        )
    if expected_status in _TERMINAL_STATUSES:
        raise TLotTransitionRejectedError(
            "terminal statuses CLOSED, CONVERTED_TO_STRATEGIC and ERROR have no "
            "automatic outbound edge"
        )
    edge = _T_LOT_TRANSITIONS.get((action, expected_status))
    if edge is None:
        raise TLotTransitionRejectedError(
            "action and expected_status do not form an approved transition"
        )
    to_status, event_type = edge
    if to_status == expected_status:
        raise TLotTransitionRejectedError("self-transition is not allowed")
    return TLotTransitionPlan(
        action=action,
        expected_status=expected_status,
        to_status=to_status,
        event_type=event_type,
    )


def apply_t_lot_transition(
    conn,
    *,
    t_lot_id: str,
    expected_status: str,
    action: str,
    audit_id: str,
    details_json: str,
    actor: str,
    occurred_at: str,
) -> TLotTransitionResult:
    """Resolve the policy and apply it through G2-T004's writer exactly once.

    The policy is resolved first, so any unapproved action/status pair is
    rejected with zero database writes.  Approved transitions delegate to
    :func:`transition_t_lot_status`, which owns all transaction/rollback/error
    semantics; writer exceptions (conflict, write failure, BaseException) are
    never swallowed and never retried.
    """
    plan = resolve_t_lot_transition(action, expected_status)
    return transition_t_lot_status(
        conn,
        t_lot_id=t_lot_id,
        expected_status=plan.expected_status,
        new_status=plan.to_status,
        audit_id=audit_id,
        event_type=plan.event_type,
        details_json=details_json,
        actor=actor,
        occurred_at=occurred_at,
    )
