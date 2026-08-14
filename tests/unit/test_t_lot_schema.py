"""Tests for the transactional T-Lot Ledger schema (G2-T002).

All tests use temporary SQLite files only; nothing connects to QMT or touches a
real database.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tgrid.persistence.database import initialize, open_database
from tgrid.persistence.migrations import MAX_SCHEMA_VERSION, MIGRATIONS
from tgrid.risk.exceptions import MigrationError, PersistenceError, SchemaVersionError


def _temp_db_path():
    return str(Path(tempfile.mkdtemp()) / "t_lot_schema.db")


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
        for r in conn.execute("SELECT version, name FROM schema_migrations ORDER BY version")
    ]


def _valid_row(suffix="1", status="OPEN", **overrides):
    row = {
        "id": f"L{suffix}",
        "symbol": "600000.SH",
        "side": "BUY",
        "qty": 100,
        "entry_price": 10.0,
        "entry_time": "2026-08-14T10:00:00",
        "status": status,
        "created_at": "2026-08-14T10:00:00",
        "updated_at": "2026-08-14T10:00:00",
    }
    row.update(overrides)
    return row


def _insert(conn, row):
    names = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    conn.execute(
        f"INSERT INTO t_lots ({names}) VALUES ({placeholders})",
        tuple(row.values()),
    )


class TestMigrations(unittest.TestCase):
    def test_max_version_and_history(self):
        self.assertEqual(MAX_SCHEMA_VERSION, 3)
        self.assertEqual(
            [(m.version, m.name) for m in MIGRATIONS],
            [(1, "bootstrap"), (2, "t_lot_ledger"), (3, "t_lot_audit_log")],
        )

    def test_fresh_db_has_t_lots_and_trigger(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 3)
            tables = _tables(conn)
            self.assertIn("t_lots", tables)
            self.assertIn("schema_migrations", tables)
            self.assertIn("application_metadata", tables)
            self.assertIn("t_lots_no_delete", _triggers(conn))
            self.assertEqual(
                _history(conn),
                [(1, "bootstrap"), (2, "t_lot_ledger"), (3, "t_lot_audit_log")],
            )
        finally:
            conn.close()

    def test_v1_to_v2_upgrade_preserves_metadata(self):
        # Build a hand-made v1 database with a marker metadata value, then let
        # initialize() upgrade it atomically to v2.
        path = _temp_db_path()
        conn = sqlite3.connect(path)
        try:
            conn.executescript(
                """
                CREATE TABLE schema_migrations (
                  version INTEGER PRIMARY KEY CHECK(version > 0),
                  name TEXT NOT NULL UNIQUE,
                  applied_at TEXT NOT NULL
                );
                CREATE TABLE application_metadata (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                INSERT INTO schema_migrations VALUES (1, 'bootstrap', 'v1-time');
                INSERT INTO application_metadata VALUES
                  ('project_name', 'TGrid', 'v1-time'),
                  ('marker', 'PRESERVED_XYZ', 'v1-time');
                PRAGMA user_version = 1;
                """
            )
            conn.commit()
        finally:
            conn.close()
        conn = initialize(path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(
                _history(conn),
                [(1, "bootstrap"), (2, "t_lot_ledger"), (3, "t_lot_audit_log")],
            )
            meta = dict(
                conn.execute("SELECT key, value FROM application_metadata").fetchall()
            )
            self.assertEqual(meta["project_name"], "TGrid")
            self.assertEqual(meta["marker"], "PRESERVED_XYZ")
            self.assertIn("t_lots", _tables(conn))
            self.assertIn("t_lots_no_delete", _triggers(conn))
        finally:
            conn.close()

    def test_reopen_idempotent(self):
        path = _temp_db_path()
        conn1 = initialize(path)
        conn1.close()
        conn2 = initialize(path)
        try:
            self.assertEqual(conn2.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(
                _history(conn2),
                [(1, "bootstrap"), (2, "t_lot_ledger"), (3, "t_lot_audit_log")],
            )
            count = conn2.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            self.assertEqual(count, 3)
        finally:
            conn2.close()

    def test_migration_failure_rolls_back_fully(self):
        # Replace migration 2 with one that creates t_lots then hits invalid SQL:
        # the whole migration must roll back to a clean v1 database.
        import tgrid.persistence.database as database

        original = database.MIGRATIONS
        bad_v2 = (
            database.MIGRATIONS[0],
            type(database.MIGRATIONS[0])(
                version=2,
                name="t_lot_ledger",
                statements=(
                    "CREATE TABLE t_lots (id TEXT PRIMARY KEY)",
                    "THIS IS NOT VALID SQL;",
                ),
            ),
        )
        database.MIGRATIONS = bad_v2
        try:
            path = _temp_db_path()
            with self.assertRaises(MigrationError):
                initialize(path)
        finally:
            database.MIGRATIONS = original
        # After rollback the file is a clean v1 database: no t_lots, no trigger,
        # no version-2 history.
        conn = sqlite3.connect(path)
        try:
            self.assertNotIn("t_lots", _tables(conn))
            self.assertNotIn("t_lots_no_delete", _triggers(conn))
            self.assertEqual(
                [(int(r[0]), r[1])
                 for r in conn.execute("SELECT version, name FROM schema_migrations")],
                [(1, "bootstrap")],
            )
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
        finally:
            conn.close()
        # Fixing migration 2 (restored) allows a clean re-upgrade to the latest
        # schema (version 3 includes the audit log migration).
        conn = initialize(path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(
                _history(conn),
                [(1, "bootstrap"), (2, "t_lot_ledger"), (3, "t_lot_audit_log")],
            )
        finally:
            conn.close()


class TestTotsConstraints(unittest.TestCase):
    def _init(self):
        return initialize(_temp_db_path())

    def test_valid_minimal_row_inserts(self):
        conn = self._init()
        try:
            _insert(conn, _valid_row())
            conn.commit()
            self.assertEqual(
                conn.execute("SELECT count(*) FROM t_lots").fetchone()[0], 1
            )
        finally:
            conn.close()

    def test_full_row_with_optional_and_suspended_fields(self):
        conn = self._init()
        try:
            _insert(
                conn,
                _valid_row(
                    suffix="full",
                    status="SUSPENDED",
                    target_price=12.0,
                    grid_pct=1.5,
                    exit_price=None,
                    exit_time=None,
                    entry_order_id="E1",
                    exit_order_id=None,
                    realized_pnl=None,
                    fees=0.5,
                    suspended_at="2026-08-14T12:00:00",
                    review_due_at="2026-08-15T12:00:00",
                    last_reviewed_at=None,
                    review_reason="price gap",
                    review_status="KEEP_SUSPENDED",
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT status, review_status, review_reason FROM t_lots"
            ).fetchone()
            self.assertEqual(row[0], "SUSPENDED")
            self.assertEqual(row[1], "KEEP_SUSPENDED")
            self.assertEqual(row[2], "price gap")
        finally:
            conn.close()

    def test_each_status_accepted(self):
        conn = self._init()
        try:
            for i, status in enumerate(
                ("PENDING_BUY", "OPEN", "PENDING_SELL", "CLOSED", "SUSPENDED",
                 "CONVERTED_TO_STRATEGIC", "ERROR")
            ):
                _insert(conn, _valid_row(suffix=str(i), status=status))
            conn.commit()
            self.assertEqual(
                conn.execute("SELECT count(*) FROM t_lots").fetchone()[0], 7
            )
        finally:
            conn.close()

    def test_unknown_lowercase_empty_status_rejected(self):
        conn = self._init()
        try:
            for status in ("", "open", "UNKNOWN", "PENDING"):
                with self.assertRaises(sqlite3.IntegrityError):
                    _insert(conn, _valid_row(suffix=status or "e", status=status))
                    conn.commit()
        finally:
            conn.close()

    def test_qty_zero_and_negative_rejected(self):
        conn = self._init()
        try:
            for qty in (0, -1):
                with self.assertRaises(sqlite3.IntegrityError):
                    _insert(conn, _valid_row(suffix=str(qty), qty=qty))
                    conn.commit()
        finally:
            conn.close()

    def test_entry_price_zero_and_negative_rejected(self):
        conn = self._init()
        try:
            for price in (0.0, -1.0):
                with self.assertRaises(sqlite3.IntegrityError):
                    _insert(conn, _valid_row(suffix=str(price), entry_price=price))
                    conn.commit()
        finally:
            conn.close()

    def test_empty_required_text_rejected(self):
        conn = self._init()
        try:
            for field in ("symbol", "side", "entry_time", "status", "created_at", "updated_at"):
                row = _valid_row(suffix=field)
                row[field] = ""
                with self.assertRaises(sqlite3.IntegrityError):
                    _insert(conn, row)
                    conn.commit()
        finally:
            conn.close()

    def test_optional_price_fields_positive_numeric_when_present(self):
        # target/grid/exit prices must be positive numeric when present; text can
        # never exploit storage-class ordering to bypass `> 0`.
        conn = self._init()
        try:
            for field in ("target_price", "grid_pct", "exit_price"):
                for bad in (0.0, -1.0, "abc"):
                    with self.assertRaises(sqlite3.IntegrityError):
                        _insert(conn, _valid_row(suffix=f"{field}{bad}", **{field: bad}))
                        conn.commit()
        finally:
            conn.close()

    def test_realized_pnl_accepts_any_numeric_rejects_text(self):
        # Design §6: realized_pnl is REAL; actual fills can be negative, zero or
        # positive.  Only a non-numeric (text) storage class is invalid.
        conn = self._init()
        try:
            for pnl in (-1.5, 0.0, 5.0):
                _insert(conn, _valid_row(suffix=f"pnl{pnl}", realized_pnl=pnl))
            conn.commit()
            self.assertEqual(
                conn.execute("SELECT count(*) FROM t_lots").fetchone()[0], 3
            )
            with self.assertRaises(sqlite3.IntegrityError):
                _insert(conn, _valid_row(suffix="pnlbad", realized_pnl="abc"))
                conn.commit()
        finally:
            conn.close()

    def test_fees_accepts_zero_and_positive_rejects_negative_and_text(self):
        # Design §6: fees is REAL; a fill can have zero fees.  Negative or text
        # fees are invalid.
        conn = self._init()
        try:
            for fees in (0.0, 0.5):
                _insert(conn, _valid_row(suffix=f"fees{fees}", fees=fees))
            conn.commit()
            self.assertEqual(
                conn.execute("SELECT count(*) FROM t_lots").fetchone()[0], 2
            )
            for bad in (-1.0, "abc"):
                with self.assertRaises(sqlite3.IntegrityError):
                    _insert(conn, _valid_row(suffix=f"fees{bad}", fees=bad))
                    conn.commit()
        finally:
            conn.close()

    def test_review_status_null_and_allowed_accepted_invalid_rejected(self):
        conn = self._init()
        try:
            for index, rs in enumerate(
                (None, "PENDING", "RESUME_T", "KEEP_SUSPENDED",
                 "CONVERT_TO_STRATEGIC", "MANUAL_EXIT")
            ):
                _insert(conn, _valid_row(suffix=f"review{index}", review_status=rs))
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                _insert(conn, _valid_row(suffix="reviewbad", review_status="BOGUS"))
                conn.commit()
        finally:
            conn.close()

    def test_null_and_empty_id_rejected(self):
        conn = self._init()
        try:
            for bad_id in (None, ""):
                with self.assertRaises(sqlite3.IntegrityError):
                    _insert(conn, _valid_row(suffix="id", id=bad_id))
                    conn.commit()
        finally:
            conn.close()

    def test_fractional_qty_rejected(self):
        # qty is a count of shares: only SQLite integer storage is valid.
        conn = self._init()
        try:
            for bad in (1.5, "abc"):
                with self.assertRaises(sqlite3.IntegrityError):
                    _insert(conn, _valid_row(suffix=f"qty{bad}", qty=bad))
                    conn.commit()
        finally:
            conn.close()

    def test_text_entry_price_rejected(self):
        # entry_price must be numeric storage class; text 'abc' is lexically
        # greater than every number and would pass a bare `> 0` check.
        conn = self._init()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                _insert(conn, _valid_row(suffix="price", entry_price="abc"))
                conn.commit()
        finally:
            conn.close()

    def test_delete_rejected_and_row_preserved(self):
        conn = self._init()
        try:
            _insert(conn, _valid_row())
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM t_lots WHERE id = 'L1'")
                conn.commit()
            self.assertEqual(
                conn.execute("SELECT count(*) FROM t_lots").fetchone()[0], 1
            )
        finally:
            conn.close()


class TestTamperDetection(unittest.TestCase):
    # Column shape matches the real migration-2 t_lots exactly; only the
    # constraint under test is weakened.  This keeps _verify_columns passing so
    # the behavioral probes (not a column-mismatch shortcut) are what reject the
    # tampered schema.
    _FULLY_CONSTRAINED_T_LOTS = """
        CREATE TABLE t_lots (
          id TEXT NOT NULL PRIMARY KEY CHECK(length(trim(id)) > 0),
          symbol TEXT NOT NULL, side TEXT NOT NULL,
          qty INTEGER NOT NULL CHECK(typeof(qty) = 'integer' AND qty > 0),
          entry_price REAL NOT NULL CHECK(typeof(entry_price) IN ('integer','real') AND entry_price > 0),
          entry_time TEXT NOT NULL,
          target_price REAL, grid_pct REAL,
          status TEXT NOT NULL CHECK(status IN ('PENDING_BUY','OPEN','PENDING_SELL','CLOSED','SUSPENDED','CONVERTED_TO_STRATEGIC','ERROR')),
          exit_price REAL, exit_time TEXT,
          entry_order_id TEXT, exit_order_id TEXT,
          realized_pnl REAL, fees REAL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          suspended_at TEXT, review_due_at TEXT, last_reviewed_at TEXT,
          review_reason TEXT,
          review_status TEXT CHECK(review_status IS NULL OR review_status IN ('PENDING','RESUME_T','KEEP_SUSPENDED','CONVERT_TO_STRATEGIC','MANUAL_EXIT'))
        );
        CREATE TRIGGER t_lots_no_delete BEFORE DELETE ON t_lots
        BEGIN SELECT RAISE(ABORT, 'no delete'); END;
        """

    def _drop_trigger_fails_initialize(self):
        path = _temp_db_path()
        conn = initialize(path)
        conn.execute("DROP TRIGGER t_lots_no_delete")
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_dropped_table_fails_initialize(self):
        path = _temp_db_path()
        conn = initialize(path)
        conn.execute("DROP TABLE t_lots")
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def test_dropped_trigger_fails_initialize(self):
        self._drop_trigger_fails_initialize()

    def test_missing_column_fails_initialize(self):
        path = _temp_db_path()
        conn = initialize(path)
        conn.execute("ALTER TABLE t_lots DROP COLUMN review_status")
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            initialize(path)

    def _tampered_v2_db(self, t_lots_ddl, extra_sql=""):
        """Build a version-2 database whose t_lots shape matches the column
        contract but whose constraints are weakened exactly as specified."""
        path = _temp_db_path()
        conn = sqlite3.connect(path)
        try:
            conn.executescript(
                """
                CREATE TABLE schema_migrations (
                  version INTEGER PRIMARY KEY CHECK(version > 0),
                  name TEXT NOT NULL UNIQUE, applied_at TEXT NOT NULL
                );
                CREATE TABLE application_metadata (
                  key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                INSERT INTO schema_migrations VALUES (1, 'bootstrap', 't');
                INSERT INTO schema_migrations VALUES (2, 't_lot_ledger', 't');
                INSERT INTO application_metadata VALUES ('project_name', 'TGrid', 't');
                """
                + t_lots_ddl
                + extra_sql
                + "PRAGMA user_version = 2;"
            )
            conn.commit()
        finally:
            conn.close()
        return path

    _LEGACY_PROBE_ID_ROW = """
        INSERT INTO t_lots (id, symbol, side, qty, entry_price, entry_time, status, created_at, updated_at)
        VALUES ('__tgrid_probe_bad', 'X', 'BUY', 1, 1.0, 't', 'OPEN', 't', 't');
        """

    def test_fake_weakened_qty_constraint_rejected(self):
        # A tampered t_lots whose qty CHECK is always-true must fail the
        # behavioral probe even though the column shape is intact.  Pre-insert a
        # row whose id collides with the legacy fixed probe id to prove the
        # verifier neither relies on a reserved id namespace nor gets fooled by a
        # PRIMARY KEY collision (REV-G2T002-002).
        ddl = self._FULLY_CONSTRAINED_T_LOTS.replace(
            "qty INTEGER NOT NULL CHECK(typeof(qty) = 'integer' AND qty > 0),",
            "qty INTEGER NOT NULL CHECK(qty > 0 OR 1=1),",
        )
        with self.assertRaises(SchemaVersionError):
            initialize(self._tampered_v2_db(ddl, self._LEGACY_PROBE_ID_ROW))

    def test_fake_always_true_status_constraint_rejected(self):
        ddl = self._FULLY_CONSTRAINED_T_LOTS.replace(
            "status TEXT NOT NULL CHECK(status IN ('PENDING_BUY','OPEN','PENDING_SELL','CLOSED','SUSPENDED','CONVERTED_TO_STRATEGIC','ERROR')),",
            "status TEXT NOT NULL CHECK(status = 'OPEN' OR 1=1),",
        )
        with self.assertRaises(SchemaVersionError):
            initialize(self._tampered_v2_db(ddl, self._LEGACY_PROBE_ID_ROW))

    def test_fake_weak_id_length_check_rejected(self):
        # id keeps NOT NULL but loses the non-empty CHECK: an empty-string id
        # must be caught by the behavioral probe, not by a DDL text search.
        ddl = self._FULLY_CONSTRAINED_T_LOTS.replace(
            "PRIMARY KEY CHECK(length(trim(id)) > 0),", "PRIMARY KEY,"
        )
        with self.assertRaises(SchemaVersionError):
            initialize(self._tampered_v2_db(ddl))

    def test_fake_weak_numeric_type_guard_rejected(self):
        # entry_price guarded only by `> 0` accepts text 'abc' (text sorts
        # greater than every number); the typeof storage-class probe must catch
        # it.
        ddl = self._FULLY_CONSTRAINED_T_LOTS.replace(
            "entry_price REAL NOT NULL CHECK(typeof(entry_price) IN ('integer','real') AND entry_price > 0),",
            "entry_price REAL NOT NULL CHECK(entry_price > 0),",
        )
        with self.assertRaises(SchemaVersionError):
            initialize(self._tampered_v2_db(ddl))

    def test_fake_unconstrained_review_status_rejected(self):
        ddl = self._FULLY_CONSTRAINED_T_LOTS.replace(
            "review_status TEXT CHECK(review_status IS NULL OR review_status IN ('PENDING','RESUME_T','KEEP_SUSPENDED','CONVERT_TO_STRATEGIC','MANUAL_EXIT'))",
            "review_status TEXT",
        )
        with self.assertRaises(SchemaVersionError):
            initialize(self._tampered_v2_db(ddl))

    def test_trigger_name_but_no_abort_rejected(self):
        # A trigger with the expected name that does not abort deletes must fail
        # the behavioral delete probe.
        ddl = self._FULLY_CONSTRAINED_T_LOTS.replace(
            "BEGIN SELECT RAISE(ABORT, 'no delete'); END;",
            "BEGIN SELECT 1; END;",
        )
        with self.assertRaises(SchemaVersionError):
            initialize(self._tampered_v2_db(ddl))

    def test_preinserted_legacy_probe_ids_initialize_succeeds(self):
        # A healthy database may legitimately contain rows whose ids look like
        # the old fixed probe ids; initialize() must succeed and leave them and
        # every other row untouched (REV-G2T002-002).
        path = _temp_db_path()
        conn = initialize(path)
        try:
            for i, legacy_id in enumerate(
                ("__tgrid_probe_valid", "__tgrid_probe_bad", "__tgrid_probe_delete")
            ):
                _insert(conn, _valid_row(id=legacy_id, qty=100 + i))
            conn.commit()
            before_rows = conn.execute("SELECT * FROM t_lots ORDER BY id").fetchall()
            before_history = conn.execute(
                "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
            ).fetchall()
            before_version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        conn = initialize(path)
        try:
            self.assertEqual(
                conn.execute("SELECT * FROM t_lots ORDER BY id").fetchall(), before_rows
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
            _insert(conn, _valid_row())
            _insert(
                conn,
                _valid_row(
                    suffix="suspended",
                    status="SUSPENDED",
                    realized_pnl=-1.5,
                    fees=0.0,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        before_conn = sqlite3.connect(path)
        before_rows = before_conn.execute(
            "SELECT * FROM t_lots ORDER BY id"
        ).fetchall()
        before_history = before_conn.execute(
            "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        before_version = before_conn.execute("PRAGMA user_version").fetchone()[0]
        before_conn.close()
        # initialize() runs all behavioral probes; nothing may be left behind.
        conn = initialize(path)
        try:
            self.assertEqual(
                conn.execute("SELECT * FROM t_lots ORDER BY id").fetchall(), before_rows
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
        conn.execute("DROP TABLE t_lots")
        conn.commit()
        conn.close()
        with self.assertRaises(PersistenceError):
            initialize(path)


if __name__ == "__main__":
    unittest.main()
