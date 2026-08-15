"""Tests for the atomic T-Lot status transition writer (G2-T004).

All tests use temporary SQLite files only; nothing connects to QMT or touches a
real database.
"""

import dataclasses
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from tgrid.persistence import (
    TLotNotFoundError,
    TLotStatusConflictError,
    TLotTransitionResult,
    TLotWriteFailedError,
    TLotWriterError,
    TLotWriterInputError,
    initialize,
    transition_t_lot_status,
)

OPEN = "OPEN"
SUSPENDED = "SUSPENDED"
PENDING_SELL = "PENDING_SELL"
CLOSED = "CLOSED"


def _temp_db_path():
    return str(Path(tempfile.mkdtemp()) / "t_lot_writer.db")


def _insert_t_lot(conn, lot_id, status=OPEN, updated_at="2026-08-15T10:00:00"):
    conn.execute(
        "INSERT INTO t_lots (id, symbol, side, qty, entry_price, entry_time,"
        " status, created_at, updated_at)"
        " VALUES (?, '600000.SH', 'BUY', 100, 10.0, 't', ?, 't', ?)",
        (lot_id, status, updated_at),
    )
    conn.commit()


def _audit_count(conn):
    return conn.execute("SELECT COUNT(*) FROM t_lot_audit_log").fetchone()[0]


def _seam(real, when, exc):
    """Minimal controlled connection seam: execute raises ``exc`` when
    ``when(sql)`` is true; everything else forwards to ``real``."""
    class Seam:
        def __init__(self, target):
            object.__setattr__(self, "_target", target)

        @property
        def in_transaction(self):
            return self._target.in_transaction

        def execute(self, sql, params=()):
            if when(sql):
                raise exc
            return self._target.execute(sql, params)

        def close(self):
            self._target.close()

    return Seam(real)


def _audit_insert(sql):
    return sql.strip().upper().startswith("INSERT INTO T_LOT_AUDIT_LOG")


