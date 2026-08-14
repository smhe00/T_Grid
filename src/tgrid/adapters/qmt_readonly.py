"""Read-only QMT Trader adapter boundary (Gate 1, offline).

This module never imports or touches XtQuant.  It calls only the *fixed* set of
read-only methods on an injected ``client`` object and drives an explicit
lifecycle state machine whose failures surface as safe, type-only project
exceptions.

Deliberately absent: dynamic method forwarding, a public ``client`` property,
raw client exposure, and any order or cancel surface.  The forbidden trading
method names are not even written in this file.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Optional

from tgrid.risk.exceptions import (
    QmtAdapterConfigError,
    QmtAdapterLifecycleError,
    QmtConnectionError,
    QmtQueryError,
    QmtReadOnlyError,
)


class ReadOnlyTraderState(Enum):
    NEW = "NEW"
    STARTED = "STARTED"
    CONNECTED = "CONNECTED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


_BASE_EXCEPTIONS = (KeyboardInterrupt, SystemExit, GeneratorExit)
_NO_EXTRA_ARG = object()


def _is_plain_int(value: object) -> bool:
    # ``bool`` is an ``int`` subclass; connect/subscribe results must be plain ints.
    return type(value) is int


class ReadOnlyTraderAdapter:
    """Strictly read-only facade over an injected QMT trader client.

    The injected ``client`` is resolved exactly once in the constructor into
    eight frozen bound callables and is never exposed publicly afterwards.
    Lifecycle transitions are serialized under a single operation lock and fail
    closed: external failures mark the adapter FAILED with a type-only
    ``failure_type`` and surface as safe project exceptions whose public text,
    ``__cause__`` and ``__context__`` never carry the original exception.
    """

    def __init__(self, client: object) -> None:
        self._methods = self._resolve_client_methods(client)
        self._op_lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._state = ReadOnlyTraderState.NEW
        self._failure_type: Optional[str] = None
        # Whether the underlying client ``start`` succeeded; gates FAILED-state
        # cleanup in ``stop``.
        self._start_ok = False
        # Whether the underlying client ``stop`` has already been attempted;
        # guarantees at-most-once cleanup.
        self._stop_called = False

    # -- construction: freeze the 8 read-only client methods -------------------

    @staticmethod
    def _resolve_client_methods(client: object) -> dict:
        """Validate and freeze the 8 fixed read-only client methods.

        Every attribute read is a literal attribute access (no ``getattr``, no
        runtime-derived name), so no dynamic forwarding is possible.  A missing
        attribute or a raising descriptor is a *configuration* failure surfaced
        as a safe ``QmtAdapterConfigError``; the resolved bound callables are
        frozen for the life of the adapter and queries never re-resolve client
        attributes (REV-G1T002-002).
        """
        if client is None:
            raise QmtAdapterConfigError("client must not be None")
        problems: list = []

        def _read(name: str, thunk):
            try:
                return thunk()
            except BaseException as exc:
                if isinstance(exc, _BASE_EXCEPTIONS):
                    raise
                problems.append(name)
                return None

        values = (
            ("start", _read("start", lambda: client.start)),
            ("connect", _read("connect", lambda: client.connect)),
            ("subscribe", _read("subscribe", lambda: client.subscribe)),
            (
                "query_stock_asset",
                _read("query_stock_asset", lambda: client.query_stock_asset),
            ),
            (
                "query_stock_positions",
                _read("query_stock_positions", lambda: client.query_stock_positions),
            ),
            (
                "query_stock_orders",
                _read("query_stock_orders", lambda: client.query_stock_orders),
            ),
            (
                "query_stock_trades",
                _read("query_stock_trades", lambda: client.query_stock_trades),
            ),
            ("stop", _read("stop", lambda: client.stop)),
        )
        methods: dict = {}
        for name, value in values:
            if name in problems:
                continue  # already recorded as unreadable
            if not callable(value):
                problems.append(name)
            else:
                methods[name] = value
        if problems:
            # Raised here, outside any active except block, so __cause__ and
            # __context__ never carry the original attribute exception.
            raise QmtAdapterConfigError(
                f"client of type {type(client).__name__} must provide callable "
                f"read-only methods: {', '.join(sorted(set(problems)))}"
            ) from None
        return methods

    # -- state / failure visibility -------------------------------------------

    @property
    def state(self) -> ReadOnlyTraderState:
        with self._state_lock:
            return self._state

    @property
    def failure_type(self) -> Optional[str]:
        with self._state_lock:
            return self._failure_type

    def raise_if_failed(self) -> None:
        with self._state_lock:
            if self._state is ReadOnlyTraderState.FAILED:
                name = self._failure_type or "unknown"
                raise QmtReadOnlyError(f"adapter failed: {name}")

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        with self._op_lock:
            with self._state_lock:
                if self._state in (
                    ReadOnlyTraderState.STARTED,
                    ReadOnlyTraderState.CONNECTED,
                ):
                    return  # idempotent: never start the client twice
                if self._state is not ReadOnlyTraderState.NEW:
                    raise QmtAdapterLifecycleError(
                        f"cannot start adapter from state {self._state.value}"
                    )
            self._invoke_client_start()

    def connect(self) -> None:
        with self._op_lock:
            with self._state_lock:
                if self._state is not ReadOnlyTraderState.STARTED:
                    raise QmtAdapterLifecycleError(
                        f"connect requires STARTED, got {self._state.value}"
                    )
            result, failure = self._run_client_op(self._methods["connect"])
            if failure is not None:
                raise QmtConnectionError(f"connect failed: {failure}") from None
            if not _is_plain_int(result):
                self._mark_failed(type(result).__name__)
                raise QmtConnectionError(
                    "connect failed: expected int 0, "
                    f"returned {type(result).__name__}"
                ) from None
            if result != 0:
                self._mark_failed(str(result))
                raise QmtConnectionError(
                    f"connect failed: non-zero return code {result}"
                ) from None
            with self._state_lock:
                self._state = ReadOnlyTraderState.CONNECTED

    def subscribe(self, account: object) -> None:
        with self._op_lock:
            with self._state_lock:
                if self._state is not ReadOnlyTraderState.CONNECTED:
                    raise QmtAdapterLifecycleError(
                        f"subscribe requires CONNECTED, got {self._state.value}"
                    )
            result, failure = self._run_client_op(
                self._methods["subscribe"], account
            )
            if failure is not None:
                raise QmtConnectionError(
                    f"subscribe failed: {failure}"
                ) from None
            if not _is_plain_int(result):
                self._mark_failed(type(result).__name__)
                raise QmtConnectionError(
                    "subscribe failed: expected int 0, "
                    f"returned {type(result).__name__}"
                ) from None
            if result != 0:
                self._mark_failed(str(result))
                raise QmtConnectionError(
                    f"subscribe failed: non-zero return code {result}"
                ) from None

    def stop(self) -> None:
        with self._op_lock:
            with self._state_lock:
                if self._state is ReadOnlyTraderState.STOPPED:
                    return  # idempotent
                if self._state is ReadOnlyTraderState.NEW:
                    # Never started: nothing to stop on the client.
                    self._state = ReadOnlyTraderState.STOPPED
                    return
                if self._state is ReadOnlyTraderState.FAILED:
                    # Clean up only when the client was actually started and we
                    # have not already attempted a stop.
                    if not self._start_ok or self._stop_called:
                        return
            with self._state_lock:
                self._stop_called = True
            result, failure = self._run_client_op(self._methods["stop"])
            if failure is not None:
                raise QmtAdapterLifecycleError(
                    f"stop failed: {failure}"
                ) from None
            with self._state_lock:
                if self._state is not ReadOnlyTraderState.FAILED:
                    self._state = ReadOnlyTraderState.STOPPED

    # -- read-only queries ----------------------------------------------------

    def query_asset(self, account: object) -> object:
        with self._op_lock:
            return self._query(
                "query_asset", self._methods["query_stock_asset"], account
            )

    def query_positions(self, account: object) -> object:
        with self._op_lock:
            return self._query(
                "query_positions", self._methods["query_stock_positions"], account
            )

    def query_orders(
        self, account: object, *, cancelable_only: bool = False
    ) -> object:
        with self._op_lock:
            return self._query(
                "query_orders",
                self._methods["query_stock_orders"],
                account,
                cancelable_only,
            )

    def query_trades(self, account: object) -> object:
        with self._op_lock:
            return self._query(
                "query_trades", self._methods["query_stock_trades"], account
            )

    # -- internals ------------------------------------------------------------

    def _query(
        self,
        operation: str,
        method: object,
        account: object,
        extra: object = _NO_EXTRA_ARG,
    ) -> object:
        with self._state_lock:
            if self._state is not ReadOnlyTraderState.CONNECTED:
                raise QmtAdapterLifecycleError(
                    f"{operation} requires CONNECTED, got {self._state.value}"
                )
        if extra is not _NO_EXTRA_ARG and type(extra) is not bool:
            raise QmtQueryError(
                f"{operation} cancelable_only must be a bool, "
                f"got {type(extra).__name__}"
            )
        if extra is _NO_EXTRA_ARG:
            args = (account,)
        else:
            args = (account, extra)
        result, failure = self._run_client_op(method, *args)
        if failure is not None:
            raise QmtQueryError(f"{operation} failed: {failure}") from None
        if result is None:
            self._mark_failed("None result")
            raise QmtQueryError(f"{operation} returned None") from None
        return result

    def _invoke_client_start(self) -> None:
        # Runs under _op_lock; never calls the client while holding _state_lock.
        result, failure = self._run_client_op(self._methods["start"])
        if failure is not None:
            raise QmtAdapterLifecycleError(
                f"start failed: {failure}"
            ) from None
        with self._state_lock:
            self._start_ok = True
            self._state = ReadOnlyTraderState.STARTED

    def _run_client_op(self, method: object, *args):
        """Invoke a frozen client method with the safe exception contract.

        Returns ``(result, None)`` on success.  On an ordinary ``Exception``
        marks FAILED and returns ``(None, type_name)``; the caller raises the
        project exception OUTSIDE any active ``except`` block, so ``__cause__``
        and ``__context__`` never carry the original exception (REV-G1T002-001).
        Base exceptions are re-raised after marking FAILED.
        """
        try:
            return method(*args), None
        except BaseException as exc:
            self._mark_failed(type(exc).__name__)
            if isinstance(exc, _BASE_EXCEPTIONS):
                raise
            return None, type(exc).__name__

    def _mark_failed(self, failure_type: str) -> None:
        # Called while holding _op_lock; takes _state_lock so state readers
        # observe the transition atomically.
        with self._state_lock:
            self._state = ReadOnlyTraderState.FAILED
            self._failure_type = failure_type
