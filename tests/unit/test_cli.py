"""Tests for the offline CLI and startup/shutdown orchestration (G0-T004)."""

import ast
import contextlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tgrid.main import (
    EXIT_FAILURE,
    EXIT_INTERRUPT,
    EXIT_OK,
    EXIT_USAGE,
    LOGGER_NAME,
    main,
)
from tgrid.reporting import shutdown_logger as real_shutdown_logger


def _valid_config_text(live_trading="false"):
    return (
        "global:\n"
        f"  live_trading: {live_trading}\n"
        "  database: data/tgrid.db\n"
        "  log_dir: logs\n"
        "  bar_period: 5m\n"
        "  order_timeout_seconds: 120\n"
        "  skip_open_minutes: 15\n"
        "  skip_close_minutes: 15\n"
        "  volatility_halt_atr: 2.5\n"
        "  minimum_cash_buffer: 50000.0\n"
        "symbols:\n"
        "  0700.HK:\n"
        "    enabled: true\n"
        "    mode: ACCUMULATE\n"
        "    core_qty: 600\n"
        "    target_qty: 1100\n"
        "    t_unit: 100\n"
        "    lot_size: 100\n"
        "    price_tick: 0.2\n"
        "    max_t_lots: 2\n"
        "    max_t_capital: 200000.0\n"
        "    anchor: VWAP20\n"
        "    atr_period: 14\n"
        "    atr_k: 1.20\n"
        "    min_grid: 0.040\n"
        "    max_grid: 0.080\n"
        "    exit_multiple: 1.15\n"
    )


def _write_config(tmp, text=None, name="config.yaml"):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text if text is not None else _valid_config_text())
    return path


def _tmp_paths(tmp):
    return (
        os.path.join(tmp, "config.yaml"),
        os.path.join(tmp, "data", "tgrid.db"),
        os.path.join(tmp, "logs", "app.jsonl"),
    )


def _read_jsonl(path):
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle.read().splitlines() if line.strip()]


