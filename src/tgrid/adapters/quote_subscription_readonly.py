"""Single quote-subscription lifecycle adapter boundary (Gate 1, offline).

This module never imports or touches XtQuant.  Each adapter instance manages at
most one ``subscribe_quote`` subscription through two frozen client callables
(``subscribe_quote`` / ``unsubscribe_quote``), recording state, sequence id and
failure type explicitly.  It never invokes the callback, never connects, and
never joins an Event Queue or business logic.

Failures surface as safe project exceptions whose public text, ``__cause__``
and ``__context__`` never carry the original exception or any argument value.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Callable, Optional

from tgrid.risk.exceptions import (
    QuoteSubscriptionConfigError,
    QuoteSubscriptionError,
    QuoteSubscriptionLifecycleError,
    QuoteSubscriptionStartError,
    QuoteSubscriptionStopError,
    QuoteSubscriptionValidationError,
)

_BASE_EXCEPTIONS = (KeyboardInterrupt, SystemExit, GeneratorExit)


class QuoteSubscriptionState(Enum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


def _reject(name: str, expected: str) -> None:
    # Message carries only the parameter name and the fixed constraint, never
    # the offending value's repr or message.
    raise QuoteSubscriptionValidationError(f"{name}: expected {expected}") from None


class ReadOnlyQuoteSubscriptionAdapter:
    """Single-subscription read-only facade over an injected quote client.

    The injected ``client`` is resolved exactly once into two frozen bound
    callables and never exposed publicly.  Lifecycle transitions are serialized
    under a single operation lock and fail closed: external failures mark the
    adapter FAILED with a type-only ``failure_type`` and surface as safe project
    exceptions with a clean exception graph.
    """

    def __init__(self, client: object) -> None:
        self._methods = self._resolve_client_methods(client)
        self._op_lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._state = QuoteSubscriptionState.NEW
        self._sequence_id: Optional[int] = None
        self._failure_type: Optional[str] = None
        # Whether unsubscribe has already been attempted; guarantees at-most-once
        # cleanup even after a FAILED state or a cleanup exception.
        self._stop_attempted = False

    # -- construction: freeze the two subscribe/unsubscribe callables ---------

    @staticmethod
    def _resolve_client_methods(client: object) -> dict:
        """Validate and freeze ``subscribe_quote`` and ``unsubscribe_quote``.

        Literal attribute reads only (no ``getattr``, no runtime-derived name),
        each guarded individually: a missing attribute or a raising descriptor
        is a configuration failure surfaced as a safe
        ``QuoteSubscriptionConfigError`` (clean exception graph); Base
        exceptions propagate.  The resolved bound callables are frozen and never
        re-resolved afterwards.
        """
        if client is None:
            raise QuoteSubscriptionConfigError("client must not be None")
        problems: list = []

        def _read(name: str, thunk):
            try:
                return thunk()
            except BaseException as exc:
                if isinstance(exc, _BASE_EXCEPTIONS):
                    raise
                problems.append(name)
                return None

        subscribe = _read("subscribe_quote", lambda: client.subscribe_quote)
        unsubscribe = _read("unsubscribe_quote", lambda: client.unsubscribe_quote)
        methods: dict = {}
        for name, value in (("subscribe_quote", subscribe), ("unsubscribe_quote", unsubscribe)):
            if name in problems:
                continue
            if not callable(value):
                problems.append(name)
            else:
                methods[name] = value
        if problems:
            # Raised outside any active except block: __cause__/__context__
            # never carry the original attribute exception.
            raise QuoteSubscriptionConfigError(
                f"client of type {type(client).__name__} must provide callable "
                f"methods: {', '.join(sorted(set(problems)))}"
            ) from None
        return methods

    # -- state / failure visibility -------------------------------------------

    @property
    def state(self) -> QuoteSubscriptionState:
        with self._state_lock:
            return self._state

    @property
    def sequence_id(self) -> Optional[int]:
        with self._state_lock:
            return self._sequence_id

    @property
    def failure_type(self) -> Optional[str]:
        with self._state_lock:
            return self._failure_type

    def raise_if_failed(self) -> None:
        with self._state_lock:
            if self._state is QuoteSubscriptionState.FAILED:
                name = self._failure_type or "unknown"
                raise QuoteSubscriptionError(f"adapter failed: {name}")

    # -- lifecycle ------------------------------------------------------------

    def subscribe(
        self,
        stock_code: str,
        callback: Callable[[object], None],
        *,
        period: str = "tick",
        start_time: str = "",
        end_time: str = "",
        count: int = 0,
    ) -> int:
        with self._op_lock:
            with self._state_lock:
                if self._state is not QuoteSubscriptionState.NEW:
                    raise QuoteSubscriptionLifecycleError(
                        f"subscribe requires NEW, got {self._state.value}"
                    )
            self._validate_subscribe_args(
                stock_code, callback, period, start_time, end_time, count
            )
            result, failure = self._run_op(
                self._methods["subscribe_quote"],
                stock_code,
                period,
                start_time,
                end_time,
                count,
                callback,
            )
            if failure is not None:
                raise QuoteSubscriptionStartError(
                    f"subscribe_quote failed: {failure}"
                ) from None
            if not self._is_plain_nonneg_int(result):
                self._mark_failed(type(result).__name__)
                raise QuoteSubscriptionStartError(
                    "subscribe_quote returned an invalid sequence id: "
                    f"expected a plain int >= 0, got {type(result).__name__}"
                ) from None
            with self._state_lock:
                self._sequence_id = result
                self._state = QuoteSubscriptionState.ACTIVE
            return result

    def stop(self) -> None:
        with self._op_lock:
            with self._state_lock:
                if self._state is QuoteSubscriptionState.STOPPED:
                    return  # idempotent
                if self._state is QuoteSubscriptionState.NEW:
                    # Never subscribed: nothing to unsubscribe.
                    self._state = QuoteSubscriptionState.STOPPED
                    return
                if self._stop_attempted:
                    return  # cleanup already attempted; never retry
                # REV-G1T004-001: cleanup eligibility is decided by a validated
                # saved sequence id, never by the FAILED state alone.  A FAILED
                # subscribe that never produced a valid id must not call
                # unsubscribe_quote(None).
                if self._sequence_id is None:
                    return
                seq = self._sequence_id
            with self._state_lock:
                self._stop_attempted = True
            result, failure = self._run_op(
                self._methods["unsubscribe_quote"], seq
            )
            if failure is not None:
                raise QuoteSubscriptionStopError(
                    f"unsubscribe_quote failed: {failure}"
                ) from None
            with self._state_lock:
                if self._state is not QuoteSubscriptionState.FAILED:
                    self._state = QuoteSubscriptionState.STOPPED

    # -- validation -----------------------------------------------------------

    @staticmethod
    def _validate_subscribe_args(
        stock_code: object,
        callback: object,
        period: object,
        start_time: object,
        end_time: object,
        count: object,
    ) -> None:
        if not isinstance(stock_code, str) or not stock_code:
            _reject("stock_code", "a non-empty string")
        if not callable(callback):
            _reject("callback", "callable")
        if not isinstance(period, str) or not period:
            _reject("period", "a non-empty string")
        if not isinstance(start_time, str):
            _reject("start_time", "a string")
        if not isinstance(end_time, str):
            _reject("end_time", "a string")
        if isinstance(count, bool) or type(count) is not int or count < 0:
            _reject("count", "a plain int >= 0")

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _is_plain_nonneg_int(value: object) -> bool:
        return type(value) is int and value >= 0

    def _run_op(self, method: object, *args):
        """Invoke a frozen client method with the safe exception contract.

        Returns ``(result, None)`` on success.  On an ordinary ``Exception``
        marks FAILED and returns ``(None, type_name)``; the caller raises the
        project exception OUTSIDE any active ``except`` block so ``__cause__``
        and ``__context__`` never carry the original exception.  Base
        exceptions are re-raised after marking FAILED.
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
            self._state = QuoteSubscriptionState.FAILED
            self._failure_type = failure_type
