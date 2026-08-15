"""Tests for the structured JSONL logging foundation (G0-T003)."""

import ast
import json
import logging
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tgrid.reporting import (
    SCHEMA_VERSION,
    configure_jsonl_logger,
    emit,
    shutdown_logger,
)
from tgrid.risk.exceptions import (
    LoggingConfigError,
    LoggingEmitError,
    LoggingError,
    TGridError,
)


def _temp_log_path():
    handle = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
    path = handle.name
    handle.close()
    os.remove(path)
    return path


def _read_lines(path):
    with open(path, "r", encoding="utf-8") as handle:
        return [line for line in handle.read().splitlines() if line.strip()]


def _parse_lines(path):
    return [json.loads(line) for line in _read_lines(path)]


class TestEventContract(unittest.TestCase):
    def test_basic_fields(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.basic", path)
        try:
            emit(logger, "start", "hello")
        finally:
            shutdown_logger("tgrid.test.basic")
        lines = _parse_lines(path)
        self.assertEqual(len(lines), 1)
        rec = lines[0]
        self.assertEqual(rec["schema_version"], SCHEMA_VERSION)
        self.assertTrue(rec["timestamp"].endswith("+00:00"))
        self.assertEqual(rec["level"], "INFO")
        self.assertEqual(rec["logger"], "tgrid.test.basic")
        self.assertEqual(rec["event"], "start")
        self.assertEqual(rec["message"], "hello")
        self.assertEqual(rec["context"], {})

    def test_utf8_roundtrip(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.utf8", path)
        try:
            emit(logger, "evt", "中文消息 with ünïcödé", context={"k": "值"})
        finally:
            shutdown_logger("tgrid.test.utf8")
        recs = _parse_lines(path)
        self.assertEqual(recs[0]["message"], "中文消息 with ünïcödé")
        self.assertEqual(recs[0]["context"]["k"], "值")

    def test_message_with_newline_and_quotes_still_single_line(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.multiline", path)
        try:
            emit(logger, "evt", 'line1\nline2 "quoted"')
        finally:
            shutdown_logger("tgrid.test.multiline")
        raw = _read_lines(path)
        self.assertEqual(len(raw), 1)
        rec = json.loads(raw[0])
        self.assertEqual(rec["message"], 'line1\nline2 "quoted"')

    def test_context_fields(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.ctx", path)
        try:
            emit(logger, "evt", "m", context={"a": 1, "b": [1, 2], "c": None, "d": True})
        finally:
            shutdown_logger("tgrid.test.ctx")
        rec = _parse_lines(path)[0]
        self.assertEqual(rec["context"], {"a": 1, "b": [1, 2], "c": None, "d": True})


class TestValidation(unittest.TestCase):
    def _logger(self):
        path = _temp_log_path()
        return configure_jsonl_logger("tgrid.test.val", path), path

    def test_empty_event_rejected(self):
        logger, path = self._logger()
        try:
            with self.assertRaises(LoggingEmitError):
                emit(logger, "", "m")
            with self.assertRaises(LoggingEmitError):
                emit(logger, "   ", "m")
        finally:
            shutdown_logger("tgrid.test.val")

    def test_reserved_field_conflict_rejected(self):
        logger, path = self._logger()
        try:
            with self.assertRaises(LoggingEmitError):
                emit(logger, "evt", "m", context={"timestamp": "x"})
            with self.assertRaises(LoggingEmitError):
                emit(logger, "evt", "m", context={"level": "x"})
        finally:
            shutdown_logger("tgrid.test.val")

    def test_non_string_context_key_rejected(self):
        logger, path = self._logger()
        try:
            with self.assertRaises(LoggingEmitError):
                emit(logger, "evt", "m", context={1: "x"})
        finally:
            shutdown_logger("tgrid.test.val")

    def test_unserializable_value_rejected(self):
        logger, path = self._logger()
        try:
            with self.assertRaises(LoggingEmitError):
                emit(logger, "evt", "m", context={"obj": object()})
        finally:
            shutdown_logger("tgrid.test.val")

    def test_invalid_level_rejected(self):
        logger, path = self._logger()
        try:
            with self.assertRaises(LoggingEmitError):
                emit(logger, "evt", "m", level="INFO")
        finally:
            shutdown_logger("tgrid.test.val")


class TestPathValidation(unittest.TestCase):
    def test_empty_path_rejected(self):
        for bad in ("", "   ", None):
            with self.assertRaises(LoggingConfigError):
                configure_jsonl_logger("tgrid.test.path", bad)

    def test_directory_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LoggingConfigError):
                configure_jsonl_logger("tgrid.test.path", tmp)

    def test_parent_directory_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = os.path.join(tmp, "a", "b", "log.jsonl")
            logger = configure_jsonl_logger("tgrid.test.path", nested)
            try:
                self.assertTrue(os.path.isfile(nested))
            finally:
                shutdown_logger("tgrid.test.path")


class TestLifecycle(unittest.TestCase):
    def test_reconfigure_same_logger_no_duplicate_lines(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.reconf", path)
        emit(logger, "first", "m1")
        # Reconfigure same logger; old handler must be closed, no duplicates.
        logger2 = configure_jsonl_logger("tgrid.test.reconf", path)
        emit(logger2, "second", "m2")
        shutdown_logger("tgrid.test.reconf")
        recs = _parse_lines(path)
        self.assertEqual(len(recs), 2)
        self.assertEqual([r["event"] for r in recs], ["first", "second"])

    def test_different_loggers_isolated(self):
        p1 = _temp_log_path()
        p2 = _temp_log_path()
        l1 = configure_jsonl_logger("tgrid.test.iso1", p1)
        l2 = configure_jsonl_logger("tgrid.test.iso2", p2)
        try:
            emit(l1, "a", "m")
            emit(l2, "b", "m")
        finally:
            shutdown_logger("tgrid.test.iso1")
            shutdown_logger("tgrid.test.iso2")
        self.assertEqual([r["event"] for r in _parse_lines(p1)], ["a"])
        self.assertEqual([r["event"] for r in _parse_lines(p2)], ["b"])

    def test_root_logger_untouched(self):
        root = logging.getLogger()
        before_handlers = list(root.handlers)
        before_level = root.level
        before_propagate = root.propagate
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.root", path)
        try:
            emit(logger, "e", "m")
        finally:
            shutdown_logger("tgrid.test.root")
        self.assertEqual(list(root.handlers), before_handlers)
        self.assertEqual(root.level, before_level)
        self.assertEqual(root.propagate, before_propagate)

    def test_propagate_false(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.prop", path)
        try:
            self.assertFalse(logger.propagate)
        finally:
            shutdown_logger("tgrid.test.prop")

    def test_shutdown_idempotent_and_releases_handle(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.shut", path)
        emit(logger, "e", "m")
        shutdown_logger("tgrid.test.shut")
        shutdown_logger("tgrid.test.shut")  # idempotent
        # File handle released: rename should succeed on Windows.
        renamed = path + ".moved"
        os.rename(path, renamed)
        self.assertTrue(os.path.isfile(renamed))


class TestFailureInjection(unittest.TestCase):
    def _inject_broken_stream(self, logger, write_ok=True):
        handler = logger.handlers[0]
        original = handler.stream

        class BrokenStream:
            def write(self, data):
                if not write_ok:
                    raise OSError("injected write failure")
                return len(data)

            def flush(self):
                raise OSError("injected flush failure")

        handler.stream = BrokenStream()
        return handler, original

    def test_write_failure_propagates(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.fail", path)
        handler, original = self._inject_broken_stream(logger, write_ok=False)
        try:
            with self.assertRaises(LoggingEmitError):
                emit(logger, "evt", "boom")
        finally:
            handler.stream = original
            shutdown_logger("tgrid.test.fail")

    def test_flush_failure_propagates(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.failflush", path)
        handler, original = self._inject_broken_stream(logger, write_ok=True)
        try:
            with self.assertRaises(LoggingEmitError):
                emit(logger, "evt", "boom")
        finally:
            handler.stream = original
            shutdown_logger("tgrid.test.failflush")

    def test_unserializable_via_file(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.fail2", path)
        try:
            with self.assertRaises(LoggingEmitError):
                emit(logger, "evt", "m", context={"bad": object()})
        finally:
            shutdown_logger("tgrid.test.fail2")
        # No half-written line must remain.
        self.assertEqual(_read_lines(path), [])


class TestConcurrency(unittest.TestCase):
    def test_concurrent_writes_all_present_and_parseable(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.concurrent", path)
        n = 200
        errors = []

        def worker(i):
            try:
                emit(logger, f"event_{i}", f"message {i}", context={"i": i})
            except Exception as exc:  # pragma: no cover - assertion helper
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        shutdown_logger("tgrid.test.concurrent")

        self.assertEqual(errors, [])
        recs = _parse_lines(path)
        self.assertEqual(len(recs), n)
        events = {r["event"] for r in recs}
        self.assertEqual(events, {f"event_{i}" for i in range(n)})


class TestExceptionHierarchy(unittest.TestCase):
    def test_hierarchy(self):
        self.assertTrue(issubclass(LoggingError, TGridError))
        self.assertTrue(issubclass(LoggingConfigError, LoggingError))
        self.assertTrue(issubclass(LoggingEmitError, LoggingError))


class TestIteration2Fixes(unittest.TestCase):
    """REV-G0T003-001..005 regression coverage."""

    # --- REV-G0T003-001: emit validates live/registered logger ---

    def test_emit_after_shutdown_rejected(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.after", path)
        shutdown_logger("tgrid.test.after")
        with self.assertRaises(LoggingEmitError):
            emit(logger, "evt", "m")

    def test_emit_unconfigured_rejected(self):
        logger = logging.getLogger("tgrid.test.unconfigured")
        with self.assertRaises(LoggingEmitError):
            emit(logger, "evt", "m")

    def test_emit_wrong_type_rejected(self):
        with self.assertRaises(LoggingEmitError):
            emit("not-a-logger", "evt", "m")
        with self.assertRaises(LoggingEmitError):
            emit(object(), "evt", "m")

    def test_emit_forged_logger_rejected(self):
        # A fresh Logger with a name that collides with a configured one is not
        # the registered object, so it must be rejected.
        path = _temp_log_path()
        configured = configure_jsonl_logger("tgrid.test.forge", path)
        forged = logging.getLogger("tgrid.test.forge")
        # Recreate a distinct object is impossible via getLogger; instead craft
        # a Logger instance sharing the name but not the registry identity.
        import logging as _logging

        fake = _logging.Logger("tgrid.test.forge")
        with self.assertRaises(LoggingEmitError):
            emit(fake, "evt", "m")
        # And the real one still works.
        emit(configured, "evt", "m")
        shutdown_logger("tgrid.test.forge")

    # --- REV-G0T003-002: name prefix restriction ---

    def test_root_name_rejected_and_root_untouched(self):
        root = logging.getLogger()
        before = (list(root.handlers), root.level, root.propagate)
        with self.assertRaises(LoggingConfigError):
            configure_jsonl_logger("root", _temp_log_path())
        after = (list(root.handlers), root.level, root.propagate)
        self.assertEqual(before, after)

    def test_third_party_name_rejected(self):
        for bad in ("root", "other", "", "   ", "tgrid.", "myapp.tgrid"):
            with self.assertRaises(LoggingConfigError):
                configure_jsonl_logger(bad, _temp_log_path())

    def test_child_name_accepted(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.child.name", path)
        try:
            emit(logger, "evt", "m")
        finally:
            shutdown_logger("tgrid.child.name")
        self.assertEqual([r["event"] for r in _parse_lines(path)], ["evt"])

    def test_tgrid_prefix_accepted(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid", path)
        try:
            emit(logger, "evt", "m")
        finally:
            shutdown_logger("tgrid")
        self.assertEqual([r["event"] for r in _parse_lines(path)], ["evt"])

    # --- REV-G0T003-003: FileHandler open failure boundary ---

    def test_open_failure_wrapped_as_config_error(self):
        path = _temp_log_path()
        with mock.patch(
            "tgrid.reporting.logging._JsonlFileHandler",
            side_effect=OSError("injected open failure"),
        ):
            with self.assertRaises(LoggingConfigError) as ctx:
                configure_jsonl_logger("tgrid.test.openfail", path)
        self.assertIsNotNone(ctx.exception.__cause__)
        # Nothing was registered.
        import tgrid.reporting.logging as tlog

        self.assertNotIn("tgrid.test.openfail", tlog._registry)

    # --- REV-G0T003-004: flush failure still closes old handler ---

    def test_reconfigure_flush_failure_closes_old_handler(self):
        p1 = _temp_log_path()
        p2 = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.flushclose", p1)
        old_handler = logger.handlers[0]
        close_called = []
        original_close = old_handler.close

        def raising_flush():
            raise OSError("injected flush failure")

        def spy_close():
            close_called.append(True)
            original_close()

        old_handler.flush = raising_flush
        old_handler.close = spy_close

        with self.assertRaises(LoggingEmitError):
            configure_jsonl_logger("tgrid.test.flushclose", p2)

        self.assertTrue(close_called, "old handler close() must be called even on flush failure")
        import tgrid.reporting.logging as tlog

        self.assertNotIn("tgrid.test.flushclose", tlog._registry)
        self.assertEqual(logger.handlers, [])

    # --- REV-G0T003-005: standard level whitelist ---

    def test_bool_level_rejected(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.levelbool", path)
        try:
            with self.assertRaises(LoggingEmitError):
                emit(logger, "evt", "m", level=True)
        finally:
            shutdown_logger("tgrid.test.levelbool")
        with self.assertRaises(LoggingConfigError):
            configure_jsonl_logger("tgrid.test.levelbool2", path, level=True)

    def test_unknown_and_negative_level_rejected(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.levelunknown", path)
        try:
            for bad in (12345, -7, 0):
                with self.assertRaises(LoggingEmitError):
                    emit(logger, "evt", "m", level=bad)
        finally:
            shutdown_logger("tgrid.test.levelunknown")

    def test_standard_levels_accepted(self):
        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.levelstd", path)
        try:
            for lvl, name in (
                (logging.DEBUG, "DEBUG"),
                (logging.INFO, "INFO"),
                (logging.WARNING, "WARNING"),
                (logging.ERROR, "ERROR"),
                (logging.CRITICAL, "CRITICAL"),
            ):
                emit(logger, f"evt_{name}", "m", level=lvl)
        finally:
            shutdown_logger("tgrid.test.levelstd")
        recs = _parse_lines(path)
        self.assertEqual([r["level"] for r in recs], ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])


class TestLifecycleConcurrency(unittest.TestCase):
    """REV-G0T003-006 / -007 deterministic interleavings."""

    def test_emit_shutdown_race_shutdown_waits_for_emit(self):
        # emit() begins (passes liveness check), then a concurrent shutdown must
        # wait for the emit to finish before closing; the file must contain one
        # complete line and the old path must not be recreated.
        import tgrid.reporting.logging as tlog

        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.race", path)

        emit_entered = threading.Event()
        allow_emit_finish = threading.Event()
        original_handle = tlog._registry["tgrid.test.race"].handle
        emit_done = []

        def slow_handle(record):
            emit_entered.set()
            allow_emit_finish.wait(timeout=5)
            return original_handle(record)

        handler = tlog._registry["tgrid.test.race"]
        handler.handle = slow_handle

        def do_emit():
            try:
                emit(logger, "evt", "message")
                emit_done.append("ok")
            except Exception as exc:  # pragma: no cover - test helper
                emit_done.append(f"err:{type(exc).__name__}")

        t = threading.Thread(target=do_emit)
        t.start()
        self.assertTrue(emit_entered.wait(timeout=5))

        shutdown_errors = []
        shutdown_done = threading.Event()

        def do_shutdown():
            try:
                shutdown_logger("tgrid.test.race")
            except Exception as exc:  # pragma: no cover - test helper
                shutdown_errors.append(exc)
            finally:
                shutdown_done.set()

        s = threading.Thread(target=do_shutdown)
        s.start()

        # Give shutdown a chance to run while emit is still in-flight.
        allow_emit_finish.set()
        t.join(timeout=5)
        s.join(timeout=5)

        self.assertEqual(emit_done, ["ok"])
        self.assertEqual(shutdown_errors, [])
        self.assertFalse(tlog._registry.get("tgrid.test.race"))
        self.assertEqual(logger.handlers, [])

        recs = _parse_lines(path)
        self.assertEqual([r["event"] for r in recs], ["evt"])

    def test_emit_after_shutdown_does_not_reopen_file(self):
        import tgrid.reporting.logging as tlog

        path = _temp_log_path()
        logger = configure_jsonl_logger("tgrid.test.raceshut", path)
        shutdown_logger("tgrid.test.raceshut")
        with self.assertRaises(LoggingEmitError):
            emit(logger, "evt", "m")
        self.assertNotIn("tgrid.test.raceshut", tlog._registry)

    def test_concurrent_configure_same_name_single_handler(self):
        import tgrid.reporting.logging as tlog

        paths = [_temp_log_path() for _ in range(4)]
        errors = []

        def configure(p):
            try:
                configure_jsonl_logger("tgrid.test.conc", p)
            except Exception as exc:  # pragma: no cover - test helper
                errors.append(exc)

        threads = [threading.Thread(target=configure, args=(p,)) for p in paths]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        logger = logging.getLogger("tgrid.test.conc")
        tgrid_handlers = [
            h for h in logger.handlers if isinstance(h, tlog._JsonlFileHandler)
        ]
        self.assertEqual(len(tgrid_handlers), 1)
        self.assertIs(tlog._registry.get("tgrid.test.conc"), tgrid_handlers[0])

        emit(logger, "evt", "m")
        shutdown_logger("tgrid.test.conc")
        self.assertEqual(logger.handlers, [])
        self.assertNotIn("tgrid.test.conc", tlog._registry)


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
                            "xtquant", alias.name.split(".")[0],
                            f"xtquant import in {path}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(
                        "xtquant", (node.module or "").split(".")[0],
                        f"xtquant import in {path}",
                    )

    def test_no_order_or_cancel_calls(self):
        for path in self._package_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = (
                        func.attr
                        if isinstance(func, ast.Attribute)
                        else (func.id if isinstance(func, ast.Name) else None)
                    )
                    self.assertNotIn(
                        name, {"order_stock", "cancel_order_stock"},
                        f"forbidden call {name} in {path}",
                    )


if __name__ == "__main__":
    unittest.main()