class TestArgparse(unittest.TestCase):
    def test_help_exits_zero(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_version_returns_zero(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--version"])
        self.assertEqual(rc, 0)
        self.assertIn("tgrid", buf.getvalue())
        self.assertIn("0.1.0", buf.getvalue())

    def test_missing_subcommand_returns_usage(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = main([])
        self.assertEqual(rc, EXIT_USAGE)

    def test_missing_required_args_exits_two(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                main(["preflight"])
        self.assertEqual(cm.exception.code, 2)


class TestPreflightSuccess(unittest.TestCase):
    def test_success_returns_zero_and_writes_three_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(tmp)
            db_path = os.path.join(tmp, "data", "tgrid.db")
            log_path = os.path.join(tmp, "logs", "app.jsonl")

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = main(
                    ["preflight", "--config", config_path, "--database", db_path, "--log", log_path]
                )

            self.assertEqual(rc, EXIT_OK)
            self.assertIn("preflight ok", out.getvalue())

            events = [r["event"] for r in _read_jsonl(log_path)]
            self.assertEqual(events, ["startup_begin", "preflight_ok", "shutdown_complete"])

            conn = sqlite3.connect(db_path)
            try:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 5)
                count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
                self.assertEqual(count, 5)
            finally:
                conn.close()

    def test_repeat_preflight_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(tmp)
            db_path = os.path.join(tmp, "data", "tgrid.db")
            log_path = os.path.join(tmp, "logs", "app.jsonl")
            for _ in range(2):
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = main(
                        ["preflight", "--config", config_path, "--database", db_path, "--log", log_path]
                    )
                self.assertEqual(rc, EXIT_OK)

            conn = sqlite3.connect(db_path)
            try:
                count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
                self.assertEqual(count, 5)
            finally:
                conn.close()

            events = [r["event"] for r in _read_jsonl(log_path)]
            self.assertEqual(
                events,
                ["startup_begin", "preflight_ok", "shutdown_complete"] * 2,
            )


class TestPreflightRejections(unittest.TestCase):
    def test_live_trading_true_rejected_before_db_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(tmp, _valid_config_text(live_trading="true"))
            db_path = os.path.join(tmp, "data", "tgrid.db")
            log_path = os.path.join(tmp, "logs", "app.jsonl")

            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = main(
                    ["preflight", "--config", config_path, "--database", db_path, "--log", log_path]
                )

            self.assertEqual(rc, EXIT_FAILURE)
            self.assertFalse(os.path.exists(db_path))
            self.assertFalse(os.path.exists(log_path))
            self.assertNotIn("Traceback", err.getvalue())

    def test_path_conflict_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(tmp)
            same = config_path
            for db, log in (
                (same, os.path.join(tmp, "l.jsonl")),  # config == database
                (os.path.join(tmp, "d.db"), same),  # config == log
                (os.path.join(tmp, "d.db"), os.path.join(tmp, "d.db")),  # db == log
            ):
                rc = main(
                    ["preflight", "--config", config_path, "--database", db, "--log", log]
                )
                self.assertEqual(rc, EXIT_FAILURE)

    def test_alias_path_conflict_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(tmp)
            # Same location via a relative/`.` alias.
            db_path = os.path.join(tmp, ".", "config.yaml")
            log_path = os.path.join(tmp, "l.jsonl")
            rc = main(
                ["preflight", "--config", config_path, "--database", db_path, "--log", log_path]
            )
            self.assertEqual(rc, EXIT_FAILURE)

    def test_invalid_yaml_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(tmp, "global: [unclosed\n")
            rc = main(
                [
                    "preflight",
                    "--config", config_path,
                    "--database", os.path.join(tmp, "d.db"),
                    "--log", os.path.join(tmp, "l.jsonl"),
                ]
            )
            self.assertEqual(rc, EXIT_FAILURE)

    def test_corrupt_db_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(tmp)
            db_path = os.path.join(tmp, "d.db")
            with open(db_path, "wb") as handle:
                handle.write(b"not sqlite")
            rc = main(
                ["preflight", "--config", config_path, "--database", db_path, "--log", os.path.join(tmp, "l.jsonl")]
            )
            self.assertEqual(rc, EXIT_FAILURE)

    def test_log_path_is_directory_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(tmp)
            rc = main(
                [
                    "preflight",
                    "--config", config_path,
                    "--database", os.path.join(tmp, "d.db"),
                    "--log", tmp,  # directory
                ]
            )
            self.assertEqual(rc, EXIT_FAILURE)


class TestFailureInjection(unittest.TestCase):
    def _argv(self, tmp):
        config_path = _write_config(tmp)
        return [
            "preflight",
            "--config", config_path,
            "--database", os.path.join(tmp, "d.db"),
            "--log", os.path.join(tmp, "l.jsonl"),
        ]

    def test_initialize_database_failure_returns_one_and_shutdowns(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)
            with mock.patch("tgrid.main.initialize_database", side_effect=RuntimeError("db boom")), \
                 mock.patch("tgrid.main.shutdown_logger", wraps=real_shutdown_logger) as shutdown_mock:
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = main(argv)
            self.assertEqual(rc, EXIT_FAILURE)
            shutdown_mock.assert_called_once_with(LOGGER_NAME)
            self.assertNotIn("Traceback", err.getvalue())

    def test_emit_failure_returns_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)
            real_emit = __import__("tgrid.main", fromlist=["emit"]).emit

            def flaky_emit(logger, event, message, **kwargs):
                if event == "preflight_ok":
                    raise RuntimeError("emit boom")
                return real_emit(logger, event, message, **kwargs)

            with mock.patch("tgrid.main.emit", side_effect=flaky_emit), \
                 mock.patch("tgrid.main.shutdown_logger", wraps=real_shutdown_logger) as shutdown_mock:
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = main(argv)
            self.assertEqual(rc, EXIT_FAILURE)
            shutdown_mock.assert_called_once_with(LOGGER_NAME)

    def test_db_close_failure_returns_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)

            class FakeConn:
                def close(self):
                    raise OSError("close boom")

            with mock.patch("tgrid.main.initialize_database", return_value=FakeConn()), \
                 mock.patch("tgrid.main.shutdown_logger", wraps=real_shutdown_logger) as shutdown_mock:
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = main(argv)
            self.assertEqual(rc, EXIT_FAILURE)
            shutdown_mock.assert_called_once_with(LOGGER_NAME)

    def test_shutdown_logger_failure_returns_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)
            try:
                with mock.patch("tgrid.main.shutdown_logger", side_effect=RuntimeError("shutdown boom")):
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err):
                        rc = main(argv)
            finally:
                real_shutdown_logger(LOGGER_NAME)
            self.assertEqual(rc, EXIT_FAILURE)
            self.assertNotIn("Traceback", err.getvalue())

    def test_startup_and_shutdown_both_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)
            try:
                with mock.patch("tgrid.main.initialize_database", side_effect=RuntimeError("primary boom")), \
                     mock.patch("tgrid.main.shutdown_logger", side_effect=RuntimeError("cleanup boom")):
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err):
                        rc = main(argv)
            finally:
                real_shutdown_logger(LOGGER_NAME)
            self.assertEqual(rc, EXIT_FAILURE)
            text = err.getvalue()
            # Unknown exceptions are reported by type name only (no raw text).
            self.assertIn("error: RuntimeError", text)
            self.assertIn("cleanup error: RuntimeError", text)
            self.assertNotIn("primary boom", text)
            self.assertNotIn("cleanup boom", text)
            self.assertNotIn("Traceback", text)

    def test_keyboard_interrupt_returns_130(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)
            real_emit = __import__("tgrid.main", fromlist=["emit"]).emit

            def interrupt_startup(logger, event, message, **kwargs):
                if event == "startup_begin":
                    raise KeyboardInterrupt()
                return real_emit(logger, event, message, **kwargs)

            with mock.patch("tgrid.main.emit", side_effect=interrupt_startup), \
                 mock.patch("tgrid.main.shutdown_logger", wraps=real_shutdown_logger) as shutdown_mock:
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = main(argv)
            self.assertEqual(rc, EXIT_INTERRUPT)
            shutdown_mock.assert_called_once_with(LOGGER_NAME)


