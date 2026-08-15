"""Tests for the append-only T-Lot Audit Log schema (G2-T003).

All tests use temporary SQLite files only; nothing connects to QMT or touches a
real database.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tgrid.persistence.database import initialize
from tgrid.persistence.migrations import (
    BOOTSTRAP_STATEMENTS,
    MAX_SCHEMA_VERSION,
    MIGRATIONS,
    T_LOT_LEDGER_STATEMENTS,
)
from tgrid.risk.exceptions import MigrationError, PersistenceError, SchemaVersionError


def _temp_db_path():
    return str(Path(tempfile.mkdtemp()) / "t_lot_audit_schema.db")


def _tables(conn):
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _triggers(conn):
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
    }


def _history(conn):
    return [
        (int(r[0]), r[1])
        for r in conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        )
    ]


def _insert_t_lot(conn, lot_id, qty=100, status="OPEN"):
    conn.execute(
        "INSERT INTO t_lots (id, symbol, side, qty, entry_price, entry_time,"
        " status, created_at, updated_at)"
        " VALUES (?, '600000.SH', 'BUY', ?, 10.0, 't', ?, 't', 't')",
        (lot_id, qty, status),
    )


def _insert_audit(
    conn,
    audit_id,
    t_lot_id,
    event_type="STATUS_CHANGE",
    from_status="OPEN",
    to_status="CLOSED",
    details_json="{}",
    actor="system",
    created_at="t",
):
    conn.execute(
        "INSERT INTO t_lot_audit_log (id, t_lot_id, event_type, from_status,"
        " to_status, details_json, actor, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            audit_id,
            t_lot_id,
            event_type,
            from_status,
            to_status,
            details_json,
            actor,
            created_at,
        ),
    )


def _build_v2_db(path):
    """Build a hand-made, faithful v2 database (bootstrap + t_lots)."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(";\n".join(BOOTSTRAP_STATEMENTS) + ";")
        conn.executescript(";\n".join(T_LOT_LEDGER_STATEMENTS) + ";")
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at)"
            " VALUES (1, 'bootstrap', 't')"
        )
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at)"
            " VALUES (2, 't_lot_ledger', 't')"
        )
        conn.execute(
            "INSERT INTO application_metadata (key, value, updated_at)"
            " VALUES ('marker', 'PRESERVED_XYZ', 't')"
        )
        conn.execute(
            "INSERT INTO t_lots (id, symbol, side, qty, entry_price, entry_time,"
            " status, created_at, updated_at)"
            " VALUES ('L-MARKER', '600000.SH', 'BUY', 100, 10.0, 't', 'OPEN', 't', 't')"
        )
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
    finally:
        conn.close()


