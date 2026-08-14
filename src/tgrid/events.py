"""Single-consumer, bounded, FIFO event queue skeleton (Gate 0).

This is the thread boundary the design (§3.1) will use for QMT callback
isolation: callbacks will only ``enqueue`` and the single worker thread will be
the only place handler logic runs.  This task provides the queue and lifecycle
only — no QMT, strategy, order, or real event types.

Lifecycle:

    NEW --start--> RUNNING --stop--> STOPPING --drain--> STOPPED
                             |
                             +-- handler BaseException --> FAILED

Concurrency: every state read/transition and every enqueue decision happens
under a single condition lock, so ``stop`` vs ``enqueue`` is serialized and no
event accepted before ``STOPPING`` is dropped or duplicated.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from enum import Enum
from typing import Any, Callable, Optional

from tgrid.risk.exceptions import (
    EventQueueConfigError,
    EventQueueFull,
    EventQueueLifecycleError,
    EventQueueWorkerError,
)


class EventQueueState(Enum):
    NEW = "NEW"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


def _validate_handler(handler: Any) -> None:
    if not callable(handler):
        raise EventQueueConfigError(
            f"handler must be callable, got {type(handler).__name__}"
        )


def _validate_maxsize(maxsize: Any) -> int:
    if isinstance(maxsize, bool) or type(maxsize) is not int:
        raise EventQueueConfigError(
            f"maxsize must be a positive integer, got {type(maxsize).__name__}"
        )
    if maxsize <= 0:
        raise EventQueueConfigError(f"maxsize must be > 0, got {maxsize}")
    return maxsize


def _validate_thread_name(thread_name: Any) -> str:
    if not isinstance(thread_name, str) or not thread_name.strip():
        raise EventQueueConfigError("thread_name must be a non-empty string")
    return thread_name


def _validate_timeout(timeout: Any) -> Optional[float]:
    if timeout is None:
        return None
    if isinstance(timeout, bool) or type(timeout) not in (int, float):
        raise EventQueueConfigError(
            f"timeout must be None or a non-negative finite number, got {type(timeout).__name__}"
        )
    value = float(timeout)
    if value < 0 or not math.isfinite(value):
        raise EventQueueConfigError(
            f"timeout must be a non-negative finite number, got {timeout}"
        )
    return value


class EventQueue:
    """A thread-safe, capacity-bounded, FIFO, single-worker event queue."""

    def __init__(
        self,
        handler: Callable[[object], Any],
        *,
        maxsize: int,
        thread_name: str = "tgrid-event-loop",
    ) -> None:
        _validate_handler(handler)
        _validate_maxsize(maxsize)
        _validate_thread_name(thread_name)

        self._handler = handler
        self._maxsize = maxsize
        self._thread_name = thread_name
        self._queue: "queue.Queue[object]" = queue.Queue(maxsize=maxsize)
        self._cond = threading.Condition(threading.Lock())
        self._state = EventQueueState.NEW
        self._worker: Optional[threading.Thread] = None
        self._failure_type: Optional[str] = None
        # Two-phase start handshake: True between "worker object created" and
        # "the OS thread has actually been started".  Guards against a phantom
        # RUNNING while never holding the lifecycle lock across Thread.start()
        # (REV-G0T005-001 / -004).
        self._starting = False

    # -- state / failure visibility (guarded by self._cond) -------------------

    @property
    def state(self) -> EventQueueState:
        with self._cond:
            return self._state

    @property
    def failure_type(self) -> Optional[str]:
        with self._cond:
            return self._failure_type

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        with self._cond:
            if self._state is EventQueueState.RUNNING or self._starting:
                return  # idempotent: never spawn a second worker
            if self._state is not EventQueueState.NEW:
                raise EventQueueLifecycleError(
                    f"cannot start queue from state {self._state.value}"
                )
            worker = threading.Thread(
                target=self._run,
                name=self._thread_name,
                daemon=False,
            )
            self._worker = worker
            self._starting = True
            # Publish nothing yet: state stays NEW until the OS thread really
            # starts, so no caller can observe RUNNING prematurely.
        # Phase 1 completes: the lifecycle lock is released BEFORE the external
        # Thread.start() call so stop()/join() are never blocked by a slow start
        # (REV-G0T005-004).  Only one worker object exists (_starting guard).
        try:
            worker.start()
        except Exception as exc:  # noqa: BLE001 - worker start boundary
            with self._cond:
                self._starting = False
                self._worker = None
                self._state = EventQueueState.FAILED
                self._failure_type = type(exc).__name__
                self._cond.notify_all()
            raise EventQueueLifecycleError(
                f"failed to start event queue worker: {type(exc).__name__}"
            ) from None
        # Phase 2: publish RUNNING only if stop() did not already move us to a
        # terminal state while the OS start was in progress.
        with self._cond:
            self._starting = False
            if self._state is EventQueueState.NEW:
                self._state = EventQueueState.RUNNING
            self._cond.notify_all()

    def enqueue(self, event: object) -> None:
        with self._cond:
            if self._state is not EventQueueState.RUNNING:
                raise EventQueueLifecycleError(
                    f"cannot enqueue in state {self._state.value}"
                )
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                # Convert without chaining queue.Full: the public exception must
                # not expose the standard-library type via cause or traceback
                # (REV-G0T005-003).
                raise EventQueueFull("event queue is full") from None
            # Wake the worker; the count under the lock is authoritative.
            self._cond.notify()

    def stop(self) -> None:
        with self._cond:
            if self._state is EventQueueState.NEW:
                # Covers never-started and start-in-progress: prompt, remembers
                # the request (start() phase 2 will not publish RUNNING), and
                # wakes any join() waiter.
                self._state = EventQueueState.STOPPED
                self._cond.notify_all()
                return
            if self._state in (
                EventQueueState.STOPPING,
                EventQueueState.STOPPED,
                EventQueueState.FAILED,
            ):
                return  # idempotent
            # RUNNING -> STOPPING: reject all future enqueue; drain accepted items.
            self._state = EventQueueState.STOPPING
            self._cond.notify_all()

    def join(self, timeout: Optional[float] = None) -> bool:
        validated = _validate_timeout(timeout)
        # One monotonic deadline bounds the whole call, including waiting for a
        # start() that is still in its OS Thread.start() phase (REV-G0T005-004).
        deadline = None if validated is None else time.monotonic() + validated

        with self._cond:
            # Wait for the start handshake: the thread must actually have been
            # OS-started before it is joinable (REV-G0T005-004).
            while self._starting:
                if deadline is None:
                    self._cond.wait()
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    self._cond.wait(remaining)
            # Re-read the worker UNDER THE LOCK after the handshake so a
            # concurrent start failure (which clears _worker) is observed; the
            # pre-wait cached object may still reference an unstarted thread and
            # must never be joined (REV-G0T005-005).
            worker = self._worker
            if worker is None:
                # Never started (NEW / STOPPED-from-NEW) or start failed -> no
                # actual OS thread to join.
                return True
            if threading.current_thread() is worker:
                raise EventQueueLifecycleError(
                    "worker thread cannot join itself"
                )

        if deadline is None:
            worker.join()
        else:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return not worker.is_alive()
            worker.join(remaining)
        return not worker.is_alive()

    def raise_if_failed(self) -> None:
        with self._cond:
            if self._state is EventQueueState.FAILED:
                # User-facing message contains only the exception type, never the
                # original message, repr, traceback, or event content.
                name = self._failure_type or "unknown"
                raise EventQueueWorkerError(f"event queue worker failed: {name}")

    # -- worker internals (only ever runs on the single worker thread) --------

    def _run(self) -> None:
        while True:
            with self._cond:
                if self._state is EventQueueState.STOPPING and self._queue.empty():
                    self._state = EventQueueState.STOPPED
                    self._cond.notify_all()
                    return
                if self._state is EventQueueState.STOPPED or self._state is EventQueueState.FAILED:
                    return
                if self._queue.empty():
                    # Bounded wait: periodic re-check so a worker is never stuck
                    # forever if a state change was somehow not notified.
                    self._cond.wait(timeout=0.5)
                    continue
                event = self._queue.get_nowait()

            # Handler runs outside the lock; only the worker thread reaches here.
            try:
                self._handler(event)
            except BaseException as exc:  # noqa: BLE001 - worker boundary
                with self._cond:
                    self._state = EventQueueState.FAILED
                    self._failure_type = type(exc).__name__
                    # Stop dispatch and drop all still-pending items.
                    while True:
                        try:
                            self._queue.get_nowait()
                        except queue.Empty:
                            break
                    self._cond.notify_all()
                return