def _snapshot(conn):
    lots = conn.execute("SELECT * FROM t_lots ORDER BY id").fetchall()
    audit = conn.execute("SELECT * FROM t_lot_audit_log ORDER BY id").fetchall()
    history = conn.execute(
        "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    return lots, audit, history, version


class TestHappyPath(unittest.TestCase):
    def test_open_to_suspended_success(self):
        path = _temp_db_path()
        conn = initialize(path)
        try:
            _insert_t_lot(conn, "L1")
            occurred_at = "2026-08-15T11:30:00"
            result = transition_t_lot_status(
                conn,
                t_lot_id="L1",
                expected_status=OPEN,
                new_status=SUSPENDED,
                audit_id="A1",
                event_type="SUSPEND_REVIEW",
                details_json='{"reason": "gap"}',
                actor="system",
                occurred_at=occurred_at,
            )
            self.assertIsInstance(result, TLotTransitionResult)
            self.assertTrue(dataclasses.is_dataclass(result))
            self.assertTrue(dataclasses.fields(result))
            self.assertEqual(
                (result.t_lot_id, result.from_status, result.to_status,
                 result.audit_id, result.occurred_at),
                ("L1", OPEN, SUSPENDED, "A1", occurred_at),
            )
            with self.assertRaises(dataclasses.FrozenInstanceError):
                result.t_lot_id = "other"
            lot = conn.execute(
                "SELECT status, updated_at FROM t_lots WHERE id = 'L1'"
            ).fetchone()
            self.assertEqual(lot, (SUSPENDED, occurred_at))
            self.assertEqual(_audit_count(conn), 1)
            audit = conn.execute(
                "SELECT id, t_lot_id, event_type, from_status, to_status,"
                " details_json, actor, created_at FROM t_lot_audit_log"
            ).fetchone()
            self.assertEqual(
                audit,
                ("A1", "L1", "SUSPEND_REVIEW", OPEN, SUSPENDED,
                 '{"reason": "gap"}', "system", occurred_at),
            )
        finally:
            conn.close()


class TestValidation(unittest.TestCase):
    def _conn(self):
        conn = initialize(_temp_db_path())
        _insert_t_lot(conn, "L1")
        return conn

    def test_missing_lot_raises_not_found(self):
        conn = self._conn()
        try:
            before = _snapshot(conn)
            with self.assertRaises(TLotNotFoundError):
                transition_t_lot_status(
                    conn, t_lot_id="NO_SUCH", expected_status=OPEN,
                    new_status=SUSPENDED, audit_id="A1", event_type="E",
                    details_json="{}", actor="s", occurred_at="t",
                )
            self.assertEqual(_snapshot(conn), before)
        finally:
            conn.close()

    def test_stale_expected_status_raises_conflict(self):
        conn = self._conn()
        try:
            conn.execute("UPDATE t_lots SET status = 'CLOSED' WHERE id = 'L1'")
            conn.commit()
            before = _snapshot(conn)
            with self.assertRaises(TLotStatusConflictError):
                transition_t_lot_status(
                    conn, t_lot_id="L1", expected_status=OPEN,
                    new_status=SUSPENDED, audit_id="A1", event_type="E",
                    details_json="{}", actor="s", occurred_at="t",
                )
            self.assertEqual(_snapshot(conn), before)
        finally:
            conn.close()

    def test_old_equals_new_rejected(self):
        conn = self._conn()
        try:
            with self.assertRaises(TLotWriterInputError):
                transition_t_lot_status(
                    conn, t_lot_id="L1", expected_status=OPEN,
                    new_status=OPEN, audit_id="A1", event_type="E",
                    details_json="{}", actor="s", occurred_at="t",
                )
            self.assertEqual(_audit_count(conn), 0)
        finally:
            conn.close()

    def test_out_of_status_rejected(self):
        conn = self._conn()
        try:
            for field, value in (
                ("expected_status", "BOGUS"),
                ("new_status", "open"),
                ("expected_status", "PENDING"),
            ):
                kwargs = {
                    "t_lot_id": "L1", "expected_status": OPEN,
                    "new_status": SUSPENDED, "audit_id": "A1", "event_type": "E",
                    "details_json": "{}", "actor": "s", "occurred_at": "t",
                }
                kwargs[field] = value
                with self.assertRaises(
                    TLotWriterInputError, msg=f"{field}={value!r}"
                ):
                    transition_t_lot_status(conn, **kwargs)
            self.assertEqual(_audit_count(conn), 0)
        finally:
            conn.close()

    def test_invalid_text_inputs_rejected(self):
        conn = self._conn()
        try:
            fields = (
                "t_lot_id", "audit_id", "event_type", "details_json",
                "actor", "occurred_at",
            )
            for name in fields:
                for bad in (None, "", 123, b"x", ["x"], True):
                    kwargs = {
                        "t_lot_id": "L1", "expected_status": OPEN,
                        "new_status": SUSPENDED, "audit_id": "A1",
                        "event_type": "E", "details_json": "{}",
                        "actor": "s", "occurred_at": "t",
                    }
                    kwargs[name] = bad
                    with self.assertRaises(
                        TLotWriterInputError,
                        msg=f"{name}={bad!r}",
                    ):
                        transition_t_lot_status(conn, **kwargs)
            self.assertEqual(_audit_count(conn), 0)
        finally:
            conn.close()

    def test_malicious_status_dunder_not_called(self):
        # status must be validated as exact non-empty str BEFORE any membership
        # test, so a malicious object's __eq__ is never invoked (REV-G2T004-002).
        conn = self._conn()
        try:
            class EvilStatus:
                def __eq__(self, other):
                    raise RuntimeError("STATUS_DUNDER_SECRET")

            with self.assertRaises(TLotWriterInputError) as ctx:
                transition_t_lot_status(
                    conn, t_lot_id="L1", expected_status=EvilStatus(),
                    new_status=SUSPENDED, audit_id="A1", event_type="E",
                    details_json="{}", actor="s", occurred_at="t",
                )
            self.assertNotIn("STATUS_DUNDER_SECRET", str(ctx.exception))
            self.assertIsNone(ctx.exception.__cause__)
            self.assertIsNone(ctx.exception.__context__)
            self.assertEqual(_audit_count(conn), 0)
            self.assertFalse(conn.in_transaction)
        finally:
            conn.close()


class TestAtomicity(unittest.TestCase):
    def test_duplicate_audit_id_rolls_back(self):
        conn = initialize(_temp_db_path())
        try:
            _insert_t_lot(conn, "L1")
            transition_t_lot_status(
                conn, t_lot_id="L1", expected_status=OPEN,
                new_status=PENDING_SELL, audit_id="A1", event_type="E",
                details_json="{}", actor="s", occurred_at="t1",
            )
            # CAS succeeds (lot is PENDING_SELL) but the audit insert collides on
            # A1: the whole transaction must roll back to PENDING_SELL/t1.
            with self.assertRaises(TLotWriteFailedError):
                transition_t_lot_status(
                    conn, t_lot_id="L1", expected_status=PENDING_SELL,
                    new_status=CLOSED, audit_id="A1", event_type="E",
                    details_json="{}", actor="s", occurred_at="t2",
                )
            lot = conn.execute(
                "SELECT status, updated_at FROM t_lots WHERE id = 'L1'"
            ).fetchone()
            self.assertEqual(lot, (PENDING_SELL, "t1"))
            self.assertEqual(_audit_count(conn), 1)
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0], 5
            )
        finally:
            conn.close()

    def test_audit_constraint_failure_rolls_back(self):
        # A whitespace-only details_json passes the writer's non-empty check but
        # fails the audit table's trim-length CHECK; the status UPDATE must be
        # rolled back too.
        conn = initialize(_temp_db_path())
        try:
            _insert_t_lot(conn, "L1")
            with self.assertRaises(TLotWriteFailedError):
                transition_t_lot_status(
                    conn, t_lot_id="L1", expected_status=OPEN,
                    new_status=SUSPENDED, audit_id="A1", event_type="E",
                    details_json="   ", actor="s", occurred_at="t",
                )
            lot = conn.execute(
                "SELECT status, updated_at FROM t_lots WHERE id = 'L1'"
            ).fetchone()
            self.assertEqual(lot, (OPEN, "2026-08-15T10:00:00"))
            self.assertEqual(_audit_count(conn), 0)
        finally:
            conn.close()

    def test_commit_failure_rolls_back(self):
        # Minimal controlled connection seam: forward everything to a real
        # initialized connection but raise on COMMIT (no second DB wrapper).
        path = _temp_db_path()
        real = initialize(path)
        try:
            _insert_t_lot(real, "L1")

            class CommitFailConnection:
                def __init__(self, target):
                    object.__setattr__(self, "_target", target)

                @property
                def in_transaction(self):
                    return self._target.in_transaction

                def execute(self, sql, params=()):
                    if isinstance(sql, str) and sql.strip().upper() == "COMMIT":
                        raise sqlite3.Error("COMMIT_SECRET_XYZ")
                    return self._target.execute(sql, params)

            proxy = CommitFailConnection(real)
            with self.assertRaises(TLotWriteFailedError) as ctx:
                transition_t_lot_status(
                    proxy, t_lot_id="L1", expected_status=OPEN,
                    new_status=SUSPENDED, audit_id="A1", event_type="E",
                    details_json="{}", actor="s", occurred_at="t",
                )
            self.assertNotIn("COMMIT_SECRET_XYZ", str(ctx.exception))
            self.assertIsNone(ctx.exception.__cause__)
            self.assertIsNone(ctx.exception.__context__)
            lot = real.execute(
                "SELECT status, updated_at FROM t_lots WHERE id = 'L1'"
            ).fetchone()
            self.assertEqual(lot, (OPEN, "2026-08-15T10:00:00"))
            self.assertEqual(_audit_count(real), 0)
        finally:
            real.close()

    def test_base_exception_at_audit_insert_propagates_and_rolls_back(self):
        # KeyboardInterrupt / SystemExit / GeneratorExit after the CAS must
        # first roll back (no half "status changed, audit=0" state) then
        # propagate the original object/type unchanged (REV-G2T004-001).
        real = initialize(_temp_db_path())
        try:
            _insert_t_lot(real, "L1")
            for exc_type in (KeyboardInterrupt, SystemExit, GeneratorExit):
                seam = _seam(real, when=_audit_insert, exc=exc_type())
                with self.assertRaises(exc_type) as ctx:
                    transition_t_lot_status(
                        seam, t_lot_id="L1", expected_status=OPEN,
                        new_status=SUSPENDED, audit_id="A1", event_type="E",
                        details_json="{}", actor="s", occurred_at="t",
                    )
                self.assertIsInstance(ctx.exception, exc_type)
                self.assertIsNone(ctx.exception.__cause__)
                self.assertIsNone(ctx.exception.__context__)
                self.assertFalse(real.in_transaction)
                lot = real.execute(
                    "SELECT status, updated_at FROM t_lots WHERE id = 'L1'"
                ).fetchone()
                self.assertEqual(lot, (OPEN, "2026-08-15T10:00:00"))
                self.assertEqual(_audit_count(real), 0)
        finally:
            real.close()

    def test_runtime_error_secret_converted_and_rolled_back(self):
        # A non-sqlite RuntimeError after the CAS is rolled back and converted
        # to a fixed, data-free TLotWriteFailedError with a clean graph.
        real = initialize(_temp_db_path())
        try:
            _insert_t_lot(real, "L1")
            seam = _seam(
                real, when=_audit_insert, exc=RuntimeError("PRIMARY_RUNTIME_SECRET")
            )
            with self.assertRaises(TLotWriteFailedError) as ctx:
                transition_t_lot_status(
                    seam, t_lot_id="L1", expected_status=OPEN,
                    new_status=SUSPENDED, audit_id="A1", event_type="E",
                    details_json="{}", actor="s", occurred_at="t",
                )
            self.assertNotIn("PRIMARY_RUNTIME_SECRET", str(ctx.exception))
            self.assertIsNone(ctx.exception.__cause__)
            self.assertIsNone(ctx.exception.__context__)
            self.assertFalse(real.in_transaction)
            self.assertEqual(
                real.execute(
                    "SELECT status FROM t_lots WHERE id = 'L1'"
                ).fetchone()[0],
                OPEN,
            )
            self.assertEqual(_audit_count(real), 0)
        finally:
            real.close()

    def test_primary_failure_with_rollback_failure_invalidates_connection(self):
        # When rollback itself cannot be confirmed, the connection is closed so
        # the half-complete write can never be committed; the primary failure
        # (converted, data-free) still propagates and never leaks the secret.
        real = initialize(_temp_db_path())
        try:
            _insert_t_lot(real, "L1")
            seam = _seam(
                real,
                when=lambda sql: sql.strip().upper() in ("COMMIT", "ROLLBACK"),
                exc=sqlite3.Error("ROLLBACK_COMMIT_SECRET"),
            )
            with self.assertRaises(TLotWriteFailedError) as ctx:
                transition_t_lot_status(
                    seam, t_lot_id="L1", expected_status=OPEN,
                    new_status=SUSPENDED, audit_id="A1", event_type="E",
                    details_json="{}", actor="s", occurred_at="t",
                )
            self.assertNotIn("ROLLBACK_COMMIT_SECRET", str(ctx.exception))
            self.assertIsNone(ctx.exception.__cause__)
            self.assertIsNone(ctx.exception.__context__)
            # rollback failed => connection must be invalidated (not committable).
            with self.assertRaises(sqlite3.ProgrammingError):
                real.execute("SELECT 1")
        finally:
            try:
                real.close()
            except sqlite3.Error:
                pass

    def test_base_exception_primary_with_rollback_failure(self):
        # A BaseException primary combined with a rollback BaseException: the
        # primary still propagates unchanged and the connection is invalidated.
        real = initialize(_temp_db_path())
        try:
            _insert_t_lot(real, "L1")
            seam = _seam(
                real,
                when=lambda sql: sql.strip().upper() in ("COMMIT", "ROLLBACK"),
                exc=KeyboardInterrupt(),
            )
            with self.assertRaises(KeyboardInterrupt):
                transition_t_lot_status(
                    seam, t_lot_id="L1", expected_status=OPEN,
                    new_status=SUSPENDED, audit_id="A1", event_type="E",
                    details_json="{}", actor="s", occurred_at="t",
                )
            with self.assertRaises(sqlite3.ProgrammingError):
                real.execute("SELECT 1")
        finally:
            try:
                real.close()
            except sqlite3.Error:
                pass