def _build_tampered_v3(path, audit_ddl, extra_sql=""):
    """Build a version-3 database whose audit table uses the given (tampered) DDL."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            ";\n".join(BOOTSTRAP_STATEMENTS)
            + ";\n"
            + ";\n".join(T_LOT_LEDGER_STATEMENTS)
            + ";\n"
            + audit_ddl
            + extra_sql
        )
        for version, name in (
            (1, "bootstrap"),
            (2, "t_lot_ledger"),
            (3, "t_lot_audit_log"),
        ):
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at)"
                " VALUES (?, ?, 't')",
                (version, name),
            )
        conn.execute("PRAGMA user_version = 3")
        conn.commit()
    finally:
        conn.close()
    return path


class TestMigrations(unittest.TestCase):
    def test_max_version_and_history(self):
        self.assertEqual(MAX_SCHEMA_VERSION, 5)
        self.assertEqual(
            [(m.version, m.name) for m in MIGRATIONS],
            [(1, "bootstrap"), (2, "t_lot_ledger"), (3, "t_lot_audit_log"), (4, "order_intents"), (5, "order_reservations")],
        )

    def test_fresh_db_has_audit_table_and_immutable_triggers(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 5)
            tables = _tables(conn)
            self.assertIn("t_lots", tables)
            self.assertIn("t_lot_audit_log", tables)
            self.assertIn("schema_migrations", tables)
            self.assertIn("application_metadata", tables)
            triggers = _triggers(conn)
            self.assertIn("t_lots_no_delete", triggers)
            self.assertIn("t_lot_audit_log_no_update", triggers)
            self.assertIn("t_lot_audit_log_no_delete", triggers)
            self.assertEqual(
                _history(conn),
                [(1, "bootstrap"), (2, "t_lot_ledger"), (3, "t_lot_audit_log"), (4, "order_intents"), (5, "order_reservations")],
            )
        finally:
            conn.close()

    def test_v2_to_v3_upgrade_preserves_metadata_and_t_lots(self):
        path = _temp_db_path()
        _build_v2_db(path)
        conn = initialize(path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertEqual(
                _history(conn),
                [(1, "bootstrap"), (2, "t_lot_ledger"), (3, "t_lot_audit_log"), (4, "order_intents"), (5, "order_reservations")],
            )
            meta = dict(
                conn.execute("SELECT key, value FROM application_metadata").fetchall()
            )
            self.assertEqual(meta["project_name"], "TGrid")
            self.assertEqual(meta["marker"], "PRESERVED_XYZ")
            lots = conn.execute(
                "SELECT id, symbol, qty, status FROM t_lots ORDER BY id"
            ).fetchall()
            self.assertEqual(lots, [("L-MARKER", "600000.SH", 100, "OPEN")])
            self.assertIn("t_lot_audit_log", _tables(conn))
            self.assertIn("t_lot_audit_log_no_update", _triggers(conn))
            self.assertIn("t_lot_audit_log_no_delete", _triggers(conn))
        finally:
            conn.close()

    def test_reopen_idempotent(self):
        path = _temp_db_path()
        conn1 = initialize(path)
        conn1.close()
        conn2 = initialize(path)
        try:
            self.assertEqual(conn2.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertEqual(
                _history(conn2),
                [(1, "bootstrap"), (2, "t_lot_ledger"), (3, "t_lot_audit_log"), (4, "order_intents"), (5, "order_reservations")],
            )
            self.assertEqual(
                conn2.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 5,
            )
        finally:
            conn2.close()

    def test_migration_failure_rolls_back_fully(self):
        import tgrid.persistence.database as database

        original = database.MIGRATIONS
        bad_v3 = (
            database.MIGRATIONS[0],
            database.MIGRATIONS[1],
            type(database.MIGRATIONS[0])(
                version=3,
                name="t_lot_audit_log",
                statements=(
                    "CREATE TABLE t_lot_audit_log (id TEXT PRIMARY KEY)",
                    "THIS IS NOT VALID SQL;",
                ),
            ),
        )
        database.MIGRATIONS = bad_v3
        try:
            path = _temp_db_path()
            with self.assertRaises(MigrationError):
                initialize(path)
        finally:
            database.MIGRATIONS = original
        conn = sqlite3.connect(path)
        try:
            self.assertNotIn("t_lot_audit_log", _tables(conn))
            self.assertNotIn("t_lot_audit_log_no_update", _triggers(conn))
            self.assertNotIn("t_lot_audit_log_no_delete", _triggers(conn))
            self.assertEqual(
                [(int(r[0]), r[1])
                 for r in conn.execute("SELECT version, name FROM schema_migrations")],
                [(1, "bootstrap"), (2, "t_lot_ledger")],
            )
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
        finally:
            conn.close()
        conn = initialize(path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertEqual(
                _history(conn),
                [(1, "bootstrap"), (2, "t_lot_ledger"), (3, "t_lot_audit_log"), (4, "order_intents"), (5, "order_reservations")],
            )
        finally:
            conn.close()


class TestAuditConstraints(unittest.TestCase):
    def _init(self):
        return initialize(_temp_db_path())

    def test_valid_minimal_row_inserts(self):
        conn = self._init()
        try:
            _insert_t_lot(conn, "L1")
            conn.commit()
            _insert_audit(conn, "A1", "L1")
            conn.commit()
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM t_lot_audit_log").fetchone()[0], 1
            )
        finally:
            conn.close()

    def test_dangling_t_lot_id_rejected(self):
        conn = self._init()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                _insert_audit(conn, "A1", "NO_SUCH_LOT")
                conn.commit()
        finally:
            conn.close()

    def test_null_and_empty_required_fields_rejected(self):
        conn = self._init()
        try:
            _insert_t_lot(conn, "L1")
            conn.commit()
            cases = (
                ("id", None),
                ("id", ""),
                ("t_lot_id", None),
                ("t_lot_id", ""),
                ("event_type", None),
                ("event_type", ""),
                ("details_json", None),
                ("details_json", ""),
                ("actor", None),
                ("actor", ""),
                ("created_at", None),
                ("created_at", ""),
            )
            for index, (field, value) in enumerate(cases):
                if field == "id":
                    with self.assertRaises(
                        sqlite3.IntegrityError, msg=f"id={value!r}"
                    ):
                        _insert_audit(conn, value, "L1")
                        conn.commit()
                    continue
                kwargs = {"t_lot_id": "L1", field: value}
                with self.assertRaises(
                    sqlite3.IntegrityError, msg=f"{field}={value!r}"
                ):
                    _insert_audit(conn, f"A{index}", **kwargs)
                    conn.commit()
        finally:
            conn.close()

    def test_each_status_and_null_accepted_invalid_rejected(self):
        conn = self._init()
        try:
            _insert_t_lot(conn, "L1")
            conn.commit()
            statuses = (
                "PENDING_BUY", "OPEN", "PENDING_SELL", "CLOSED", "SUSPENDED",
                "CONVERTED_TO_STRATEGIC", "ERROR",
            )
            for i, status in enumerate(statuses):
                _insert_audit(conn, f"F{i}", "L1", from_status=status, to_status=None)
                _insert_audit(conn, f"T{i}", "L1", from_status=None, to_status=status)
            _insert_audit(conn, "BOTHNULL", "L1", from_status=None, to_status=None)
            conn.commit()
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM t_lot_audit_log").fetchone()[0],
                2 * len(statuses) + 1,
            )
            for bad in ("", "open", "UNKNOWN", "PENDING"):
                with self.assertRaises(sqlite3.IntegrityError):
                    _insert_audit(conn, "BADFROM", "L1", from_status=bad, to_status=None)
                    conn.commit()
                with self.assertRaises(sqlite3.IntegrityError):
                    _insert_audit(conn, "BADTO", "L1", from_status=None, to_status=bad)
                    conn.commit()
        finally:
            conn.close()

    def test_update_rejected_and_row_preserved(self):
        conn = self._init()
        try:
            _insert_t_lot(conn, "L1")
            _insert_audit(conn, "A1", "L1")
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE t_lot_audit_log SET actor = 'x' WHERE id = 'A1'"
                )
                conn.commit()
            self.assertEqual(
                conn.execute(
                    "SELECT actor FROM t_lot_audit_log WHERE id = 'A1'"
                ).fetchone()[0],
                "system",
            )
        finally:
            conn.close()

    def test_delete_rejected_and_row_preserved(self):
        conn = self._init()
        try:
            _insert_t_lot(conn, "L1")
            _insert_audit(conn, "A1", "L1")
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM t_lot_audit_log WHERE id = 'A1'")
                conn.commit()
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM t_lot_audit_log").fetchone()[0], 1
            )
        finally:
            conn.close()


class TestTamperDetection(unittest.TestCase):
    # Column shape matches the real migration-3 audit table exactly; only the
    # constraint/trigger under test is weakened, so the behavioral probes (not a
    # column-mismatch shortcut) are what reject the tampered schema.
    _FULLY_CONSTRAINED_AUDIT_DDL = """
        CREATE TABLE t_lot_audit_log (
          id TEXT NOT NULL PRIMARY KEY CHECK(length(trim(id)) > 0),
          t_lot_id TEXT NOT NULL CHECK(length(trim(t_lot_id)) > 0) REFERENCES t_lots(id),
          event_type TEXT NOT NULL CHECK(length(trim(event_type)) > 0),
          from_status TEXT CHECK(from_status IS NULL OR from_status IN ('PENDING_BUY','OPEN','PENDING_SELL','CLOSED','SUSPENDED','CONVERTED_TO_STRATEGIC','ERROR')),
          to_status TEXT CHECK(to_status IS NULL OR to_status IN ('PENDING_BUY','OPEN','PENDING_SELL','CLOSED','SUSPENDED','CONVERTED_TO_STRATEGIC','ERROR')),
          details_json TEXT NOT NULL CHECK(length(trim(details_json)) > 0),
          actor TEXT NOT NULL CHECK(length(trim(actor)) > 0),
          created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0)
        );
        CREATE TRIGGER t_lot_audit_log_no_update BEFORE UPDATE ON t_lot_audit_log
        BEGIN SELECT RAISE(ABORT, 'immutable'); END;
        CREATE TRIGGER t_lot_audit_log_no_delete BEFORE DELETE ON t_lot_audit_log
        BEGIN SELECT RAISE(ABORT, 'no delete'); END;
        """

    _LEGACY_CONFLICT_SQL = """
        INSERT INTO t_lots (id, symbol, side, qty, entry_price, entry_time, status, created_at, updated_at)
        VALUES ('__tgrid_probe_bad', 'X', 'BUY', 1, 1.0, 't', 'OPEN', 't', 't');
        INSERT INTO t_lot_audit_log (id, t_lot_id, event_type, from_status, to_status, details_json, actor, created_at)
        VALUES ('__tgrid_probe_bad', '__tgrid_probe_bad', 'STATUS_CHANGE', 'OPEN', 'CLOSED', '{}', 'system', 't');
        """

    def test_dropped_table_fails_initialize(self):
        path = _temp_db_path()
        conn = initialize(path)
        conn.execute("DROP TABLE t_lot_audit_log")
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_dropped_update_trigger_fails_initialize(self):
        path = _temp_db_path()
        conn = initialize(path)
        conn.execute("DROP TRIGGER t_lot_audit_log_no_update")
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_dropped_delete_trigger_fails_initialize(self):
        path = _temp_db_path()
        conn = initialize(path)
        conn.execute("DROP TRIGGER t_lot_audit_log_no_delete")
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_missing_column_fails_initialize(self):
        path = _temp_db_path()
        conn = initialize(path)
        conn.execute("ALTER TABLE t_lot_audit_log DROP COLUMN actor")
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_weakened_from_to_status_rejected(self):
        ddl = self._FULLY_CONSTRAINED_AUDIT_DDL.replace(
            "from_status TEXT CHECK(from_status IS NULL OR from_status IN ('PENDING_BUY','OPEN','PENDING_SELL','CLOSED','SUSPENDED','CONVERTED_TO_STRATEGIC','ERROR')),",
            "from_status TEXT,",
        ).replace(
            "to_status TEXT CHECK(to_status IS NULL OR to_status IN ('PENDING_BUY','OPEN','PENDING_SELL','CLOSED','SUSPENDED','CONVERTED_TO_STRATEGIC','ERROR')),",
            "to_status TEXT,",
        )
        with self.assertRaises(SchemaVersionError):
            initialize(_build_tampered_v3(_temp_db_path(), ddl, self._LEGACY_CONFLICT_SQL))

    def test_missing_foreign_key_rejected(self):
        # The weak schema must still be rejected even when a valid t_lot carries
        # the old fixed dangling-probe value: the collision-safe dangling probe
        # must not be fooled by the pre-inserted id (REV-G2T003-001).
        ddl = self._FULLY_CONSTRAINED_AUDIT_DDL.replace(
            "t_lot_id TEXT NOT NULL CHECK(length(trim(t_lot_id)) > 0) REFERENCES t_lots(id),",
            "t_lot_id TEXT NOT NULL CHECK(length(trim(t_lot_id)) > 0),",
        )
        conflict = """
        INSERT INTO t_lots (id, symbol, side, qty, entry_price, entry_time, status, created_at, updated_at)
        VALUES ('__tgrid_probe_no_such_lot', 'X', 'BUY', 1, 1.0, 't', 'OPEN', 't', 't');
        """
        with self.assertRaises(SchemaVersionError):
            initialize(_build_tampered_v3(_temp_db_path(), ddl, conflict))

    def test_wrong_foreign_key_rejected(self):
        ddl = self._FULLY_CONSTRAINED_AUDIT_DDL.replace(
            "REFERENCES t_lots(id),",
            "REFERENCES application_metadata(key),",
        )
        with self.assertRaises(SchemaVersionError):
            initialize(_build_tampered_v3(_temp_db_path(), ddl))

    def test_noop_update_trigger_rejected(self):
        ddl = self._FULLY_CONSTRAINED_AUDIT_DDL.replace(
            "BEGIN SELECT RAISE(ABORT, 'immutable'); END;",
            "BEGIN SELECT 1; END;",
        )
        with self.assertRaises(SchemaVersionError):
            initialize(_build_tampered_v3(_temp_db_path(), ddl))

    def test_noop_delete_trigger_rejected(self):
        ddl = self._FULLY_CONSTRAINED_AUDIT_DDL.replace(
            "BEGIN SELECT RAISE(ABORT, 'no delete'); END;",
            "BEGIN SELECT 1; END;",
        )
        with self.assertRaises(SchemaVersionError):
            initialize(_build_tampered_v3(_temp_db_path(), ddl))

    def test_preinserted_legacy_probe_ids_initialize_succeeds(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            for i, legacy_id in enumerate(
                ("__tgrid_probe_valid", "__tgrid_probe_bad", "__tgrid_probe_delete")
            ):
                _insert_t_lot(conn, legacy_id, 100 + i)
                _insert_audit(conn, legacy_id, legacy_id)
            conn.commit()
            before_lots = conn.execute("SELECT * FROM t_lots ORDER BY id").fetchall()
            before_audit = conn.execute(
                "SELECT * FROM t_lot_audit_log ORDER BY id"
            ).fetchall()
            before_history = conn.execute(
                "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
            ).fetchall()
            before_version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        conn = initialize(path)
        try:
            self.assertEqual(
                conn.execute("SELECT * FROM t_lots ORDER BY id").fetchall(), before_lots
            )
            self.assertEqual(
                conn.execute("SELECT * FROM t_lot_audit_log ORDER BY id").fetchall(),
                before_audit,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
                ).fetchall(),
                before_history,
            )
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0], before_version
            )
        finally:
            conn.close()

    def test_preinserted_fixed_dangling_value_initialize_succeeds(self):
        # A healthy database may legitimately contain a t_lot whose id equals
        # the old fixed dangling-FK probe value; the collision-safe dangling
        # probe must pick a confirmed-absent lot id and initialize() must
        # succeed with every row/history/version unchanged (REV-G2T003-001).
        path = _temp_db_path()
        conn = initialize(path)
        try:
            _insert_t_lot(conn, "__tgrid_probe_no_such_lot")
            _insert_audit(conn, "A1", "__tgrid_probe_no_such_lot")
            conn.commit()
            before_lots = conn.execute("SELECT * FROM t_lots ORDER BY id").fetchall()
            before_audit = conn.execute(
                "SELECT * FROM t_lot_audit_log ORDER BY id"
            ).fetchall()
            before_history = conn.execute(
                "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
            ).fetchall()
            before_version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        conn = initialize(path)
        try:
            self.assertEqual(
                conn.execute("SELECT * FROM t_lots ORDER BY id").fetchall(), before_lots
            )
            self.assertEqual(
                conn.execute("SELECT * FROM t_lot_audit_log ORDER BY id").fetchall(),
                before_audit,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
                ).fetchall(),
                before_history,
            )
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0], before_version
            )
        finally:
            conn.close()

    def test_verifier_probe_leaves_no_rows_or_history_changes(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            _insert_t_lot(conn, "L1")
            _insert_audit(conn, "A1", "L1")
            _insert_audit(conn, "A2", "L1", from_status="SUSPENDED", to_status=None)
            conn.commit()
        finally:
            conn.close()
        before_conn = sqlite3.connect(path)
        before_lots = before_conn.execute("SELECT * FROM t_lots ORDER BY id").fetchall()
        before_audit = before_conn.execute(
            "SELECT * FROM t_lot_audit_log ORDER BY id"
        ).fetchall()
        before_history = before_conn.execute(
            "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        before_version = before_conn.execute("PRAGMA user_version").fetchone()[0]
        before_conn.close()
        conn = initialize(path)
        try:
            self.assertEqual(
                conn.execute("SELECT * FROM t_lots ORDER BY id").fetchall(), before_lots
            )
            self.assertEqual(
                conn.execute("SELECT * FROM t_lot_audit_log ORDER BY id").fetchall(),
                before_audit,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
                ).fetchall(),
                before_history,
            )
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0], before_version
            )
        finally:
            conn.close()


class TestNoBareSqliteLeak(unittest.TestCase):
    def test_malformed_tamper_fails_closed_as_persistence(self):
        path = _temp_db_path()
        conn = initialize(path)
        conn.execute("DROP TABLE t_lot_audit_log")
        conn.commit()
        conn.close()
        with self.assertRaises(PersistenceError):
            initialize(path)


if __name__ == "__main__":
    unittest.main()
