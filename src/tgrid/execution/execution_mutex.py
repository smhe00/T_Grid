"""Cross-process execution mutex — ported from reverse_repo (pinned c9ecc70).

Ports ``reverse_repo/scripts/repo_execution_core.py`` ``ExecutionMutex``:
a file-backed advisory lock that guarantees at most ONE executor process runs
a given trading day/session.  On Windows it uses ``msvcrt.locking`` (byte
range, non-blocking); on POSIX ``fcntl.flock`` (``LOCK_EX | LOCK_NB``).  The
owner writes its pid + timestamp into the lock file so a stale lock is
diagnosable.  The OS releases the lock automatically when the owning process
exits, so a crash never leaves the trading session permanently locked.

``timeout_seconds=0`` means try-once: a held lock raises
:class:`ConcurrentExecutionError` immediately instead of polling.
"""

from __future__ import annotations

import os
import time
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Any

from tgrid.risk.exceptions import TGridError


class ConcurrentExecutionError(TGridError):
    """Another process owns the execution lock."""


class ExecutionMutex(AbstractContextManager["ExecutionMutex"]):
    """File-backed cross-process mutual exclusion around a trading session.

    Usable as a context manager (reverse_repo style) or with the explicit
    :meth:`acquire` / :meth:`release` pair (used by the LiveStack session).
    """

    def __init__(
        self,
        path: object,
        *,
        timeout_seconds: float = 0.0,
        poll_seconds: float = 0.20,
    ) -> None:
        if type(timeout_seconds) not in (int, float) or isinstance(timeout_seconds, bool):
            raise TGridError("timeout_seconds must be a plain number")
        if type(poll_seconds) not in (int, float) or isinstance(poll_seconds, bool):
            raise TGridError("poll_seconds must be a plain number")
        self.path = Path(path).resolve()
        self.timeout_seconds = max(float(timeout_seconds), 0.0)
        self.poll_seconds = max(float(poll_seconds), 0.01)
        self._handle: Any = None

    # ------------------------------------------------------------ lifecycle

    def acquire(self) -> "ExecutionMutex":
        """Acquire the lock (try-once by default); raises on contention."""
        self.__enter__()
        return self

    def release(self) -> None:
        """Release the lock (idempotent; safe when never acquired)."""
        self.__exit__(None, None, None)

    def __enter__(self) -> "ExecutionMutex":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0)
            deadline = time.monotonic() + self.timeout_seconds
            while True:
                try:
                    self._lock_handle(handle)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise ConcurrentExecutionError(
                            "another executor process owns the execution lock"
                        ) from exc
                    time.sleep(
                        min(
                            self.poll_seconds,
                            max(0.0, deadline - time.monotonic()),
                        )
                    )
            handle.seek(0)
            handle.truncate()
            handle.write(
                (
                    f"pid={os.getpid()} "
                    f"at={datetime.now().astimezone().isoformat()}\n"
                ).encode()
            )
            handle.flush()
            os.fsync(handle.fileno())
            self._handle = handle
            return self
        except Exception:
            handle.close()
            raise

    @staticmethod
    def _lock_handle(handle: Any) -> None:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(
                handle.fileno(),
                msvcrt.LK_NBLCK,
                1,
            )
        else:
            import fcntl

            fcntl.flock(
                handle.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
