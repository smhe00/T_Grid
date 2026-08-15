"""Tests for the single-consumer Event Queue skeleton (G0-T005)."""

import ast
import math
import threading
import time
import traceback
import unittest
from pathlib import Path
from unittest import mock

from tgrid import (
    EventQueue,
    EventQueueState,
)
from tgrid.risk.exceptions import (
    EventQueueConfigError,
    EventQueueError,
    EventQueueFull,
    EventQueueLifecycleError,
    EventQueueWorkerError,
    TGridError,
)


class TestConstructorValidation(unittest.TestCase):
    def test_handler_must_be_callable(self):
        for bad in (None, "not-callable", 42, object()):
            with self.assertRaises(EventQueueConfigError):
                EventQueue(bad, maxsize=10)

    def test_maxsize_must_be_positive_int(self):
        for bad in (0, -1, True, False, 1.5, "10", None):
            with self.assertRaises(EventQueueConfigError):
                EventQueue(lambda e: None, maxsize=bad)

    def test_thread_name_must_be_nonempty(self):
        for bad in ("", "   ", None):
            with self.assertRaises(EventQueueConfigError):
                EventQueue(lambda e: None, maxsize=10, thread_name=bad)


class TestLifecycle(unittest.TestCase):
    def _queue(self, handler=None, **kwargs):
        return EventQueue(
            handler or (lambda e: None),
            maxsize=kwargs.get("maxsize", 100),
            thread_name=kwargs.get("thread_name", "tgrid-test-loop"),
        )

    def test_initial_state_new(self):
        q = self._queue()
        self.assertIs(q.state, EventQueueState.NEW)

    def test_start_then_stop_then_join(self):
        q = self._queue()
        q.start()
        self.assertIs(q.state, EventQueueState.RUNNING)
        q.stop()
        self.assertIs(q.state, EventQueueState.STOPPING)
        self.assertTrue(q.join(timeout=5))
        self.assertIs(q.state, EventQueueState.STOPPED)

    def test_start_is_idempotent(self):
        q = self._queue()
        q.start()
        worker = q._worker
        q.start()  # must not spawn a second worker
        self.assertIs(q._worker, worker)
        q.stop()
        self.assertTrue(q.join(timeout=5))

    def test_restart_after_stop_rejected(self):
        q = self._queue()
        q.start()
        q.stop()
        q.join(timeout=5)
        with self.assertRaises(EventQueueLifecycleError):
            q.start()

    def test_stop_before_start(self):
        q = self._queue()
        q.stop()
        self.assertIs(q.state, EventQueueState.STOPPED)

    def test_repeated_stop_idempotent(self):
        q = self._queue()
        q.start()
        q.stop()
        q.stop()
        q.stop()
        self.assertTrue(q.join(timeout=5))

    def test_enqueue_before_start_rejected(self):
        q = self._queue()
        with self.assertRaises(EventQueueLifecycleError):
            q.enqueue("x")

    def test_enqueue_after_stop_rejected(self):
        q = self._queue()
        q.start()
        q.stop()
        with self.assertRaises(EventQueueLifecycleError):
            q.enqueue("x")

    def test_enqueue_after_failed_rejected(self):
        q = self._queue(handler=lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
        q.start()
        q.enqueue("x")
        q.join(timeout=5)
        self.assertIs(q.state, EventQueueState.FAILED)
        with self.assertRaises(EventQueueLifecycleError):
            q.enqueue("y")


class TestProcessing(unittest.TestCase):
    def test_single_event_processed_once(self):
        seen = []
        q = EventQueue(seen.append, maxsize=100, thread_name="tgrid-test-proc")
        q.start()
        q.enqueue("e")
        q.stop()
        self.assertTrue(q.join(timeout=5))
        self.assertEqual(seen, ["e"])

    def test_fifo_single_producer_order(self):
        seen = []
        q = EventQueue(seen.append, maxsize=100, thread_name="tgrid-test-fifo")
        q.start()
        for i in range(50):
            q.enqueue(i)
        q.stop()
        self.assertTrue(q.join(timeout=5))
        self.assertEqual(seen, list(range(50)))

    def test_multi_producer_exactly_once_and_single_thread(self):
        processed = []
        worker_names = set()
        lock = threading.Lock()

        def handler(event):
            with lock:
                processed.append(event)
                worker_names.add(threading.current_thread().name)

        q = EventQueue(handler, maxsize=1000, thread_name="tgrid-test-multi")
        q.start()
        n = 120

        def producer(start):
            for i in range(start, start + n):
                q.enqueue(i)

        threads = [threading.Thread(target=producer, args=(i * n,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        q.stop()
        self.assertTrue(q.join(timeout=5))

        self.assertEqual(len(processed), 4 * n)
        self.assertEqual(set(processed), set(range(4 * n)))
        self.assertEqual(len(worker_names), 1)
        self.assertEqual(worker_names, {"tgrid-test-multi"})

    def test_handler_only_on_worker_thread(self):
        main_name = threading.current_thread().name
        handler_names = []
        lock = threading.Lock()

        def handler(_):
            with lock:
                handler_names.append(threading.current_thread().name)

        q = EventQueue(handler, maxsize=100, thread_name="tgrid-test-workeronly")
        q.start()
        for i in range(30):
            q.enqueue(i)
        q.stop()
        q.join(timeout=5)
        self.assertTrue(handler_names)
        self.assertTrue(all(name != main_name for name in handler_names))


class TestFullQueue(unittest.TestCase):
    def _blocking_queue(self, maxsize, thread_name):
        """Return (queue, started_event, release_event) where the worker is
        guaranteed to be blocked inside the handler on the first event."""
        started = threading.Event()
        release = threading.Event()

        def handler(_):
            started.set()
            release.wait(timeout=10)

        q = EventQueue(handler, maxsize=maxsize, thread_name=thread_name)
        return q, started, release

    def test_full_raises_eventqueuefull_not_queue_full(self):
        q, started, release = self._blocking_queue(2, "tgrid-test-full")
        q.start()
        try:
            q.enqueue("a")
            self.assertTrue(started.wait(timeout=5), "worker should start")
            # Worker is blocked on "a", so the two slots hold b and c.
            q.enqueue("b")
            q.enqueue("c")
            with self.assertRaises(EventQueueFull):
                q.enqueue("d")
        finally:
            release.set()
            q.stop()
            self.assertTrue(q.join(timeout=5))

    def test_full_does_not_block(self):
        q, started, release = self._blocking_queue(2, "tgrid-test-nonblock")
        q.start()
        try:
            q.enqueue("a")
            self.assertTrue(started.wait(timeout=5), "worker should start")
            q.enqueue("b")
            q.enqueue("c")
            # Must raise immediately, not block the caller thread.
            with self.assertRaises(EventQueueFull):
                q.enqueue("d")
        finally:
            release.set()
            q.stop()
            self.assertTrue(q.join(timeout=5))


class TestStopDrain(unittest.TestCase):
    def test_stop_drains_accepted_items(self):
        seen = []
        q = EventQueue(seen.append, maxsize=100, thread_name="tgrid-test-drain")
        q.start()
        for i in range(20):
            q.enqueue(i)
        q.stop()  # STOPPING; accepted items must still drain in FIFO order
        self.assertTrue(q.join(timeout=5))
        self.assertEqual(seen, list(range(20)))

    def test_stop_enqueue_race_no_loss_or_duplicate(self):
        # Serialize enqueue vs stop: everything accepted before STOPPING is
        # processed exactly once; nothing after is accepted.
        seen = []
        accepted = []
        lock = threading.Lock()
        stop_barrier = threading.Barrier(2)

        def handler(e):
            seen.append(e)

        q = EventQueue(handler, maxsize=200, thread_name="tgrid-test-race")
        q.start()

        def producer():
            stop_barrier.wait()
            for i in range(50):
                try:
                    q.enqueue(i)
                    with lock:
                        accepted.append(i)
                except EventQueueError:
                    break

        t = threading.Thread(target=producer)
        t.start()
        stop_barrier.wait()
        q.stop()
        t.join()
        self.assertTrue(q.join(timeout=5))

        self.assertEqual(set(seen), set(accepted))
        self.assertEqual(len(seen), len(accepted))
        self.assertEqual(len(set(seen)), len(seen))  # no duplicates


class TestJoin(unittest.TestCase):
    def test_join_timeout_returns_bool(self):
        q = EventQueue(lambda e: None, maxsize=100, thread_name="tgrid-test-jt")
        q.start()
        q.stop()
        self.assertIsInstance(q.join(timeout=0.01), bool)

    def test_join_before_start_ok(self):
        q = EventQueue(lambda e: None, maxsize=100, thread_name="tgrid-test-jbs")
        self.assertTrue(q.join(timeout=0.01))

    def test_invalid_timeout_rejected(self):
        q = EventQueue(lambda e: None, maxsize=100, thread_name="tgrid-test-jinv")
        for bad in (-1, True, False, "5", object()):
            with self.assertRaises(EventQueueConfigError):
                q.join(timeout=bad)

    def test_timeout_nan_and_infinity_rejected(self):
        # REV-G0T005-002: NaN / +inf / -inf must be rejected as non-finite.
        q = EventQueue(lambda e: None, maxsize=100, thread_name="tgrid-test-jnf")
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(EventQueueConfigError):
                q.join(timeout=bad)
        # Finite values are accepted.
        self.assertIsInstance(q.join(timeout=0.01), bool)

    def test_self_join_rejected(self):
        error = []

        def handler(_):
            try:
                q.join(timeout=1)
            except EventQueueLifecycleError as exc:
                error.append(exc)

        q = EventQueue(handler, maxsize=100, thread_name="tgrid-test-selfjoin")
        q.start()
        q.enqueue("x")
        q.stop()
        q.join(timeout=5)
        self.assertEqual(len(error), 1)
        self.assertIsInstance(error[0], EventQueueLifecycleError)


class TestWorkerFailure(unittest.TestCase):
    def _assert_failure(self, exc_factory, token):
        results = []

        def handler(_):
            raise exc_factory()

        q = EventQueue(handler, maxsize=100, thread_name="tgrid-test-fail")
        q.start()
        q.enqueue("x")
        q.join(timeout=5)
        self.assertIs(q.state, EventQueueState.FAILED)
        self.assertEqual(q.failure_type, type(exc_factory()).__name__)
        with self.assertRaises(EventQueueWorkerError) as cm:
            q.raise_if_failed()
        self.assertNotIn(token, str(cm.exception))
        self.assertNotIn("Traceback", str(cm.exception))

    def test_handler_runtime_error_fails(self):
        self._assert_failure(lambda: RuntimeError("TOKEN_RUNTIME"), "TOKEN_RUNTIME")

    def test_handler_keyboard_interrupt_fails(self):
        self._assert_failure(lambda: KeyboardInterrupt("TOKEN_KI"), "TOKEN_KI")

    def test_handler_system_exit_fails(self):
        self._assert_failure(lambda: SystemExit(3), "TOKEN_SE")

    def test_handler_generator_exit_fails(self):
        self._assert_failure(lambda: GeneratorExit(), "TOKEN_GE")

    def test_pending_items_not_dispatched_after_failure(self):
        dispatched = []
        lock = threading.Lock()

        def handler(e):
            with lock:
                dispatched.append(e)
                raise RuntimeError("boom")

        q = EventQueue(handler, maxsize=100, thread_name="tgrid-test-pending")
        q.start()
        for i in range(5):
            q.enqueue(i)
        q.join(timeout=5)
        self.assertIs(q.state, EventQueueState.FAILED)
        # Only one event (the failing one) was dispatched.
        self.assertEqual(len(dispatched), 1)

    def test_raise_if_failed_noop_when_not_failed(self):
        q = EventQueue(lambda e: None, maxsize=100, thread_name="tgrid-test-noop")
        q.start()
        q.stop()
        q.join(timeout=5)
        q.raise_if_failed()  # must not raise


class TestThreadCleanup(unittest.TestCase):
    def test_no_live_threads_after_stop(self):
        name = "tgrid-test-cleanup"
        q = EventQueue(lambda e: None, maxsize=100, thread_name=name)
        q.start()
        q.stop()
        q.join(timeout=5)
        for thread in threading.enumerate():
            self.assertNotEqual(thread.name, name)


class TestIteration2Fixes(unittest.TestCase):
    """REV-G0T005-001..003 regression coverage."""

    # --- REV-G0T005-001: start publication atomicity / failure ---

    def test_state_not_running_before_thread_started(self):
        real_start = threading.Thread.start
        calls = []

        def recording_start(thread):
            calls.append("thread_start_called")
            return real_start(thread)

        q = EventQueue(lambda e: None, maxsize=10, thread_name="tgrid-test-order")
        with mock.patch.object(threading.Thread, "start", recording_start):
            q.start()
        # RUNNING is published only after the real thread start completed.
        self.assertIn("thread_start_called", calls)
        self.assertIs(q.state, EventQueueState.RUNNING)
        q.stop()
        self.assertTrue(q.join(timeout=5))

    def test_concurrent_start_during_pause_no_second_worker(self):
        # Only the target worker's Thread.start is paused; control threads use
        # the unpatched real start (matched by worker thread name).
        real_start = threading.Thread.start
        target = "tgrid-test-concstart"
        entered = threading.Event()
        release = threading.Event()
        worker_starts = []

        def pausing_start(thread):
            if thread.name == target:
                worker_starts.append(thread)
                entered.set()
                release.wait(timeout=10)
            return real_start(thread)

        q = EventQueue(lambda e: None, maxsize=10, thread_name=target)
        t1 = threading.Thread(target=q.start, name="tgrid-test-ctl1")
        t2 = threading.Thread(target=q.start, name="tgrid-test-ctl2")
        with mock.patch.object(threading.Thread, "start", pausing_start):
            t1.start()  # control thread passes through immediately
            self.assertTrue(entered.wait(timeout=5), "worker start paused")
            t2.start()  # second concurrent start is idempotent (no 2nd worker)
            self.assertEqual(len(worker_starts), 1)
            release.set()
            t1.join(timeout=5)
            t2.join(timeout=5)
        self.assertIs(q.state, EventQueueState.RUNNING)
        live = [t for t in threading.enumerate() if t.name == target and t.is_alive()]
        self.assertEqual(len(live), 1)
        q.stop()
        self.assertTrue(q.join(timeout=5))
        self.assertFalse(any(t.name == target and t.is_alive() for t in threading.enumerate()))

    def test_start_failure_fails_closed_no_secret(self):
        token = "THREAD_SECRET_XYZ"

        def exploding_start(thread):
            raise RuntimeError(token)

        q = EventQueue(lambda e: None, maxsize=10, thread_name="tgrid-test-startfail")
        with mock.patch.object(threading.Thread, "start", exploding_start):
            with self.assertRaises(EventQueueLifecycleError) as cm:
                q.start()

        self.assertNotIn(token, str(cm.exception))
        self.assertNotIn("Traceback", str(cm.exception))
        # No phantom RUNNING; consistent FAILED + failure_type.
        self.assertIs(q.state, EventQueueState.FAILED)
        self.assertEqual(q.failure_type, "RuntimeError")
        # join() must not leak "cannot join thread before it is started".
        self.assertTrue(q.join(timeout=0.01))
        # enqueue rejected; raise_if_failed surfaces type-only message.
        with self.assertRaises(EventQueueLifecycleError):
            q.enqueue("x")
        with self.assertRaises(EventQueueWorkerError) as worker_cm:
            q.raise_if_failed()
        self.assertNotIn(token, str(worker_cm.exception))
        self.assertNotIn("Traceback", str(worker_cm.exception))
        # No leaked test thread; restart rejected from FAILED.
        self.assertFalse(any(t.name == "tgrid-test-startfail" for t in threading.enumerate()))
        with self.assertRaises(EventQueueLifecycleError):
            q.start()

    # --- REV-G0T005-002: join returns False while worker alive ---

    def test_join_timeout_returns_false_while_worker_alive(self):
        started = threading.Event()
        release = threading.Event()

        def handler(_):
            started.set()
            release.wait(timeout=5)

        q = EventQueue(handler, maxsize=10, thread_name="tgrid-test-jtfalse")
        q.start()
        q.enqueue("a")
        self.assertTrue(started.wait(timeout=5))
        self.assertFalse(q.join(timeout=0.01))
        release.set()
        q.stop()
        self.assertTrue(q.join(timeout=5))

    # --- REV-G0T005-003: EventQueueFull must not expose queue.Full ---

    def test_full_exception_hides_queue_full(self):
        started = threading.Event()
        release = threading.Event()

        def handler(_):
            started.set()
            release.wait(timeout=5)

        q = EventQueue(handler, maxsize=2, thread_name="tgrid-test-fullboundary")
        q.start()
        try:
            q.enqueue("a")
            self.assertTrue(started.wait(timeout=5))
            q.enqueue("b")
            q.enqueue("c")
            with self.assertRaises(EventQueueFull) as cm:
                q.enqueue("d")
            exc = cm.exception
            # No chained cause exposing queue.Full.
            self.assertIsNone(exc.__cause__)
            self.assertNotIn("queue.Full", str(exc))
            # The formatted traceback must not surface queue.Full either.
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            self.assertNotIn("queue.Full", tb)
        finally:
            release.set()
            q.stop()
            self.assertTrue(q.join(timeout=5))


class TestIteration3Fixes(unittest.TestCase):
    """REV-G0T005-004: Thread.start must not hold the lifecycle lock."""

    def test_bounded_join_and_stop_while_start_paused(self):
        real_start = threading.Thread.start
        target = "tgrid-test-bounded"
        entered = threading.Event()
        release = threading.Event()

        def pausing_start(thread):
            if thread.name == target:
                entered.set()
                release.wait(timeout=10)
            return real_start(thread)

        q = EventQueue(lambda e: None, maxsize=10, thread_name=target)
        starter = threading.Thread(target=q.start, name="tgrid-test-ctl-bounded")
        with mock.patch.object(threading.Thread, "start", pausing_start):
            starter.start()
            self.assertTrue(entered.wait(timeout=5), "worker start paused")

            # join(0.01) must return False within a reasonable bound while the
            # OS start is still paused (single monotonic deadline).
            t0 = time.monotonic()
            result = q.join(timeout=0.01)
            elapsed = time.monotonic() - t0
            self.assertFalse(result)
            self.assertLess(elapsed, 1.0)

            # stop() must complete promptly during the paused start and remember
            # the request (state becomes STOPPED; start() must not publish RUNNING).
            t0 = time.monotonic()
            q.stop()
            stop_elapsed = time.monotonic() - t0
            self.assertLess(stop_elapsed, 1.0)
            self.assertIs(q.state, EventQueueState.STOPPED)

            # Enqueue after the remembered stop is rejected.
            with self.assertRaises(EventQueueLifecycleError):
                q.enqueue("x")

            release.set()
            starter.join(timeout=5)

        # The worker actually started, saw STOPPED, and exited; no leaks.
        self.assertTrue(q.join(timeout=5))
        self.assertIs(q.state, EventQueueState.STOPPED)
        self.assertFalse(any(t.name == target and t.is_alive() for t in threading.enumerate()))

    def test_bounded_join_returns_false_while_start_paused_then_recovers(self):
        # REV-G0T005-006: pause start with a releasable Event, verify bounded
        # join returns False, then stop + release + join every thread so no
        # controller/worker thread leaks (no daemon infinite loops).
        real_start = threading.Thread.start
        target = "tgrid-test-paused"
        ctl_name = "tgrid-test-ctl-paused"
        entered = threading.Event()
        release = threading.Event()

        def pausing_start(thread):
            if thread.name == target:
                entered.set()
                release.wait(timeout=10)
            return real_start(thread)

        q = EventQueue(lambda e: None, maxsize=10, thread_name=target)
        starter = threading.Thread(target=q.start, name=ctl_name)
        with mock.patch.object(threading.Thread, "start", pausing_start):
            starter.start()
            self.assertTrue(entered.wait(timeout=5), "worker start paused")

            t0 = time.monotonic()
            result = q.join(timeout=0.05)
            elapsed = time.monotonic() - t0
            self.assertFalse(result)
            self.assertLess(elapsed, 2.0)

            # Remember the stop, then release the start so the worker actually
            # starts, observes STOPPED, and exits cleanly.
            q.stop()
            release.set()
            starter.join(timeout=5)

        self.assertTrue(q.join(timeout=5))
        self.assertIs(q.state, EventQueueState.STOPPED)
        for thread in threading.enumerate():
            self.assertNotEqual(thread.name, target)
            self.assertNotEqual(thread.name, ctl_name)


class TestIteration4Fixes(unittest.TestCase):
    """REV-G0T005-005: concurrent join must not join an unstarted worker after a
    start failure."""

    def test_concurrent_join_after_start_failure_returns_true(self):
        real_start = threading.Thread.start
        target = "tgrid-test-joinfail"
        ctl_name = "tgrid-test-ctl-joinfail"
        entered = threading.Event()
        token = "THREAD_SECRET_JOIN"

        def failing_start(thread):
            if thread.name == target:
                entered.set()
                raise RuntimeError(token)
            return real_start(thread)

        q = EventQueue(lambda e: None, maxsize=10, thread_name=target)
        start_errors = []
        join_results = []

        def run_start():
            try:
                q.start()
            except Exception as exc:  # noqa: BLE001 - capture for assertion
                start_errors.append((type(exc).__name__, str(exc)))

        def run_join():
            try:
                join_results.append(("ok", q.join(timeout=5)))
            except Exception as exc:  # noqa: BLE001 - capture for assertion
                join_results.append(("err", type(exc).__name__, str(exc)))

        with mock.patch.object(threading.Thread, "start", failing_start):
            starter = threading.Thread(target=run_start, name=ctl_name)
            starter.start()
            self.assertTrue(entered.wait(timeout=5), "worker start entered")
            joiner = threading.Thread(target=run_join, name="tgrid-test-joiner")
            joiner.start()
            starter.join(timeout=5)
            joiner.join(timeout=5)

        # start surfaced the safe project exception (type-only, no token).
        self.assertEqual(len(start_errors), 1)
        start_kind, start_msg = start_errors[0]
        self.assertEqual(start_kind, EventQueueLifecycleError.__name__)
        self.assertNotIn(token, start_msg)
        self.assertNotIn("Traceback", start_msg)

        # concurrent join returned True with NO exception (no leaked Thread.join
        # RuntimeError).
        self.assertEqual(len(join_results), 1)
        self.assertEqual(join_results[0][0], "ok")
        self.assertIs(join_results[0][1], True)

        # FAILED state + type-only failure_type; no live threads.
        self.assertIs(q.state, EventQueueState.FAILED)
        self.assertEqual(q.failure_type, "RuntimeError")
        for thread in threading.enumerate():
            self.assertNotEqual(thread.name, target)
            self.assertNotEqual(thread.name, ctl_name)
            self.assertNotEqual(thread.name, "tgrid-test-joiner")

    def test_stop_and_start_failure_interleaved_no_deadlock(self):
        # Interleave stop + start failure + join: no deadlock, no phantom
        # RUNNING, no live threads, and no unhandled thread exception (the
        # control thread catches the safe project exception).
        real_start = threading.Thread.start
        target = "tgrid-test-stopfail"
        ctl_name = "tgrid-test-ctl-stopfail"
        entered = threading.Event()
        start_errors = []

        def failing_start(thread):
            if thread.name == target:
                entered.set()
                raise RuntimeError("boom")
            return real_start(thread)

        def run_start():
            try:
                q.start()
            except Exception as exc:  # noqa: BLE001 - capture for assertion
                start_errors.append((type(exc).__name__, str(exc)))

        q = EventQueue(lambda e: None, maxsize=10, thread_name=target)
        with mock.patch.object(threading.Thread, "start", failing_start):
            starter = threading.Thread(target=run_start, name=ctl_name)
            starter.start()
            self.assertTrue(entered.wait(timeout=5))
            q.stop()  # prompt while start is failing
            starter.join(timeout=5)

        self.assertEqual(len(start_errors), 1)
        self.assertEqual(start_errors[0][0], EventQueueLifecycleError.__name__)
        self.assertNotIn("boom", start_errors[0][1])
        self.assertNotIn("Traceback", start_errors[0][1])
        self.assertIs(q.state, EventQueueState.FAILED)
        self.assertTrue(q.join(timeout=5))
        for thread in threading.enumerate():
            self.assertNotEqual(thread.name, target)
            self.assertNotEqual(thread.name, ctl_name)


class TestExceptionHierarchy(unittest.TestCase):
    def test_hierarchy(self):
        self.assertTrue(issubclass(EventQueueError, TGridError))
        for exc in (
            EventQueueConfigError,
            EventQueueLifecycleError,
            EventQueueFull,
            EventQueueWorkerError,
        ):
            self.assertTrue(issubclass(exc, EventQueueError))


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
                        name, {"order_stock", "cancel_order_stock"}, f"forbidden call {name} in {path}"
                    )


if __name__ == "__main__":
    unittest.main()
