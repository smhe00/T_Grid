"""Tests for the fail-closed SQLite persistence foundation (G0-T002)."""

import ast
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tgrid.persistence import (
    BUSY_TIMEOUT_MS,
    MAX_SCHEMA_VERSION,
    MIGRATIONS,
    connect,
    initialize,
    open_database,
)
from tgrid.risk.exceptions import (
    DatabaseIntegrityError,
    DatabaseOpenError,
    MigrationError,
    PersistenceError,
    SchemaVersionError,
    TGridError,
)

# Gate 2 (G2-T002) legitimately creates t_lots; the remaining domain tables are
# still forbidden until their own Gate-2 tasks.
FORBIDDEN_DOMAIN_TABLES = {
    "order_intent",
    "orders",
    "trades",
    "positions",
    "reservations",
    "audit_log",
}


def _temp_db_path():
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = handle.name
    handle.close()
    os.remove(path)  # ensure initialize() sees a non-existent (fresh) path
    return path


def _read_file_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


class TestInitialize(unittest.TestCase):
    def test_new_database_bootstrap(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("schema_migrations", tables)
            self.assertIn("application_metadata", tables)

            rows = conn.execute(
                "SELECT version, name, applied_at FROM schema_migrations"
            ).fetchall()
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[0][0], 1)
            self.assertEqual(rows[0][1], "bootstrap")
            self.assertTrue(rows[0][2])
            self.assertEqual(rows[1][0], 2)
            self.assertEqual(rows[1][1], "t_lot_ledger")
            self.assertTrue(rows[1][2])
            self.assertEqual(rows[2][0], 3)
            self.assertEqual(rows[2][1], "t_lot_audit_log")
            self.assertTrue(rows[2][2])
            self.assertEqual(rows[3][0], 4)
            self.assertEqual(rows[3][1], "order_intents")
            self.assertTrue(rows[3][2])
            self.assertEqual(rows[4][0], 5)
            self.assertEqual(rows[4][1], "order_reservations")
            self.assertTrue(rows[4][2])

            meta = conn.execute(
                "SELECT key, value, updated_at FROM application_metadata"
            ).fetchall()
            self.assertEqual(len(meta), 1)
            self.assertEqual(meta[0][0], "project_name")
            self.assertEqual(meta[0][1], "TGrid")
            self.assertTrue(meta[0][2])

            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(user_version, 5)
            self.assertEqual(user_version, MAX_SCHEMA_VERSION)
        finally:
            conn.close()

    def test_reinitialize_idempotent(self):
        path = _temp_db_path()
        conn1 = initialize(path)
        conn1.close()
        conn2 = initialize(path)
        try:
            count = conn2.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            self.assertEqual(count, 5)
            meta_count = conn2.execute(
                "SELECT COUNT(*) FROM application_metadata"
            ).fetchone()[0]
            self.assertEqual(meta_count, 1)
            self.assertEqual(conn2.execute("PRAGMA user_version").fetchone()[0], 5)
        finally:
            conn2.close()

    def test_reopen_after_close(self):
        path = _temp_db_path()
        conn = initialize(path)
        conn.close()
        with open_database(path) as reopened:
            self.assertEqual(reopened.execute("PRAGMA user_version").fetchone()[0], 5)

    def test_foreign_keys_and_busy_timeout(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertGreater(
                conn.execute("PRAGMA busy_timeout").fetchone()[0], 0
            )
        finally:
            conn.close()

    def test_journal_mode_safe_on_windows(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            # Only persistent, crash-durable journal modes are acceptable for a
            # file database. OFF and MEMORY provide no rollback durability.
            self.assertIn(mode, {"delete", "wal", "truncate", "persist"})
            self.assertNotIn(mode, {"off", "memory"})
        finally:
            conn.close()

    def test_no_domain_tables_created(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertTrue(FORBIDDEN_DOMAIN_TABLES.isdisjoint(tables))
        finally:
            conn.close()


class TestPathValidation(unittest.TestCase):
    def test_empty_path_rejected(self):
        for bad in ("", "   ", None):
            with self.assertRaises(DatabaseOpenError):
                initialize(bad)

    def test_directory_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DatabaseOpenError):
                initialize(tmp)

    def test_parent_directory_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = os.path.join(tmp, "a", "b", "tgrid.db")
            conn = initialize(nested)
            try:
                self.assertTrue(os.path.isfile(nested))
            finally:
                conn.close()

    def test_uncreatable_parent_directory_fails(self):
        # A path whose parent is a file (not a directory) cannot be created.
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            blocker = handle.name
        try:
            path = os.path.join(blocker, "sub", "tgrid.db")
            with self.assertRaises(DatabaseOpenError):
                initialize(path)
        finally:
            os.remove(blocker)


class TestCorruptionAndVersion(unittest.TestCase):
    def test_corrupt_bytes_rejected_and_file_unchanged(self):
        path = _temp_db_path()
        garbage = b"this is not a sqlite database at all \x00\x01\x02"
        with open(path, "wb") as handle:
            handle.write(garbage)
        before = _read_file_bytes(path)
        with self.assertRaises(DatabaseIntegrityError):
            initialize(path)
        after = _read_file_bytes(path)
        self.assertEqual(before, after)

    def test_empty_file_treated_as_fresh(self):
        path = _temp_db_path()
        with open(path, "wb") as handle:
            handle.write(b"")
        conn = initialize(path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 5)
        finally:
            conn.close()

    def test_future_user_version_rejected(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            conn.execute("PRAGMA user_version = 999")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_future_migration_record_rejected(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            # Simulate a future migration record beyond this build's support.
            conn.execute("PRAGMA user_version = 999")
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at)"
                " VALUES (999, 'future', 'x')"
            )
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_user_version_mismatch_rejected(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            conn.execute("PRAGMA user_version = 0")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_migration_gap_rejected(self):
        # A recorded history [1, 3] (missing 2) is a gap and must be rejected
        # even though every recorded version is within MAX_SCHEMA_VERSION.
        path = _temp_db_path()
        conn = initialize(path)
        try:
            conn.execute("DELETE FROM schema_migrations WHERE version = 2")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_migration_gap_detector(self):
        # Directly exercise the gap detector, since a pure in-range gap cannot be
        # reached through the public API while MAX_SCHEMA_VERSION == 1.
        from tgrid.persistence.database import _verify_recorded_versions

        _verify_recorded_versions([1, 2])  # contiguous is fine
        with self.assertRaises(SchemaVersionError):
            _verify_recorded_versions([1, 3])  # missing 2
        with self.assertRaises(SchemaVersionError):
            _verify_recorded_versions([2])  # missing leading 1

    def test_corruption_raises_persistence_hierarchy(self):
        path = _temp_db_path()
        with open(path, "wb") as handle:
            handle.write(b"garbage-not-sqlite")
        with self.assertRaises(PersistenceError):
            initialize(path)


class TestMigrationRollback(unittest.TestCase):
    def test_migration_failure_rolls_back_completely(self):
        # Monkeypatch database.MIGRATIONS (the global iterated by
        # _apply_migrations) with a failing bootstrap to prove transactional
        # rollback leaves a fresh, re-initializable database.
        import tgrid.persistence.database as database
        from tgrid.persistence.migrations import Migration

        original = database.MIGRATIONS
        failing = (
            Migration(
                version=1,
                name="bootstrap",
                statements=(
                    "CREATE TABLE schema_migrations ("
                    " version INTEGER PRIMARY KEY,"
                    " name TEXT NOT NULL UNIQUE,"
                    " applied_at TEXT NOT NULL"
                    ")",
                    "CREATE TABLE application_metadata ("
                    " key TEXT PRIMARY KEY,"
                    " value TEXT NOT NULL,"
                    " updated_at TEXT NOT NULL"
                    ")",
                    "INSERT INTO application_metadata (key, value, updated_at)"
                    " VALUES ('project_name', 'TGrid', datetime('now'))",
                    "THIS IS NOT VALID SQL;",  # forces a mid-migration failure
                ),
            ),
        )
        database.MIGRATIONS = failing
        try:
            path = _temp_db_path()
            with self.assertRaises(MigrationError):
                initialize(path)
        finally:
            database.MIGRATIONS = original

        # After rollback, the file must be re-initializable deterministically.
        conn = initialize(path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 5)
            count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            self.assertEqual(count, 5)
        finally:
            conn.close()


class TestExceptionHierarchy(unittest.TestCase):
    def test_persistence_exceptions_are_distinct_and_catchable(self):
        self.assertTrue(issubclass(PersistenceError, TGridError))
        for exc in (
            DatabaseOpenError,
            DatabaseIntegrityError,
            SchemaVersionError,
            MigrationError,
        ):
            self.assertTrue(issubclass(exc, PersistenceError))

        with self.assertRaises(DatabaseOpenError):
            raise DatabaseOpenError("open failed")
        with self.assertRaises(DatabaseIntegrityError):
            raise DatabaseIntegrityError("integrity failed")
        with self.assertRaises(SchemaVersionError):
            raise SchemaVersionError("version mismatch")
        with self.assertRaises(MigrationError):
            raise MigrationError("migration failed")


class TestSchemaContractValidation(unittest.TestCase):
    """REV-G0T002-001: numeric version agreement alone is not sufficient."""

    def _db(self):
        path = _temp_db_path()
        conn = initialize(path)
        conn.close()
        return path

    def test_missing_metadata_table_rejected(self):
        path = self._db()
        conn = sqlite3.connect(path)
        conn.execute("DROP TABLE application_metadata")
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_missing_project_name_rejected(self):
        path = self._db()
        conn = sqlite3.connect(path)
        conn.execute("DELETE FROM application_metadata WHERE key = 'project_name'")
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_tampered_project_name_rejected(self):
        path = self._db()
        conn = sqlite3.connect(path)
        conn.execute(
            "UPDATE application_metadata SET value = 'NotTGrid' WHERE key = 'project_name'"
        )
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_tampered_migration_name_rejected(self):
        path = self._db()
        conn = sqlite3.connect(path)
        conn.execute(
            "UPDATE schema_migrations SET name = 'not_bootstrap' WHERE version = 1"
        )
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_missing_column_rejected(self):
        # Rebuild schema_migrations without the `name` column but keep
        # user_version=1 so numeric checks alone would pass.
        path = self._db()
        conn = sqlite3.connect(path)
        conn.execute("DROP TABLE schema_migrations")
        conn.execute(
            "CREATE TABLE schema_migrations ("
            " version INTEGER PRIMARY KEY CHECK(version > 0),"
            " applied_at TEXT NOT NULL"
            ")"
        )
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_wrong_table_structure_rejected(self):
        # Replace schema_migrations with an entirely different table shape.
        path = self._db()
        conn = sqlite3.connect(path)
        conn.execute("DROP TABLE schema_migrations")
        conn.execute("CREATE TABLE schema_migrations (wrong INTEGER)")
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_unique_on_wrong_column_rejected(self):
        # UNIQUE(applied_at) instead of UNIQUE(name): column shape is fine and a
        # UNIQUE is present, but it does not bind to `name`.
        path = self._db()
        conn = sqlite3.connect(path)
        conn.execute("DROP TABLE schema_migrations")
        conn.execute(
            "CREATE TABLE schema_migrations ("
            " version INTEGER PRIMARY KEY CHECK(version > 0),"
            " name TEXT NOT NULL,"
            " applied_at TEXT NOT NULL UNIQUE"
            ")"
        )
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_composite_unique_without_name_unique_rejected(self):
        # UNIQUE(name, applied_at) does not make `name` alone unique.
        path = self._db()
        conn = sqlite3.connect(path)
        conn.execute("DROP TABLE schema_migrations")
        conn.execute(
            "CREATE TABLE schema_migrations ("
            " version INTEGER PRIMARY KEY CHECK(version > 0),"
            " name TEXT NOT NULL,"
            " applied_at TEXT NOT NULL,"
            " UNIQUE(name, applied_at)"
            ")"
        )
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_partial_unique_name_index_rejected(self):
        # A partial unique index on `name` enforces uniqueness only for a subset
        # of rows and must not satisfy the full-table UNIQUE(name) contract.
        path = self._db()
        conn = sqlite3.connect(path)
        conn.execute("DROP TABLE schema_migrations")
        conn.execute(
            "CREATE TABLE schema_migrations ("
            " version INTEGER PRIMARY KEY CHECK(version > 0),"
            " name TEXT NOT NULL,"
            " applied_at TEXT NOT NULL"
            ")"
        )
        conn.execute(
            "CREATE UNIQUE INDEX uq_partial_name ON schema_migrations(name)"
            " WHERE version > 100"
        )
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_valid_schema_validation_preserves_history(self):
        # A valid database must pass validation without altering its migration
        # history (the CHECK probe must leave no rows behind).
        path = _temp_db_path()
        conn = initialize(path)
        before = conn.execute(
            "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        conn.close()
        conn = initialize(path)
        after = conn.execute(
            "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        conn.close()
        self.assertEqual(before, after)
        self.assertEqual(
            [(row[0], row[1]) for row in after],
            [(1, "bootstrap"), (2, "t_lot_ledger"), (3, "t_lot_audit_log"), (4, "order_intents"), (5, "order_reservations")],
        )
        self.assertTrue(all(row[2] for row in after))


class TestMalformedTableBoundary(unittest.TestCase):
    """REV-G0T002-002: malformed tables must not leak raw sqlite3 errors."""

    def _make_db(self, ddl, user_version):
        path = _temp_db_path()
        conn = initialize(path)
        conn.execute("DROP TABLE schema_migrations")
        conn.execute(ddl)
        conn.execute(f"PRAGMA user_version = {user_version}")
        conn.commit()
        conn.close()
        return path

    def test_wrong_column_schema_migrations_raises_persistence_error(self):
        path = self._make_db("CREATE TABLE schema_migrations (wrong INTEGER)", 1)
        with self.assertRaises(PersistenceError):
            initialize(path)
        # It must specifically be a SchemaVersionError, not a raw sqlite3.Error.
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_wrong_column_application_metadata_raises_persistence_error(self):
        path = _temp_db_path()
        conn = initialize(path)
        conn.execute("DROP TABLE application_metadata")
        conn.execute("CREATE TABLE application_metadata (wrong INTEGER)")
        conn.commit()
        conn.close()
        with self.assertRaises(PersistenceError):
            initialize(path)

    def test_raw_sqlite_error_is_not_leaked(self):
        path = self._make_db("CREATE TABLE schema_migrations (wrong INTEGER)", 1)
        with self.assertRaises(SchemaVersionError) as ctx:
            initialize(path)
        # The original chain should be preserved.
        self.assertIsNotNone(ctx.exception.__cause__)


class TestVersionCheckConstraint(unittest.TestCase):
    """REV-G0T002-003: schema_migrations.version must be > 0."""

    def _db_conn(self):
        path = _temp_db_path()
        conn = initialize(path)
        return conn

    def test_insert_version_zero_rejected(self):
        conn = self._db_conn()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at)"
                    " VALUES (0, 'zero', 'x')"
                )
        finally:
            conn.close()

    def test_insert_negative_version_rejected(self):
        conn = self._db_conn()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at)"
                    " VALUES (-1, 'neg', 'x')"
                )
        finally:
            conn.close()

    def test_missing_check_constraint_detected(self):
        # Rebuild schema_migrations without the CHECK constraint.
        path = _temp_db_path()
        conn = initialize(path)
        conn.execute("DROP TABLE schema_migrations")
        conn.execute(
            "CREATE TABLE schema_migrations ("
            " version INTEGER PRIMARY KEY,"
            " name TEXT NOT NULL UNIQUE,"
            " applied_at TEXT NOT NULL"
            ")"
        )
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_weak_check_always_true_rejected(self):
        # CHECK(version > 0 OR 1=1) is always true and must be rejected by the
        # behavioral probe (a text match would wrongly accept it).
        path = _temp_db_path()
        conn = initialize(path)
        conn.execute("DROP TABLE schema_migrations")
        conn.execute(
            "CREATE TABLE schema_migrations ("
            " version INTEGER PRIMARY KEY CHECK(version > 0 OR 1=1),"
            " name TEXT NOT NULL UNIQUE,"
            " applied_at TEXT NOT NULL"
            ")"
        )
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)


