"""Offline, fail-closed atomic T-Lot status transition writer (G2-T004).

The single public primitive :func:`transition_t_lot_status` performs, inside one
SQLite ``BEGIN IMMEDIATE`` transaction, a compare-and-set update of one T-Lot's
``status``/``updated_at`` followed by an immutable append to
``t_lot_audit_log``.  All-or-nothing: any failure rolls the whole transaction
back so a lot can never be observed as "updated but not audited" (or the
reverse).  This primitive deliberately does not define which transitions are
business-valid; a future state-machine task owns that decision.  No create,
delete, generic update, retry, QMT, or trading surface is exposed.

Every failure raises a :class:`PersistenceError` subclass.  Project exceptions
carry no SQL, parameter values, or underlying exception graph (``__cause__`` /
``__context__`` stay ``None``), so injected secrets can never leak.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from tgrid.persistence.migrations import T_LOT_STATUSES
from tgrid.risk.exceptions import PersistenceError


class TLotWriterError(PersistenceError):
    """Base class for atomic T-Lot status transition writer failures."""


class TLotWriterInputError(TLotWriterError):
    """Writer input is invalid: wrong type, empty, out-of-status, or old==new."""


class TLotNotFoundError(TLotWriterError):
    """The referenced T-Lot does not exist."""


class TLotStatusConflictError(TLotWriterError):
    """The T-Lot exists but its current status is not the expected status."""


class TLotWriteFailedError(TLotWriterError):
    """The atomic status+audit write failed and was rolled back."""


@dataclass(frozen=True)
class TLotTransitionResult:
    """Data-only result of a successful atomic transition."""

    t_lot_id: str
    from_status: str
    to_status: str
    audit_id: str
    occurred_at: str


def _require_exact_nonempty_str(value, name: str) -> None:
    """Require an exact ``str`` that is non-empty; never call str/repr/dunders."""
    if type(value) is not str or value == "":
        raise TLotWriterInputError(f"{name} must be a non-empty string")


def _require_status(value, name: str) -> None:
    # Exact non-empty str FIRST: membership on an arbitrary object would call its
    # __eq__ and could leak secrets.  After the exact-str check, `in` only
    # compares str-to-str and never touches user dunders (REV-G2T004-002).
    _require_exact_nonempty_str(value, name)
    if value not in T_LOT_STATUSES:
        raise TLotWriterInputError(
            f"{name} must be one of the seven approved T-Lot statuses"
        )


def _rollback_or_invalidate(conn: sqlite3.Connection) -> None:
    """Roll back the writer's transaction and never return a live half-write.

    The rollback step itself must never mask the primary failure or leak a
    secret.  If rollback cannot be confirmed (connection broken/locked), the
    connection is closed so it can never commit the half-complete write
    (REV-G2T004-001).
    """
    try:
        conn.execute("ROLLBACK")
    except BaseException:
        try:
            conn.close()
        except BaseException:
            pass  # do not mask the primary failure


def transition_t_lot_status(
    conn: sqlite3.Connection,
    *,
    t_lot_id: str,
    expected_status: str,
    new_status: str,
    audit_id: str,
    event_type: str,
    details_json: str,
    actor: str,
    occurred_at: str,
) -> TLotTransitionResult:
    """Atomically CAS a T-Lot status and append one immutable audit row.

    ``conn`` must be an initialized connection with no active transaction; if
    the caller already holds a transaction the writer refuses and never
    commits/rolls back the caller's state.  On success returns a frozen
    data-only result; on any failure raises a :class:`TLotWriterError` subclass
    after a full rollback.
    """
    for name, value in (
        ("t_lot_id", t_lot_id),
        ("audit_id", audit_id),
        ("event_type", event_type),
        ("details_json", details_json),
        ("actor", actor),
        ("occurred_at", occurred_at),
    ):
        _require_exact_nonempty_str(value, name)
    _require_status(expected_status, "expected_status")
    _require_status(new_status, "new_status")
    if expected_status == new_status:
        raise TLotWriterInputError("expected_status and new_status must differ")

    if conn.in_transaction:
        raise TLotWriterInputError(
            "writer requires a connection with no active transaction"
        )

    # The whole CAS+audit+COMMIT is one transaction boundary that covers
    # BaseException: any primary failure first rolls back (or invalidates the
    # connection), then propagates/converts the exception.  KeyboardInterrupt /
    # SystemExit / GeneratorExit propagate unchanged; ordinary exceptions and
    # sqlite errors become a fixed, data-free TLotWriteFailedError.
    primary = None
    in_write = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        in_write = True
        cursor = conn.execute(
            "UPDATE t_lots SET status = ?, updated_at = ?"
            " WHERE id = ? AND status = ?",
            (new_status, occurred_at, t_lot_id, expected_status),
        )
        if cursor.rowcount != 1:
            row = conn.execute(
                "SELECT status FROM t_lots WHERE id = ?", (t_lot_id,)
            ).fetchone()
            if row is None:
                raise TLotNotFoundError("t_lot does not exist")
            raise TLotStatusConflictError(
                "t_lot status does not match the expected status"
            )
        conn.execute(
            "INSERT INTO t_lot_audit_log (id, t_lot_id, event_type, from_status,"
            " to_status, details_json, actor, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                audit_id,
                t_lot_id,
                event_type,
                expected_status,
                new_status,
                details_json,
                actor,
                occurred_at,
            ),
        )
        conn.execute("COMMIT")
    except TLotWriterError as exc:
        primary = exc
    except Exception:
        primary = TLotWriteFailedError("atomic t-lot status write failed")
    except BaseException as exc:
        primary = exc
    if primary is not None:
        if in_write:
            _rollback_or_invalidate(conn)
        raise primary

    return TLotTransitionResult(
        t_lot_id=t_lot_id,
        from_status=expected_status,
        to_status=new_status,
        audit_id=audit_id,
        occurred_at=occurred_at,
    )
