"""reverse_repo ExecutionMutex port: cross-process execution lock tests.

Covers acquire/release, same-process contention (fail closed), poll-based
timeout acquisition, pid ownership marker, and release on exit — the TGrid
guard for "at most one executor process per trade date".
"""

import os
import tempfile
import threading
import time
import unittest

from tgrid.execution.execution_mutex import (
    ConcurrentExecutionError,
    ExecutionMutex,
)


def _lock_path() -> str:
    return os.path.join(tempfile.mkdtemp(), "tgrid-exec.lock")


class TestExecutionMutex(unittest.TestCase):
    def test_acquire_release_roundtrip(self):
        path = _lock_path()
        mutex = ExecutionMutex(path)
        mutex.acquire()
        self.assertTrue(os.path.exists(path))
        mutex.release()
        # The pid marker persists in the lock file after release (the lock
        # file itself is never truncated on release).
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn(f"pid={os.getpid()}", content)
        # Released: a fresh mutex can re-acquire immediately.
        ExecutionMutex(path).acquire().release()
        os.remove(path)

    def test_second_acquire_fails_closed_while_held(self):
        path = _lock_path()
        first = ExecutionMutex(path)
        first.acquire()
        try:
            second = ExecutionMutex(path)
            with self.assertRaises(ConcurrentExecutionError):
                second.acquire()
            # Not held: releasing the failed lock is a safe no-op.
            second.release()
        finally:
            first.release()
        # After release the same mutex object can be re-acquired.
        first.acquire()
        first.release()
        os.remove(path)

    def test_timeout_waits_for_release(self):
        path = _lock_path()
        first = ExecutionMutex(path)
        first.acquire()
        try:
            second = ExecutionMutex(path, timeout_seconds=3.0, poll_seconds=0.05)
            release_at = time.monotonic() + 0.2

            def _release_later():
                while time.monotonic() < release_at:
                    time.sleep(0.01)
                first.release()

            thread = threading.Thread(target=_release_later)
            thread.start()
            second.acquire()  # blocks until the first owner releases
            thread.join(timeout=2.0)
            second.release()
        finally:
            if first._handle is not None:
                first.release()
        os.remove(path)

    def test_timeout_zero_does_not_poll(self):
        path = _lock_path()
        first = ExecutionMutex(path)
        first.acquire()
        try:
            started = time.monotonic()
            with self.assertRaises(ConcurrentExecutionError):
                ExecutionMutex(path, timeout_seconds=0.0).acquire()
            self.assertLess(time.monotonic() - started, 1.0)
        finally:
            first.release()
        os.remove(path)

    def test_context_manager_acquire_and_release(self):
        path = _lock_path()
        with ExecutionMutex(path):
            # Held inside the block: a second acquire fails closed.
            with self.assertRaises(ConcurrentExecutionError):
                ExecutionMutex(path).acquire()
        # Exited: lock released.
        ExecutionMutex(path).acquire().release()
        os.remove(path)

    def test_release_idempotent_when_never_acquired(self):
        path = _lock_path()
        mutex = ExecutionMutex(path)
        mutex.release()  # no-op, must not raise
        mutex.release()
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
