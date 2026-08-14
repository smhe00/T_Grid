"""Fail-closed SQLite database lifecycle for TGrid.

The caller always supplies an explicit database file path; this module never
discovers a path from configuration or account state.  All failures raise a
:class:`tgrid.risk.exceptions.PersistenceError` subclass and never delete,
overwrite, downgrade, or "repair" a database on their own.

Public API:

- :func:`connect` — open a connection with safety PRAGMAs applied (no schema
  work).  The caller is responsible for closing it.
- :func:`initialize` — ``connect`` + integrity check + ordered transactional
  migration + version consistency verification.  Returns an open connection the
  caller must close.
- :func:`open_database` — context manager wrapping :func:`initialize` so the
  connection is always closed on exit.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, List

from tgrid.persistence.migrations import MAX_SCHEMA_VERSION, MIGRATIONS, T_LOT_STATUSES
from tgrid.risk.exceptions import (
    DatabaseIntegrityError,
    DatabaseOpenError,
    MigrationError,
    PersistenceError,
    SchemaVersionError,
)

# Every connection must enable foreign keys and tolerate brief lock contention.
BUSY_TIMEOUT_MS = 5000


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_path(path: str) -> None:
    if not isinstance(path, str) or not path.strip():
        raise DatabaseOpenError("database path must be a non-empty string")
    if os.path.isdir(path):
        raise DatabaseOpenError(f"database path is a directory: {path}")
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            raise DatabaseOpenError(
                f"cannot create database parent directory {parent!r}: {exc}"
            ) from exc


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")


def connect(path: str) -> sqlite3.Connection:
    """Open a connection to ``path`` with safety PRAGMAs applied.

    Does not validate integrity or run migrations.  The caller owns the
    returned connection and must close it.
    """
    _validate_path(path)
    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error as exc:
        raise DatabaseOpenError(f"cannot open database {path!r}: {exc}") from exc
    try:
        _apply_pragmas(conn)
    except sqlite3.Error as exc:
        conn.close()
        raise DatabaseOpenError(f"cannot configure database {path!r}: {exc}") from exc
    return conn


def _check_integrity(conn: sqlite3.Connection) -> None:
    try:
        result = conn.execute("PRAGMA quick_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise DatabaseIntegrityError(f"database integrity check failed: {exc}") from exc
    if result != "ok":
        raise DatabaseIntegrityError(f"database integrity check not ok: {result!r}")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _get_user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _get_recorded_versions(conn: sqlite3.Connection) -> List[int]:
    rows = conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall()
    return [int(row[0]) for row in rows]


def _verify_recorded_versions(recorded: List[int]) -> None:
    # PRAGMA user_version must exactly mirror the recorded history with no gaps
    # (e.g. [1, 3]) and no skipped leading version (e.g. [2] without 1).
    for index, version in enumerate(recorded, start=1):
        if version != index:
            raise SchemaVersionError(
                f"migration history has a gap: expected version {index}, found {version}"
            )


def _verify_state_before_migrations(conn: sqlite3.Connection) -> None:
    user_version = _get_user_version(conn)
    if user_version > MAX_SCHEMA_VERSION:
        raise SchemaVersionError(
            f"database user_version {user_version} exceeds supported "
            f"{MAX_SCHEMA_VERSION}; refusing to downgrade"
        )

    if _table_exists(conn, "schema_migrations"):
        recorded = _get_recorded_versions(conn)
        _verify_recorded_versions(recorded)
        if recorded:
            max_recorded = max(recorded)
            if max_recorded > MAX_SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"migration history records version {max_recorded} above "
                    f"supported {MAX_SCHEMA_VERSION}"
                )
            if max_recorded != user_version:
                raise SchemaVersionError(
                    f"migration history max version {max_recorded} does not match "
                    f"user_version {user_version}"
                )
        elif user_version != 0:
            raise SchemaVersionError(
                f"user_version {user_version} set but schema_migrations is empty"
            )
    elif user_version != 0:
        raise SchemaVersionError(
            f"user_version {user_version} set but schema_migrations table is missing"
        )


def _apply_one_migration(conn: sqlite3.Connection, migration) -> None:
    conn.execute("BEGIN")
    try:
        for statement in migration.statements:
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {migration.version}")
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at)"
            " VALUES (?, ?, ?)",
            (migration.version, migration.name, _utc_now_iso()),
        )
        conn.execute("COMMIT")
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise MigrationError(
            f"migration {migration.version} ({migration.name}) failed and was "
            f"rolled back: {exc}"
        ) from exc


def _apply_migrations(conn: sqlite3.Connection) -> None:
    applied = (
        set(_get_recorded_versions(conn))
        if _table_exists(conn, "schema_migrations")
        else set()
    )
    for migration in MIGRATIONS:
        if migration.version in applied:
            continue  # idempotent: never re-apply a recorded migration
        _apply_one_migration(conn, migration)


def _verify_version_consistency(conn: sqlite3.Connection) -> None:
    user_version = _get_user_version(conn)
    recorded = _get_recorded_versions(conn)
    expected = list(range(1, user_version + 1))
    if recorded != expected:
        raise SchemaVersionError(
            f"post-migration inconsistency: user_version {user_version} but "
            f"recorded versions {recorded}"
        )


def _verify_columns(conn: sqlite3.Connection, table: str, expected) -> None:
    # PRAGMA table_info rows: (cid, name, type, notnull, dflt_value, pk)
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    actual = [(row[1], row[2].upper(), int(row[3]), int(row[5])) for row in rows]
    if actual != expected:
        raise SchemaVersionError(
            f"table {table!r} does not match the bootstrap schema contract: "
            f"expected {expected}, found {actual}"
        )


def _get_unique_index_column_sets(conn: sqlite3.Connection, table: str):
    """Return the set of column tuples covered by full (non-partial) unique indexes.

    Uses structured SQLite metadata (PRAGMA index_list + index_info) rather than
    scanning DDL text, so a UNIQUE constraint on the wrong column or a composite
    unique index is distinguished from a single-column UNIQUE(name).  Partial
    unique indexes are skipped: they enforce uniqueness only for a subset of
    rows, so they cannot satisfy the full-table uniqueness contract.
    """
    column_sets = []
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        # index_list rows: (seq, name, unique, origin, partial)
        name, unique, partial = row[1], int(row[2]), int(row[4])
        if not unique or partial:
            continue
        columns = tuple(
            r[2] for r in conn.execute(f"PRAGMA index_info({name})").fetchall()
        )
        column_sets.append(columns)
    return column_sets


def _verify_name_unique_constraint(conn: sqlite3.Connection) -> None:
    """The UNIQUE constraint must cover exactly ``schema_migrations.name``.

    A unique index on a different column, or a composite unique index that does
    not make ``name`` alone unique, is a contract violation (REV-G0T002-001).
    """
    column_sets = _get_unique_index_column_sets(conn, "schema_migrations")
    if ("name",) not in column_sets:
        raise SchemaVersionError(
            "schema_migrations is missing a single-column UNIQUE constraint on "
            f"'name'; unique indexes found: {column_sets}"
        )


def _verify_check_version_positive(conn: sqlite3.Connection) -> None:
    """Behaviorally verify CHECK(version > 0) actually rejects non-positive values.

    A text/regex match on the DDL is insufficient: ``CHECK(version > 0 OR 1=1)``
    still matches but never rejects.  We probe by attempting to insert version 0
    and a negative version inside a transaction, expecting
    ``sqlite3.IntegrityError``, and roll back so the probe leaves no rows and no
    change to the migration history (REV-G0T002-003).
    """
    conn.execute("BEGIN")
    try:
        for probe_version, probe_name in ((0, "__tgrid_probe_0"), (-1, "__tgrid_probe_neg")):
            try:
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at)"
                    " VALUES (?, ?, ?)",
                    (probe_version, probe_name, "probe"),
                )
            except sqlite3.IntegrityError:
                continue  # constraint correctly rejects the non-positive version
            raise SchemaVersionError(
                f"schema_migrations accepts non-positive version {probe_version}; "
                "CHECK(version > 0) is missing or not enforced"
            )
    finally:
        conn.execute("ROLLBACK")


# (name, type, notnull, pk) — type is matched case-insensitively, so normalize
# to upper-case when comparing (done inside _verify_columns).  SQLite reports
# notnull=0 for PRIMARY KEY columns (they are implicitly non-null), so the
# explicit NOT NULL columns carry notnull=1 while PK columns carry 0.
_SCHEMA_MIGRATIONS_COLUMNS = [
    ("version", "INTEGER", 0, 1),
    ("name", "TEXT", 1, 0),
    ("applied_at", "TEXT", 1, 0),
]
_APPLICATION_METADATA_COLUMNS = [
    ("key", "TEXT", 0, 1),
    ("value", "TEXT", 1, 0),
    ("updated_at", "TEXT", 1, 0),
]

# t_lots (design §6 + §16.1 suspended review fields).  NOT NULL columns are
# created with explicit NOT NULL (including the TEXT PRIMARY KEY, since SQLite
# rowid tables otherwise allow NULL in a primary key column); optional
# numeric/price columns are nullable.
_T_LOTS_COLUMNS = [
    ("id", "TEXT", 1, 1),
    ("symbol", "TEXT", 1, 0),
    ("side", "TEXT", 1, 0),
    ("qty", "INTEGER", 1, 0),
    ("entry_price", "REAL", 1, 0),
    ("entry_time", "TEXT", 1, 0),
    ("target_price", "REAL", 0, 0),
    ("grid_pct", "REAL", 0, 0),
    ("status", "TEXT", 1, 0),
    ("exit_price", "REAL", 0, 0),
    ("exit_time", "TEXT", 0, 0),
    ("entry_order_id", "TEXT", 0, 0),
    ("exit_order_id", "TEXT", 0, 0),
    ("realized_pnl", "REAL", 0, 0),
    ("fees", "REAL", 0, 0),
    ("created_at", "TEXT", 1, 0),
    ("updated_at", "TEXT", 1, 0),
    ("suspended_at", "TEXT", 0, 0),
    ("review_due_at", "TEXT", 0, 0),
    ("last_reviewed_at", "TEXT", 0, 0),
    ("review_reason", "TEXT", 0, 0),
    ("review_status", "TEXT", 0, 0),
]

# Shared with the migration CHECKs and the offline T-Lot writer (single source
# of truth for the seven design statuses).
_ALLOWED_T_LOT_STATUSES = frozenset(T_LOT_STATUSES)


def _trigger_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _valid_t_lot_row(**overrides) -> dict:
    """Return a minimal valid t_lots row as a dict (callers must set a unique id)."""
    row = {
        "id": "__tgrid_probe",
        "symbol": "600000.SH",
        "side": "BUY",
        "qty": 100,
        "entry_price": 10.0,
        "entry_time": "2026-08-14T10:00:00",
        "status": "OPEN",
        "created_at": "2026-08-14T10:00:00",
        "updated_at": "2026-08-14T10:00:00",
    }
    row.update(overrides)
    return row


def _valid_audit_row(**overrides) -> dict:
    """Return a minimal valid t_lot_audit_log row as a dict.

    ``t_lot_id`` must be overridden to an id that actually exists in ``t_lots``
    before the row can be inserted (callers set it from a probe lot).
    """
    row = {
        "id": "__tgrid_probe",
        "t_lot_id": "__tgrid_probe",
        "event_type": "STATUS_CHANGE",
        "from_status": "OPEN",
        "to_status": "CLOSED",
        "details_json": "{}",
        "actor": "system",
        "created_at": "2026-08-14T10:00:00",
    }
    row.update(overrides)
    return row


def _insert_row(conn: sqlite3.Connection, table: str, row: dict) -> None:
    names = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    conn.execute(
        f"INSERT INTO {table} ({names}) VALUES ({placeholders})",
        tuple(row.values()),
    )


def _pick_probe_id(conn: sqlite3.Connection, table: str, tag: str) -> str:
    """Return a probe id confirmed absent from ``table``'s ``id`` column.

    The verifier must never depend on an undeclared reserved id namespace: a
    legitimate user row that happens to use a probe-shaped id must neither fail
    a healthy database (PRIMARY KEY collision on the valid probe) nor let a
    weakened constraint pass (PK collision raising IntegrityError before the
    target CHECK is evaluated).  Probing current rows (including rows inserted
    earlier in this rolled-back transaction) guarantees the chosen id cannot
    collide, so any IntegrityError a probe raises is caused by the probe's own
    target field (REV-G2T002-002).  ``table`` is an internal constant, never
    caller input.
    """
    existing = {
        row[0]
        for row in conn.execute(
            f"SELECT id FROM {table} WHERE id IS NOT NULL"
        ).fetchall()
    }
    candidate = tag
    n = 0
    while candidate in existing:
        n += 1
        candidate = f"{tag}_{n}"
    return candidate


def _expect_integrity(
    conn: sqlite3.Connection, table: str, row: dict, label: str
) -> None:
    """Attempt an invalid insert into ``table``; require sqlite3.IntegrityError."""
    names = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    try:
        conn.execute(
            f"INSERT INTO {table} ({names}) VALUES ({placeholders})",
            tuple(row.values()),
        )
    except sqlite3.IntegrityError:
        return
    raise SchemaVersionError(
        f"{table} accepts invalid value for {label}; constraint is missing or not enforced"
    )


def _expect_accept(
    conn: sqlite3.Connection, table: str, row: dict, label: str
) -> None:
    """Insert a row the design declares valid; the schema must accept it."""
    names = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    try:
        conn.execute(
            f"INSERT INTO {table} ({names}) VALUES ({placeholders})",
            tuple(row.values()),
        )
    except sqlite3.IntegrityError as exc:
        raise SchemaVersionError(
            f"{table} rejects valid value for {label}; a CHECK is too strict"
        ) from exc


def _verify_t_lot_constraints(conn: sqlite3.Connection) -> None:
    """Behaviorally verify t_lots constraints inside a rolled-back transaction.

    Text/DDL matching is insufficient: ``CHECK(qty > 0 OR 1=1)``, an
    unconstrained status column, or a missing numeric storage-type guard would
    match a regex yet still accept bad rows.  Each probe changes exactly one
    field of a valid row and uses an id confirmed absent from t_lots, so the
    only IntegrityError possible is the target field's own CHECK/NOT NULL and a
    PK collision can never masquerade as constraint evidence.  The whole probe
    transaction is rolled back so no probe row, user row, migration history or
    user_version is ever changed (REV-G0T002-003 / REV-G2T002-002/-004).
    """
    conn.execute("BEGIN")
    try:
        # A valid minimal row must insert (constraints do not reject good data).
        _expect_accept(
            conn,
            "t_lots",
            _valid_t_lot_row(id=_pick_probe_id(conn, "t_lots", "__tgrid_probe_valid")),
            label="valid minimal row",
        )

        invalid_probes = (
            ("id NULL", {"id": None}),
            ("id empty", {"id": ""}),
            ("symbol empty", {"symbol": ""}),
            ("side empty", {"side": ""}),
            ("entry_time empty", {"entry_time": ""}),
            ("created_at empty", {"created_at": ""}),
            ("updated_at empty", {"updated_at": ""}),
            ("qty=0", {"qty": 0}),
            ("qty=-1", {"qty": -1}),
            ("qty=1.5 fractional", {"qty": 1.5}),
            ("qty text", {"qty": "abc"}),
            ("entry_price=0", {"entry_price": 0.0}),
            ("entry_price=-1", {"entry_price": -1.0}),
            ("entry_price text", {"entry_price": "abc"}),
            ("status empty", {"status": ""}),
            ("status lowercase", {"status": "open"}),
            ("status unknown", {"status": "UNKNOWN"}),
            ("status partial", {"status": "PENDING"}),
            ("target_price=0", {"target_price": 0.0}),
            ("target_price text", {"target_price": "abc"}),
            ("grid_pct=0", {"grid_pct": 0.0}),
            ("grid_pct text", {"grid_pct": "abc"}),
            ("exit_price=0", {"exit_price": 0.0}),
            ("exit_price text", {"exit_price": "abc"}),
            ("realized_pnl text", {"realized_pnl": "abc"}),
            ("fees negative", {"fees": -1.0}),
            ("fees text", {"fees": "abc"}),
            ("review_status invalid", {"review_status": "BOGUS"}),
        )
        for label, overrides in invalid_probes:
            row = _valid_t_lot_row()
            row.update(overrides)
            if row["id"]:
                # A non-empty id is valid; give it a non-colliding probe id so the
                # NULL/empty id probes (above) are the only ones that change id.
                row["id"] = _pick_probe_id(conn, "t_lots", f"__tgrid_probe_invalid_{label}")
            _expect_integrity(conn, "t_lots", row, label=label)

        # Financial semantics (design §6): realized_pnl may be any numeric
        # (losses/zero/gains); fees must be a non-negative numeric.
        for tag, pnl in (("pnl_neg", -1.5), ("pnl_zero", 0.0), ("pnl_pos", 5.0)):
            _expect_accept(
                conn,
                "t_lots",
                _valid_t_lot_row(id=_pick_probe_id(conn, "t_lots", f"__tgrid_probe_{tag}"), realized_pnl=pnl),
                label=f"realized_pnl={pnl}",
            )
        for tag, fees in (("fees_zero", 0.0), ("fees_pos", 0.5)):
            _expect_accept(
                conn,
                "t_lots",
                _valid_t_lot_row(id=_pick_probe_id(conn, "t_lots", f"__tgrid_probe_{tag}"), fees=fees),
                label=f"fees={fees}",
            )

        # review_status: NULL and each allowed value are accepted.
        allowed_review_statuses = (
            None, "PENDING", "RESUME_T", "KEEP_SUSPENDED",
            "CONVERT_TO_STRATEGIC", "MANUAL_EXIT",
        )
        for index, review_status in enumerate(allowed_review_statuses):
            _expect_accept(
                conn,
                "t_lots",
                _valid_t_lot_row(
                    id=_pick_probe_id(conn, "t_lots", f"__tgrid_probe_review_{index}"),
                    review_status=review_status,
                ),
                label=f"review_status={review_status!r}",
            )
    finally:
        conn.execute("ROLLBACK")


def _verify_t_lot_no_delete_trigger(conn: sqlite3.Connection) -> None:
    """Verify DELETE FROM t_lots is rejected, behaviorally.

    A trigger with the expected name alone is insufficient: a trigger that does
    not actually abort deletes would pass a name check.  We insert a probe row
    (id confirmed absent from t_lots) and require ``sqlite3.IntegrityError`` on
    delete; the whole transaction is rolled back so no probe row remains
    (REV-G2T002 tamper check).
    """
    if not _trigger_exists(conn, "t_lots_no_delete"):
        raise SchemaVersionError(
            "t_lots is missing the 't_lots_no_delete' trigger"
        )
    conn.execute("BEGIN")
    try:
        probe_id = _pick_probe_id(conn, "t_lots", "__tgrid_probe_delete")
        _insert_row(conn, "t_lots", _valid_t_lot_row(id=probe_id))
        try:
            conn.execute("DELETE FROM t_lots WHERE id = ?", (probe_id,))
        except sqlite3.IntegrityError:
            return
        raise SchemaVersionError(
            "DELETE FROM t_lots is not rejected; the no-delete trigger is "
            "missing or does not abort deletes"
        )
    finally:
        conn.execute("ROLLBACK")


def _verify_t_lot_schema(conn: sqlite3.Connection) -> None:
    """Verify the on-disk t_lots schema matches migration 2 (design §6/§16.1).

    Called only when MAX_SCHEMA_VERSION >= 2: a version-2 database missing a
    correct t_lots table, weakened constraints, or a non-enforcing delete
    trigger fails closed and is never silently repaired.
    """
    if MAX_SCHEMA_VERSION < 2:
        return
    if not _table_exists(conn, "t_lots"):
        raise SchemaVersionError("missing table 't_lots'")
    _verify_columns(conn, "t_lots", _T_LOTS_COLUMNS)
    _verify_t_lot_constraints(conn)
    _verify_t_lot_no_delete_trigger(conn)


# t_lot_audit_log (design §6 append-only Audit Log).  id is the explicit NOT
# NULL TEXT PRIMARY KEY; every required text is non-empty; from/to status are
# NULL or one of the seven approved T-Lot statuses; details_json is opaque
# non-empty text in this task (business JSON schema is decoded by a future
# writer/service).
_T_LOT_AUDIT_LOG_COLUMNS = [
    ("id", "TEXT", 1, 1),
    ("t_lot_id", "TEXT", 1, 0),
    ("event_type", "TEXT", 1, 0),
    ("from_status", "TEXT", 0, 0),
    ("to_status", "TEXT", 0, 0),
    ("details_json", "TEXT", 1, 0),
    ("actor", "TEXT", 1, 0),
    ("created_at", "TEXT", 1, 0),
]


def _verify_t_lot_audit_log_foreign_key(conn: sqlite3.Connection) -> None:
    """The audit table must reference ``t_lots(id)`` via ``t_lot_id``.

    Uses structured ``PRAGMA foreign_key_list`` metadata (not DDL text) so a
    missing FK or an FK pointing at the wrong table/column is rejected.
    """
    fks = conn.execute("PRAGMA foreign_key_list(t_lot_audit_log)").fetchall()
    for row in fks:
        # foreign_key_list columns: (id, seq, table, from, to, on_update,
        # on_delete, match)
        if row[2] == "t_lots" and row[3] == "t_lot_id" and row[4] == "id":
            return
    raise SchemaVersionError(
        "t_lot_audit_log is missing foreign key t_lot_id -> t_lots(id)"
    )


def _verify_t_lot_audit_log_constraints(conn: sqlite3.Connection) -> None:
    """Behaviorally verify t_lot_audit_log constraints inside a rollback.

    Every probe changes exactly one field of a valid row and uses a non-colliding
    id, so a PRIMARY KEY / foreign-key collision can never masquerade as target
    constraint evidence; dangling ``t_lot_id`` (no FK) and weakened
    from/to-status checks are caught by the insert probes.
    """
    conn.execute("BEGIN")
    try:
        # A valid audit row must reference a lot that actually exists.
        t_lot_probe_id = _pick_probe_id(conn, "t_lots", "__tgrid_probe_audit_lot")
        _insert_row(conn, "t_lots", _valid_t_lot_row(id=t_lot_probe_id))
        _expect_accept(
            conn,
            "t_lot_audit_log",
            _valid_audit_row(
                id=_pick_probe_id(conn, "t_lot_audit_log", "__tgrid_probe_valid"),
                t_lot_id=t_lot_probe_id,
            ),
            label="valid minimal audit row",
        )

        # A dangling t_lot_id must be confirmed absent from t_lots (not a fixed
        # string): a legitimate user lot could otherwise carry the fixed value,
        # turning the FK probe into a valid reference and rejecting a healthy
        # database (REV-G2T003-001).
        dangling_lot_id = _pick_probe_id(conn, "t_lots", "__tgrid_probe_no_such_lot")
        invalid_probes = (
            ("id NULL", {"id": None}),
            ("id empty", {"id": ""}),
            ("t_lot_id NULL", {"t_lot_id": None}),
            ("t_lot_id empty", {"t_lot_id": ""}),
            ("t_lot_id dangling", {"t_lot_id": dangling_lot_id}),
            ("event_type NULL", {"event_type": None}),
            ("event_type empty", {"event_type": ""}),
            ("from_status empty", {"from_status": ""}),
            ("from_status lowercase", {"from_status": "open"}),
            ("from_status unknown", {"from_status": "UNKNOWN"}),
            ("to_status empty", {"to_status": ""}),
            ("to_status lowercase", {"to_status": "open"}),
            ("to_status unknown", {"to_status": "UNKNOWN"}),
            ("details_json NULL", {"details_json": None}),
            ("details_json empty", {"details_json": ""}),
            ("actor NULL", {"actor": None}),
            ("actor empty", {"actor": ""}),
            ("created_at NULL", {"created_at": None}),
            ("created_at empty", {"created_at": ""}),
        )
        for label, overrides in invalid_probes:
            row = _valid_audit_row(t_lot_id=t_lot_probe_id)
            row.update(overrides)
            if row["id"]:
                row["id"] = _pick_probe_id(
                    conn, "t_lot_audit_log", f"__tgrid_probe_invalid_{label}"
                )
            _expect_integrity(conn, "t_lot_audit_log", row, label=label)

        # Every approved status is valid for both from_status and to_status, and
        # NULL is valid for either.
        allowed_statuses = (
            "PENDING_BUY", "OPEN", "PENDING_SELL", "CLOSED", "SUSPENDED",
            "CONVERTED_TO_STRATEGIC", "ERROR",
        )
        for index, status in enumerate(allowed_statuses):
            _expect_accept(
                conn,
                "t_lot_audit_log",
                _valid_audit_row(
                    id=_pick_probe_id(conn, "t_lot_audit_log", f"__tgrid_probe_from_{index}"),
                    t_lot_id=t_lot_probe_id,
                    from_status=status,
                    to_status=None,
                ),
                label=f"from_status={status}",
            )
            _expect_accept(
                conn,
                "t_lot_audit_log",
                _valid_audit_row(
                    id=_pick_probe_id(conn, "t_lot_audit_log", f"__tgrid_probe_to_{index}"),
                    t_lot_id=t_lot_probe_id,
                    from_status=None,
                    to_status=status,
                ),
                label=f"to_status={status}",
            )
    finally:
        conn.execute("ROLLBACK")


def _verify_t_lot_audit_log_immutable_triggers(conn: sqlite3.Connection) -> None:
    """Verify both immutable triggers reject UPDATE and DELETE, behaviorally.

    A trigger with the expected name alone is insufficient: a no-op trigger
    would pass a name check.  We insert a probe lot + audit row, require
    ``sqlite3.IntegrityError`` on UPDATE and on DELETE, then roll everything
    back so no probe row remains.
    """
    for name in ("t_lot_audit_log_no_update", "t_lot_audit_log_no_delete"):
        if not _trigger_exists(conn, name):
            raise SchemaVersionError(f"t_lot_audit_log is missing the '{name}' trigger")
    conn.execute("BEGIN")
    try:
        t_lot_id = _pick_probe_id(conn, "t_lots", "__tgrid_probe_audit_lot")
        _insert_row(conn, "t_lots", _valid_t_lot_row(id=t_lot_id))
        audit_id = _pick_probe_id(conn, "t_lot_audit_log", "__tgrid_probe_audit_row")
        _insert_row(
            conn,
            "t_lot_audit_log",
            _valid_audit_row(id=audit_id, t_lot_id=t_lot_id),
        )
        try:
            conn.execute(
                "UPDATE t_lot_audit_log SET actor = 'x' WHERE id = ?", (audit_id,)
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise SchemaVersionError(
                "UPDATE of t_lot_audit_log is not rejected; the no-update "
                "trigger is missing or does not abort"
            )
        try:
            conn.execute("DELETE FROM t_lot_audit_log WHERE id = ?", (audit_id,))
        except sqlite3.IntegrityError:
            return
        raise SchemaVersionError(
            "DELETE of t_lot_audit_log is not rejected; the no-delete trigger "
            "is missing or does not abort"
        )
    finally:
        conn.execute("ROLLBACK")


def _verify_t_lot_audit_log_schema(conn: sqlite3.Connection) -> None:
    """Verify the on-disk t_lot_audit_log schema matches migration 3.

    Called only when MAX_SCHEMA_VERSION >= 3: a version-3 database missing the
    audit table, columns, foreign key, constraints, or immutable triggers fails
    closed and is never silently repaired.
    """
    if MAX_SCHEMA_VERSION < 3:
        return
    if not _table_exists(conn, "t_lot_audit_log"):
        raise SchemaVersionError("missing table 't_lot_audit_log'")
    _verify_columns(conn, "t_lot_audit_log", _T_LOT_AUDIT_LOG_COLUMNS)
    _verify_t_lot_audit_log_foreign_key(conn)
    _verify_t_lot_audit_log_constraints(conn)
    _verify_t_lot_audit_log_immutable_triggers(conn)


def _verify_bootstrap_schema(conn: sqlite3.Connection) -> None:
    """Verify the on-disk schema actually matches the migration definitions.

    Numeric version agreement alone does not prove the tables, columns,
    constraints, migration history identities, or application metadata are
    intact; a tampered or partially-dropped database must fail closed rather
    than be silently treated as usable (REV-G0T002-001).
    """
    if not _table_exists(conn, "schema_migrations"):
        raise SchemaVersionError("missing table 'schema_migrations'")
    if not _table_exists(conn, "application_metadata"):
        raise SchemaVersionError("missing table 'application_metadata'")

    _verify_columns(conn, "schema_migrations", _SCHEMA_MIGRATIONS_COLUMNS)
    _verify_columns(conn, "application_metadata", _APPLICATION_METADATA_COLUMNS)

    # Constraint verification must be semantic, not a DDL text search:
    # - UNIQUE must bind exactly to `name` (structured PRAGMA index metadata).
    # - CHECK(version > 0) must actually reject non-positive values (behavioral
    #   probe inside a rolled-back transaction).
    _verify_name_unique_constraint(conn)
    _verify_check_version_positive(conn)

    # Migration history (version, name) must match code MIGRATIONS exactly and
    # every applied_at must be non-empty.
    history = conn.execute(
        "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
    expected_history = [(m.version, m.name) for m in MIGRATIONS]
    actual_history = [(int(row[0]), row[1]) for row in history]
    if actual_history != expected_history:
        raise SchemaVersionError(
            f"migration history mismatch: expected {expected_history}, "
            f"found {actual_history}"
        )
    for row in history:
        if not row[2]:
            raise SchemaVersionError(
                f"migration {row[0]} ({row[1]}) has an empty applied_at"
            )

    # application_metadata must contain exactly one project_name=TGrid with a
    # non-empty updated_at.
    meta = conn.execute(
        "SELECT value, updated_at FROM application_metadata WHERE key = 'project_name'"
    ).fetchall()
    if len(meta) != 1:
        raise SchemaVersionError(
            f"application_metadata must contain exactly one project_name row, "
            f"found {len(meta)}"
        )
    if meta[0][0] != "TGrid":
        raise SchemaVersionError(
            f"application_metadata project_name is {meta[0][0]!r}, expected 'TGrid'"
        )
    if not meta[0][1]:
        raise SchemaVersionError("application_metadata project_name has empty updated_at")


def initialize(path: str) -> sqlite3.Connection:
    """Open, validate, and migrate the database at ``path``.

    Returns an open connection the caller must close.  Any failure closes the
    connection and raises a :class:`PersistenceError` subclass; the on-disk
    file is never deleted or silently modified beyond a rolled-back migration.

    Malformed schema or SQLite query failures (e.g. a tampered table with wrong
    columns) are converted to :class:`SchemaVersionError`, preserving the
    original exception chain, instead of leaking a raw ``sqlite3.Error``
    (REV-G0T002-002).
    """
    conn = connect(path)
    try:
        _check_integrity(conn)
    except BaseException:
        conn.close()
        raise
    try:
        _verify_state_before_migrations(conn)
        _apply_migrations(conn)
        _verify_version_consistency(conn)
        _verify_bootstrap_schema(conn)
        _verify_t_lot_schema(conn)
        _verify_t_lot_audit_log_schema(conn)
    except PersistenceError:
        conn.close()
        raise
    except sqlite3.Error as exc:
        conn.close()
        raise SchemaVersionError(
            f"database schema or query failed: {exc}"
        ) from exc
    return conn


@contextmanager
def open_database(path: str) -> Iterator[sqlite3.Connection]:
    """Context manager yielding an initialized connection, closed on exit."""
    conn = initialize(path)
    try:
        yield conn
    finally:
        conn.close()
