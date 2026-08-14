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

from tgrid.persistence.migrations import MAX_SCHEMA_VERSION, MIGRATIONS
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
