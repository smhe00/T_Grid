"""Tests for the T-Lot business transition policy guard (G2-T005).

All tests use temporary SQLite files only; nothing connects to QMT or touches a
real database.  The policy layer reuses G2-T004's atomic writer; no SQL is
written here.
"""

import ast
import dataclasses
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tgrid.persistence import (
    TLotStatusConflictError,
    TLotTransitionPlan,
    TLotTransitionRejectedError,
    TLotTransitionResult,
    apply_t_lot_transition,
    initialize,
    resolve_t_lot_transition,
)
from tgrid.persistence.migrations import T_LOT_STATUSES

ACTIONS = (
    "BUY_FILL_CONFIRMED",
    "PREPARE_SELL",
    "SELL_FILL_CONFIRMED",
    "SUSPEND_T",
    "RESUME_T",
)

APPROVED = {
    ("BUY_FILL_CONFIRMED", "PENDING_BUY"): ("OPEN", "BUY_FILL_CONFIRMED"),
    ("PREPARE_SELL", "OPEN"): ("PENDING_SELL", "PREPARE_SELL"),
    ("SELL_FILL_CONFIRMED", "PENDING_SELL"): ("CLOSED", "SELL_FILL_CONFIRMED"),
    ("SUSPEND_T", "OPEN"): ("SUSPENDED", "SUSPEND_T"),
    ("RESUME_T", "SUSPENDED"): ("OPEN", "RESUME_T"),
}

TERMINAL_STATUSES = ("CLOSED", "CONVERTED_TO_STRATEGIC", "ERROR")
MANUAL_NOOP_ACTIONS = ("KEEP_SUSPENDED", "CONVERT_TO_STRATEGIC", "MANUAL_EXIT")


def _temp_db_path():
    return str(Path(tempfile.mkdtemp()) / "t_lot_policy.db")


def _insert_t_lot(conn, lot_id, status, updated_at="2026-08-15T10:00:00"):
    conn.execute(
        "INSERT INTO t_lots (id, symbol, side, qty, entry_price, entry_time,"
        " status, created_at, updated_at)"
        " VALUES (?, '600000.SH', 'BUY', 100, 10.0, 't', ?, 't', ?)",
        (lot_id, status, updated_at),
    )
    conn.commit()


def _audit_count(conn):
    return conn.execute("SELECT COUNT(*) FROM t_lot_audit_log").fetchone()[0]