class TestActiveTransaction(unittest.TestCase):
    def test_active_transaction_rejected_and_caller_state_preserved(self):
        conn = initialize(_temp_db_path())
        try:
            conn.execute("BEGIN")
            conn.execute(
                "INSERT INTO t_lots (id, symbol, side, qty, entry_price,"
                " entry_time, status, created_at, updated_at)"
                " VALUES ('PENDING', '600000.SH', 'BUY', 100, 10.0, 't',"
                " 'OPEN', 't', 't')"
            )
            with self.assertRaises(TLotWriterInputError):
                transition_t_lot_status(
                    conn, t_lot_id="PENDING", expected_status=OPEN,
                    new_status=SUSPENDED, audit_id="A1", event_type="E",
                    details_json="{}", actor="s", occurred_at="t",
                )
            # The writer must not have committed or rolled back the caller's
            # transaction: the pending row is still visible to the caller.
            self.assertTrue(conn.in_transaction)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM t_lots WHERE id = 'PENDING'")
                .fetchone()[0],
                1,
            )
            conn.execute("ROLLBACK")
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM t_lots WHERE id = 'PENDING'")
                .fetchone()[0],
                0,
            )
        finally:
            conn.close()


class TestConcurrency(unittest.TestCase):
    def test_two_connections_deterministic_cas_race(self):
        # Real interleaving driven by Events (no sleep): conn1 holds BEGIN
        # IMMEDIATE with an uncommitted CAS+audit while conn2 starts the same
        # expected-status write and blocks on conn1's write lock.  After the
        # deterministic release exactly one wins; the other conflicts and no
        # second audit is written.  Each connection is created and used inside
        # its own thread (sqlite3 check_same_thread).
        path = _temp_db_path()
        in_txn = threading.Event()
        conn2_ready = threading.Event()
        started2 = threading.Event()
        release = threading.Event()
        results = {}

        class PauseCommitConn:
            def __init__(self, target):
                object.__setattr__(self, "_target", target)

            @property
            def in_transaction(self):
                return self._target.in_transaction

            def execute(self, sql, params=()):
                if isinstance(sql, str) and sql.strip().upper() == "COMMIT":
                    in_txn.set()
                    release.wait()
                return self._target.execute(sql, params)

        def run2():
            try:
                conn2 = initialize(path)
            except BaseException as exc:
                results["conn2"] = exc
                return
            try:
                conn2_ready.set()
                # Only initiate the competing write once conn1 holds an
                # uncommitted BEGIN IMMEDIATE, so conn2's BEGIN genuinely
                # contends for the write lock (REV-G2T004-003).
                if not in_txn.wait(10):
                    results["conn2"] = RuntimeError("conn1 never entered its transaction")
                    return
                started2.set()
                results["conn2"] = transition_t_lot_status(
                    conn2, t_lot_id="L1", expected_status=OPEN,
                    new_status=CLOSED, audit_id="A2", event_type="E",
                    details_json="{}", actor="s", occurred_at="t2",
                )
            except BaseException as exc:
                results["conn2"] = exc
            finally:
                conn2.close()

        def run1():
            try:
                conn1 = initialize(path)
                _insert_t_lot(conn1, "L1")
                results["conn1"] = transition_t_lot_status(
                    PauseCommitConn(conn1), t_lot_id="L1", expected_status=OPEN,
                    new_status=SUSPENDED, audit_id="A1", event_type="E",
                    details_json="{}", actor="s", occurred_at="t1",
                )
            except BaseException as exc:
                results["conn1"] = exc
            finally:
                conn1.close()

        t2 = threading.Thread(target=run2)
        t1 = threading.Thread(target=run1)
        try:
            t2.start()
            self.assertTrue(conn2_ready.wait(10), "conn2 did not initialize")
            t1.start()
            self.assertTrue(
                in_txn.wait(10), "conn1 did not reach its uncommitted write"
            )
            self.assertTrue(started2.wait(10), "conn2 did not start its writer")
            release.set()  # deterministic release: conn1 commits first
            t1.join(10)
            t2.join(10)
            self.assertFalse(t1.is_alive())
            self.assertFalse(t2.is_alive())
            self.assertIsInstance(results["conn1"], TLotTransitionResult)
            self.assertEqual(
                (results["conn1"].from_status, results["conn1"].to_status),
                (OPEN, SUSPENDED),
            )
            self.assertIsInstance(results["conn2"], TLotStatusConflictError)
            conn3 = initialize(path)
            try:
                lot = conn3.execute(
                    "SELECT status, updated_at FROM t_lots WHERE id = 'L1'"
                ).fetchone()
                self.assertEqual(lot, (SUSPENDED, "t1"))
                self.assertEqual(_audit_count(conn3), 1)
                self.assertFalse(conn3.in_transaction)
            finally:
                conn3.close()
        finally:
            release.set()


class TestExceptionHierarchy(unittest.TestCase):
    def test_writer_exceptions_subclass_persistence(self):
        from tgrid.risk.exceptions import PersistenceError

        for exc in (
            TLotWriterError, TLotWriterInputError, TLotNotFoundError,
            TLotStatusConflictError, TLotWriteFailedError,
        ):
            self.assertTrue(issubclass(exc, PersistenceError))

    def test_no_forbidden_api_in_writer_module(self):
        import ast

        from tgrid.persistence import t_lot_writer

        tree = ast.parse(
            Path(t_lot_writer.__file__).read_text(encoding="utf-8"),
            filename=str(t_lot_writer.__file__),
        )
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, ast.Assert)], [])
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(alias.name.split(".")[0], "xtquant")
            elif isinstance(node, ast.ImportFrom):
                self.assertNotEqual((node.module or "").split(".")[0], "xtquant")
            if isinstance(node, ast.Call):
                func = node.func
                name = (
                    func.attr
                    if isinstance(func, ast.Attribute)
                    else (func.id if isinstance(func, ast.Name) else None)
                )
                self.assertNotIn(name, {"order_stock", "cancel_order"})


if __name__ == "__main__":
    unittest.main()