class TestIteration2Fixes(unittest.TestCase):
    """REV-G0T004-001..004 regression coverage."""

    def _argv(self, tmp):
        config_path = _write_config(tmp)
        return [
            "preflight",
            "--config", config_path,
            "--database", os.path.join(tmp, "d.db"),
            "--log", os.path.join(tmp, "l.jsonl"),
        ]

    # --- REV-G0T004-001: DB close failure must not record shutdown_complete ---

    def test_db_close_failure_no_shutdown_complete(self):
        import tgrid.reporting.logging as tlog

        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)

            class FailingCloseConn:
                def close(self):
                    raise OSError("close boom")

            with mock.patch("tgrid.main.initialize_database", return_value=FailingCloseConn()), \
                 mock.patch("tgrid.main.shutdown_logger", wraps=real_shutdown_logger) as shutdown_mock:
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = main(argv)

            self.assertEqual(rc, EXIT_FAILURE)
            shutdown_mock.assert_called_once_with(LOGGER_NAME)
            events = [r["event"] for r in _read_jsonl(argv[3])]
            self.assertNotIn("shutdown_complete", events)
            self.assertNotIn("tgrid.preflight", tlog._registry)
            self.assertNotIn("Traceback", err.getvalue())

    # --- REV-G0T004-002: KeyboardInterrupt during cleanup still shuts logger ---

    def test_keyboard_interrupt_during_db_close_shuts_logger(self):
        import tgrid.reporting.logging as tlog

        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)

            class InterruptingCloseConn:
                def close(self):
                    raise KeyboardInterrupt()

            with mock.patch("tgrid.main.initialize_database", return_value=InterruptingCloseConn()), \
                 mock.patch("tgrid.main.shutdown_logger", wraps=real_shutdown_logger) as shutdown_mock:
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = main(argv)

            self.assertEqual(rc, EXIT_INTERRUPT)
            shutdown_mock.assert_called_once_with(LOGGER_NAME)
            self.assertNotIn("tgrid.preflight", tlog._registry)
            events = [r["event"] for r in _read_jsonl(argv[3])]
            self.assertNotIn("shutdown_complete", events)

    def test_keyboard_interrupt_during_preflight_ok_shuts_logger(self):
        import tgrid.reporting.logging as tlog

        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)
            real_emit = __import__("tgrid.main", fromlist=["emit"]).emit

            def interrupt_ok(logger, event, message, **kwargs):
                if event == "preflight_ok":
                    raise KeyboardInterrupt()
                return real_emit(logger, event, message, **kwargs)

            with mock.patch("tgrid.main.emit", side_effect=interrupt_ok), \
                 mock.patch("tgrid.main.shutdown_logger", wraps=real_shutdown_logger) as shutdown_mock:
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = main(argv)

            self.assertEqual(rc, EXIT_INTERRUPT)
            shutdown_mock.assert_called_once_with(LOGGER_NAME)
            self.assertNotIn("tgrid.preflight", tlog._registry)

    # --- REV-G0T004-003: unknown exception before logger setup is contained ---

    def test_configure_unknown_exception_returns_one_no_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)
            with mock.patch(
                "tgrid.main.configure_jsonl_logger",
                side_effect=RuntimeError("SECRET_CONFIGURE_XYZ"),
            ):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = main(argv)
            self.assertEqual(rc, EXIT_FAILURE)
            text = err.getvalue()
            self.assertNotIn("Traceback", text)
            self.assertNotIn("SECRET_CONFIGURE_XYZ", text)

    # --- REV-G0T004-004: unknown exception text must not leak ---

    def test_unknown_exception_secret_not_leaked(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)
            with mock.patch(
                "tgrid.main.initialize_database",
                side_effect=RuntimeError("ACCOUNT_SECRET_XYZ"),
            ):
                out = io.StringIO()
                err = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = main(argv)
            self.assertEqual(rc, EXIT_FAILURE)
            for stream in (out.getvalue(), err.getvalue()):
                self.assertNotIn("ACCOUNT_SECRET_XYZ", stream)
                self.assertNotIn("Traceback", stream)
            # JSONL also must not contain the secret.
            log_path = argv[3]
            if os.path.isfile(log_path):
                with open(log_path, "r", encoding="utf-8") as handle:
                    self.assertNotIn("ACCOUNT_SECRET_XYZ", handle.read())

    def test_cleanup_secret_not_leaked(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)
            with mock.patch(
                "tgrid.main.shutdown_logger",
                side_effect=RuntimeError("CLEANUP_SECRET_XYZ"),
            ):
                try:
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err):
                        rc = main(argv)
                finally:
                    real_shutdown_logger(LOGGER_NAME)
            self.assertEqual(rc, EXIT_FAILURE)
            self.assertNotIn("CLEANUP_SECRET_XYZ", err.getvalue())
            self.assertNotIn("Traceback", err.getvalue())