class TestResolver(unittest.TestCase):
    def test_approved_edges_resolve_correctly(self):
        for (action, source), (to_status, event_type) in APPROVED.items():
            plan = resolve_t_lot_transition(action, source)
            self.assertIsInstance(plan, TLotTransitionPlan)
            self.assertTrue(dataclasses.is_dataclass(plan))
            self.assertEqual(
                (plan.action, plan.expected_status, plan.to_status, plan.event_type),
                (action, source, to_status, event_type),
            )
            with self.assertRaises(dataclasses.FrozenInstanceError):
                plan.to_status = "X"

    def test_full_action_status_matrix(self):
        approved = set(APPROVED.keys())
        for action in ACTIONS:
            for status in T_LOT_STATUSES:
                if (action, status) in approved:
                    plan = resolve_t_lot_transition(action, status)
                    self.assertEqual(plan.to_status, APPROVED[(action, status)][0])
                else:
                    with self.assertRaises(TLotTransitionRejectedError):
                        resolve_t_lot_transition(action, status)

    def test_self_transitions_rejected(self):
        # No approved edge maps a status onto itself; any request that would be
        # a self-transition therefore falls outside the closed set and must be
        # rejected.
        for action in ACTIONS:
            for status in T_LOT_STATUSES:
                edge = APPROVED.get((action, status))
                if edge is not None:
                    self.assertNotEqual(
                        edge[0], status, f"{action},{status} is a self-transition"
                    )
                    resolve_t_lot_transition(action, status)  # approved, succeeds
                else:
                    with self.assertRaises(TLotTransitionRejectedError):
                        resolve_t_lot_transition(action, status)

    def test_unknown_action_rejected(self):
        for action in ("UNKNOWN", "SELL", "OPEN_LOT", "CANCEL_ORDER"):
            with self.assertRaises(TLotTransitionRejectedError):
                resolve_t_lot_transition(action, "OPEN")

    def test_manual_noop_actions_rejected(self):
        for action in MANUAL_NOOP_ACTIONS:
            with self.assertRaises(TLotTransitionRejectedError):
                resolve_t_lot_transition(action, "SUSPENDED")
            with self.assertRaises(TLotTransitionRejectedError):
                resolve_t_lot_transition(action, "OPEN")

    def test_terminal_source_rejected(self):
        for status in TERMINAL_STATUSES:
            for action in ACTIONS:
                with self.assertRaises(TLotTransitionRejectedError):
                    resolve_t_lot_transition(action, status)

    def test_wrong_source_rejected(self):
        # A valid action with a source it does not apply to.
        for action, source in (
            ("BUY_FILL_CONFIRMED", "OPEN"),
            ("PREPARE_SELL", "PENDING_BUY"),
            ("SELL_FILL_CONFIRMED", "OPEN"),
            ("SUSPEND_T", "PENDING_SELL"),
            ("RESUME_T", "OPEN"),
        ):
            with self.assertRaises(TLotTransitionRejectedError):
                resolve_t_lot_transition(action, source)

    def test_invalid_input_types_rejected(self):
        class StrSub(str):
            pass

        for field in ("action", "expected_status"):
            for bad in (None, "", 123, b"x", ["x"], True, StrSub("OPEN")):
                kwargs = {"action": "SUSPEND_T", "expected_status": "OPEN"}
                kwargs[field] = bad
                with self.assertRaises(
                    TLotTransitionRejectedError, msg=f"{field}={bad!r}"
                ):
                    resolve_t_lot_transition(**kwargs)

    def test_malicious_action_dunder_not_called(self):
        class Evil:
            def __eq__(self, other):
                raise RuntimeError("POLICY_DUNDER_SECRET")

        with self.assertRaises(TLotTransitionRejectedError) as ctx:
            resolve_t_lot_transition(Evil(), "OPEN")
        self.assertNotIn("POLICY_DUNDER_SECRET", str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertIsNone(ctx.exception.__context__)

    def test_malicious_status_dunder_not_called(self):
        class Evil:
            def __eq__(self, other):
                raise RuntimeError("STATUS_DUNDER_SECRET")

        with self.assertRaises(TLotTransitionRejectedError) as ctx:
            resolve_t_lot_transition("SUSPEND_T", Evil())
        self.assertNotIn("STATUS_DUNDER_SECRET", str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertIsNone(ctx.exception.__context__)


class TestApplyIntegration(unittest.TestCase):
    def test_each_approved_edge_applies_and_audits(self):
        for (action, source), (to_status, event_type) in APPROVED.items():
            conn = initialize(_temp_db_path())
            try:
                _insert_t_lot(conn, "L1", source)
                result = apply_t_lot_transition(
                    conn, t_lot_id="L1", expected_status=source, action=action,
                    audit_id=f"A-{action}", details_json="{}", actor="system",
                    occurred_at="2026-08-15T11:00:00",
                )
                self.assertIsInstance(result, TLotTransitionResult)
                self.assertEqual(
                    (result.from_status, result.to_status), (source, to_status)
                )
                self.assertEqual(
                    conn.execute("SELECT status FROM t_lots WHERE id='L1'")
                    .fetchone()[0],
                    to_status,
                )
                self.assertEqual(_audit_count(conn), 1)
                audit = conn.execute(
                    "SELECT event_type, from_status, to_status FROM t_lot_audit_log"
                ).fetchone()
                self.assertEqual(audit, (event_type, source, to_status))
            finally:
                conn.close()

    def test_rejected_edge_no_db_touch(self):
        conn = initialize(_temp_db_path())
        try:
            _insert_t_lot(conn, "L1", "OPEN")
            before = conn.execute("SELECT * FROM t_lots").fetchall()
            with self.assertRaises(TLotTransitionRejectedError):
                apply_t_lot_transition(
                    conn, t_lot_id="L1", expected_status="OPEN",
                    action="SELL_FILL_CONFIRMED", audit_id="A", details_json="{}",
                    actor="s", occurred_at="t",
                )
            self.assertEqual(conn.execute("SELECT * FROM t_lots").fetchall(), before)
            self.assertEqual(_audit_count(conn), 0)
        finally:
            conn.close()

    def test_manual_noop_not_applied(self):
        for action in MANUAL_NOOP_ACTIONS:
            conn = initialize(_temp_db_path())
            try:
                _insert_t_lot(conn, "L1", "SUSPENDED")
                with self.assertRaises(TLotTransitionRejectedError):
                    apply_t_lot_transition(
                        conn, t_lot_id="L1", expected_status="SUSPENDED",
                        action=action, audit_id="A", details_json="{}",
                        actor="s", occurred_at="t",
                    )
                self.assertEqual(
                    conn.execute("SELECT status FROM t_lots WHERE id='L1'")
                    .fetchone()[0],
                    "SUSPENDED",
                )
                self.assertEqual(_audit_count(conn), 0)
            finally:
                conn.close()

    def test_stale_source_conflicts_via_writer(self):
        conn = initialize(_temp_db_path())
        try:
            _insert_t_lot(conn, "L1", "OPEN")
            result = apply_t_lot_transition(
                conn, t_lot_id="L1", expected_status="OPEN", action="PREPARE_SELL",
                audit_id="A1", details_json="{}", actor="s", occurred_at="t1",
            )
            self.assertEqual(result.to_status, "PENDING_SELL")
            with self.assertRaises(TLotStatusConflictError):
                apply_t_lot_transition(
                    conn, t_lot_id="L1", expected_status="OPEN", action="PREPARE_SELL",
                    audit_id="A2", details_json="{}", actor="s", occurred_at="t2",
                )
            self.assertEqual(
                conn.execute("SELECT status FROM t_lots WHERE id='L1'")
                .fetchone()[0],
                "PENDING_SELL",
            )
            self.assertEqual(_audit_count(conn), 1)
        finally:
            conn.close()


class TestWriterSpy(unittest.TestCase):
    def test_writer_not_called_on_rejected(self):
        conn = initialize(_temp_db_path())
        try:
            with mock.patch(
                "tgrid.persistence.t_lot_transition_policy.transition_t_lot_status"
            ) as spy:
                with self.assertRaises(TLotTransitionRejectedError):
                    apply_t_lot_transition(
                        conn, t_lot_id="L1", expected_status="OPEN",
                        action="CONVERT_TO_STRATEGIC", audit_id="A",
                        details_json="{}", actor="s", occurred_at="t",
                    )
                spy.assert_not_called()
        finally:
            conn.close()

    def test_writer_called_exactly_once_on_success(self):
        conn = initialize(_temp_db_path())
        try:
            with mock.patch(
                "tgrid.persistence.t_lot_transition_policy.transition_t_lot_status",
                return_value=object(),
            ) as spy:
                apply_t_lot_transition(
                    conn, t_lot_id="L1", expected_status="PENDING_BUY",
                    action="BUY_FILL_CONFIRMED", audit_id="A", details_json="{}",
                    actor="s", occurred_at="t",
                )
                spy.assert_called_once_with(
                    conn,
                    t_lot_id="L1",
                    expected_status="PENDING_BUY",
                    new_status="OPEN",
                    audit_id="A",
                    event_type="BUY_FILL_CONFIRMED",
                    details_json="{}",
                    actor="s",
                    occurred_at="t",
                )
        finally:
            conn.close()

    def test_writer_conflict_propagates_once(self):
        conn = initialize(_temp_db_path())
        try:
            with mock.patch(
                "tgrid.persistence.t_lot_transition_policy.transition_t_lot_status",
                side_effect=TLotStatusConflictError("conflict"),
            ) as spy:
                with self.assertRaises(TLotStatusConflictError):
                    apply_t_lot_transition(
                        conn, t_lot_id="L1", expected_status="OPEN",
                        action="SUSPEND_T", audit_id="A", details_json="{}",
                        actor="s", occurred_at="t",
                    )
                spy.assert_called_once()
        finally:
            conn.close()

    def test_writer_base_exception_propagates_once(self):
        conn = initialize(_temp_db_path())
        try:
            with mock.patch(
                "tgrid.persistence.t_lot_transition_policy.transition_t_lot_status",
                side_effect=KeyboardInterrupt(),
            ) as spy:
                with self.assertRaises(KeyboardInterrupt):
                    apply_t_lot_transition(
                        conn, t_lot_id="L1", expected_status="OPEN",
                        action="SUSPEND_T", audit_id="A", details_json="{}",
                        actor="s", occurred_at="t",
                    )
                spy.assert_called_once()
        finally:
            conn.close()


class TestForbiddenApiScan(unittest.TestCase):
    def test_no_raw_sql_assert_or_trading_api(self):
        from tgrid.persistence import t_lot_transition_policy as mod

        src = Path(mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(mod.__file__))
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, ast.Assert)], [])
        for token in (
            "BEGIN", "UPDATE ", "INSERT INTO", "DELETE FROM", "COMMIT", "ROLLBACK",
        ):
            self.assertNotIn(token, src)
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