class TestForbiddenApiScan(unittest.TestCase):
    """REV-G0T002-004: AST-based safety scan across the whole package."""

    def _package_files(self):
        project_root = Path(__file__).resolve().parents[2]
        src = project_root / "src" / "tgrid"
        return sorted(p for p in src.rglob("*.py") if "__pycache__" not in p.parts)

    def test_no_assert_anywhere_in_package(self):
        for path in self._package_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            asserts = [
                (node.lineno, node.col_offset)
                for node in ast.walk(tree)
                if isinstance(node, ast.Assert)
            ]
            self.assertEqual([], asserts, f"assert found in {path}: {asserts}")

    def test_no_xtquant_import(self):
        for path in self._package_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotEqual(
                            "xtquant", alias.name.split(".")[0],
                            f"xtquant import in {path}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(
                        "xtquant", (node.module or "").split(".")[0],
                        f"xtquant import in {path}",
                    )

    def test_no_order_or_cancel_calls(self):
        # INV-009 / §19: business code must never call the real broker API
        # (order_stock / cancel_order_stock).  Gate 4's SimBroker defines its
        # own place_order/cancel_order methods on an injected fake; those are
        # the sanctioned dry-run surface, not real XtQuant calls.
        for path in self._package_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = None
                    if isinstance(func, ast.Attribute):
                        name = func.attr
                    elif isinstance(func, ast.Name):
                        name = func.id
                    self.assertNotIn(
                        name, {"order_stock", "cancel_order_stock"},
                        f"forbidden call {name} in {path}",
                    )


if __name__ == "__main__":
    unittest.main()