class TestIteration3Fixes(unittest.TestCase):
    """REV-G0T004-005: DB close must live in a finally so BaseException cannot skip it."""

    def _argv(self, tmp):
        config_path = _write_config(tmp)
        return [
            "preflight",
            "--config", config_path,
            "--database", os.path.join(tmp, "d.db"),
            "--log", os.path.join(tmp, "l.jsonl"),
        ]

    def _tracked_conn(self, close_calls):
        class TrackedConn:
            def close(self):
                close_calls.append(True)

        return TrackedConn()

    def test_failure_event_keyboard_interrupt_closes_db(self):
        import tgrid.reporting.logging as tlog

        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)
            close_calls = []
            real_emit = __import__("tgrid.main", fromlist=["emit"]).emit

            def flaky_emit(logger, event, message, **kwargs):
                if event == "preflight_ok":
                    raise RuntimeError("preflight boom")
                if event == "preflight_failed":
                    raise KeyboardInterrupt()
                return real_emit(logger, event, message, **kwargs)

            with mock.patch(
                "tgrid.main.initialize_database",
                return_value=self._tracked_conn(close_calls),
            ), mock.patch("tgrid.main.emit", side_effect=flaky_emit), \
               mock.patch("tgrid.main.shutdown_logger", wraps=real_shutdown_logger):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = main(argv)

            self.assertEqual(rc, EXIT_INTERRUPT)
            self.assertEqual(close_calls, [True])
            self.assertNotIn("tgrid.preflight", tlog._registry)
            self.assertNotIn("preflight boom", err.getvalue())

    def test_system_exit_during_preflight_ok_still_closes_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)
            close_calls = []
            real_emit = __import__("tgrid.main", fromlist=["emit"]).emit

            def exit_ok(logger, event, message, **kwargs):
                if event == "preflight_ok":
                    raise SystemExit(7)
                return real_emit(logger, event, message, **kwargs)

            with mock.patch(
                "tgrid.main.initialize_database",
                return_value=self._tracked_conn(close_calls),
            ), mock.patch("tgrid.main.emit", side_effect=exit_ok), \
               mock.patch("tgrid.main.shutdown_logger", wraps=real_shutdown_logger) as shutdown_mock:
                with self.assertRaises(SystemExit) as cm:
                    main(argv)

            self.assertEqual(cm.exception.code, 7)
            self.assertEqual(close_calls, [True])
            shutdown_mock.assert_called_once_with(LOGGER_NAME)

    def test_generator_exit_during_preflight_ok_still_closes_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)
            close_calls = []
            real_emit = __import__("tgrid.main", fromlist=["emit"]).emit

            def gen_exit_ok(logger, event, message, **kwargs):
                if event == "preflight_ok":
                    raise GeneratorExit()
                return real_emit(logger, event, message, **kwargs)

            with mock.patch(
                "tgrid.main.initialize_database",
                return_value=self._tracked_conn(close_calls),
            ), mock.patch("tgrid.main.emit", side_effect=gen_exit_ok), \
               mock.patch("tgrid.main.shutdown_logger", wraps=real_shutdown_logger) as shutdown_mock:
                with self.assertRaises(GeneratorExit):
                    main(argv)

            self.assertEqual(close_calls, [True])
            shutdown_mock.assert_called_once_with(LOGGER_NAME)


class TestIteration4Fixes(unittest.TestCase):
    """REV-G0T004-006: DB close / shutdown emit BaseException must not skip logger shutdown."""

    def _argv(self, tmp):
        config_path = _write_config(tmp)
        return [
            "preflight",
            "--config", config_path,
            "--database", os.path.join(tmp, "d.db"),
            "--log", os.path.join(tmp, "l.jsonl"),
        ]

    def test_db_close_system_exit_still_shuts_logger(self):
        import tgrid.reporting.logging as tlog

        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)

            class SystemExitCloseConn:
                def close(self):
                    raise SystemExit(9)

            with mock.patch("tgrid.main.initialize_database", return_value=SystemExitCloseConn()), \
                 mock.patch("tgrid.main.shutdown_logger", wraps=real_shutdown_logger) as shutdown_mock:
                with self.assertRaises(SystemExit) as cm:
                    main(argv)

            self.assertEqual(cm.exception.code, 9)
            shutdown_mock.assert_called_once_with(LOGGER_NAME)
            self.assertNotIn("tgrid.preflight", tlog._registry)

    def test_shutdown_complete_generator_exit_still_shuts_logger(self):
        import tgrid.reporting.logging as tlog

        with tempfile.TemporaryDirectory() as tmp:
            argv = self._argv(tmp)
            real_emit = __import__("tgrid.main", fromlist=["emit"]).emit

            def gen_exit_shutdown(logger, event, message, **kwargs):
                if event == "shutdown_complete":
                    raise GeneratorExit()
                return real_emit(logger, event, message, **kwargs)

            with mock.patch("tgrid.main.emit", side_effect=gen_exit_shutdown), \
                 mock.patch("tgrid.main.shutdown_logger", wraps=real_shutdown_logger) as shutdown_mock:
                with self.assertRaises(GeneratorExit):
                    main(argv)

            shutdown_mock.assert_called_once_with(LOGGER_NAME)
            self.assertNotIn("tgrid.preflight", tlog._registry)


class TestOutputContract(unittest.TestCase):
    def test_failure_no_success_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = [
                "preflight",
                "--config", os.path.join(tmp, "missing.yaml"),
                "--database", os.path.join(tmp, "d.db"),
                "--log", os.path.join(tmp, "l.jsonl"),
            ]
            out = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = main(argv)
            self.assertEqual(rc, EXIT_FAILURE)
            self.assertNotIn("preflight ok", out.getvalue())
            self.assertNotIn("Traceback", err.getvalue())
            self.assertIn("error", err.getvalue())

    def test_no_sensitive_data_in_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(tmp)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = main(
                    [
                        "preflight",
                        "--config", config_path,
                        "--database", os.path.join(tmp, "d.db"),
                        "--log", os.path.join(tmp, "l.jsonl"),
                    ]
                )
            self.assertEqual(rc, EXIT_OK)
            text = out.getvalue()
            self.assertNotIn("core_qty", text)
            self.assertNotIn("600", text)
            self.assertNotIn("miniqmt", text)


class TestSubprocessSmoke(unittest.TestCase):
    def _run_module(self, *args):
        project_root = Path(__file__).resolve().parents[2]
        src = project_root / "src"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
        return subprocess.run(
            [sys.executable, "-m", "tgrid", *args],
            capture_output=True, text=True, env=env,
        )

    def test_version_smoke(self):
        proc = self._run_module("--version")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("0.1.0", proc.stdout)

    def test_help_smoke(self):
        proc = self._run_module("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("preflight", proc.stdout)


class TestForbiddenApiScan(unittest.TestCase):
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
                            "xtquant", alias.name.split(".")[0], f"xtquant import in {path}"
                        )
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(
                        "xtquant", (node.module or "").split(".")[0], f"xtquant import in {path}"
                    )

    def test_no_order_or_cancel_calls(self):
        # NODEB-001: the ONE concrete XtQuantBrokerBridge is the single
        # allowlisted exception; every other file must stay clean.
        allowlisted = Path("src/tgrid/integrations/xtquant_bridge.py")
        for path in self._package_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            is_bridge = path.as_posix().endswith(allowlisted.as_posix())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = (
                        func.attr
                        if isinstance(func, ast.Attribute)
                        else (func.id if isinstance(func, ast.Name) else None)
                    )
                    if name in {"order_stock", "cancel_order_stock"} and not is_bridge:
                        self.fail(
                            f"forbidden call {name} in {path} "
                            "(only xtquant_bridge.py may call the real surface)"
                        )


if __name__ == "__main__":
    unittest.main()
