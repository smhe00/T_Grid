"""Read-only MarketData query adapter boundary (Gate 1, offline).

This module never imports or touches XtQuant.  It calls only the *fixed* set of
read-only query methods on an injected ``client`` object (frozen at construction
into private bound callables) and validates every argument against an explicit
contract before any underlying call.  No subscription, download, connection,
account, or trading capability exists here, and no dynamic forwarding.

Failures surface as safe project exceptions whose public text, ``__cause__``
and ``__context__`` never carry the original exception, an illegal argument
value, or any client representation.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

from tgrid.risk.exceptions import (
    MarketDataAdapterConfigError,
    MarketDataQueryError,
    MarketDataValidationError,
)

_BASE_EXCEPTIONS = (KeyboardInterrupt, SystemExit, GeneratorExit)
_NO_EXTRA_ARG = object()


def _reject(name: str, expected: str) -> None:
    # Message carries only the parameter name and the expected type/constraint,
    # never the offending value's repr or message (validation contract item 4).
    raise MarketDataValidationError(f"{name}: expected {expected}") from None


def _require_nonempty_string(value: object, name: str) -> None:
    if not isinstance(value, str) or not value:
        _reject(name, "a non-empty string")


def _require_string(value: object, name: str) -> None:
    if not isinstance(value, str):
        _reject(name, "a string")


def _require_bool(value: object, name: str) -> None:
    if type(value) is not bool:
        _reject(name, "a bool")


def _require_count(value: object, name: str) -> None:
    if isinstance(value, bool) or type(value) is not int:
        _reject(name, "a plain int (-1 or a positive integer)")
    if value != -1 and value <= 0:
        _reject(name, "a plain int (-1 or a positive integer)")


def _snapshot_symbol_sequence(value: object, name: str, *, allow_empty: bool) -> list:
    """Materialize a sequence parameter exactly once and validate the snapshot.

    REV-G1T003-001: the caller's object is observed only through a single
    ``list(value)`` snapshot.  That snapshot is used both for member validation
    and for the underlying call, so a stateful/malicious Sequence can never be
    seen twice or swapped between validation and invocation, and a raising
    ``__len__``/``__iter__``/``__getitem__`` cannot leak its message.

    A string/bytes is a Sequence but is explicitly rejected: the contract
    requires a real sequence of codes/fields, not a single code string.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _reject(name, "a non-string sequence")
    iter_error = False
    try:
        # A list comprehension iterates without the C-level length hint, so a
        # malicious ``__len__`` is never called (REV-G1T003-001).
        snapshot = [item for item in value]
    except BaseException as exc:
        if isinstance(exc, _BASE_EXCEPTIONS):
            raise
        iter_error = True
    if iter_error:
        # Raised OUTSIDE the active except block: __cause__/__context__ stay
        # None and the original iterator exception is unreachable.
        _reject(name, "a non-string sequence of non-empty strings")
    if not allow_empty and len(snapshot) == 0:
        _reject(name, "a non-empty sequence")
    for item in snapshot:
        if not isinstance(item, str) or not item:
            _reject(name, "a sequence of non-empty strings")
    return snapshot


class ReadOnlyMarketDataAdapter:
    """Strictly read-only facade over an injected MarketData query client.

    The injected ``client`` is resolved exactly once in the constructor into
    eight frozen bound callables and is never exposed publicly afterwards.
    Every public method validates its arguments first (no underlying call on
    validation failure) and then invokes the frozen callable; ordinary failures
    surface as safe ``MarketDataQueryError`` objects with a clean exception
    graph, while ``KeyboardInterrupt``/``SystemExit``/``GeneratorExit``
    propagate untouched.
    """

    def __init__(self, client: object) -> None:
        self._methods = self._resolve_client_methods(client)

    # -- construction: freeze the 8 read-only query methods -------------------

    @staticmethod
    def _resolve_client_methods(client: object) -> dict:
        """Validate and freeze the 8 fixed read-only query methods.

        Literal attribute reads only (no ``getattr``, no runtime-derived name),
        each guarded individually: a missing attribute or a raising descriptor
        is a configuration failure surfaced as a safe
        ``MarketDataAdapterConfigError`` (clean exception graph); Base
        exceptions propagate.  The resolved bound callables are frozen and never
        re-resolved afterwards (mirrors the G1-T002 frozen-callable contract).
        """
        if client is None:
            raise MarketDataAdapterConfigError("client must not be None")
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
            ("get_full_tick", _read("get_full_tick", lambda: client.get_full_tick)),
            ("get_market_data", _read("get_market_data", lambda: client.get_market_data)),
            ("get_market_data_ex", _read("get_market_data_ex", lambda: client.get_market_data_ex)),
            ("get_instrument_detail", _read("get_instrument_detail", lambda: client.get_instrument_detail)),
            ("get_divid_factors", _read("get_divid_factors", lambda: client.get_divid_factors)),
            ("get_trading_calendar", _read("get_trading_calendar", lambda: client.get_trading_calendar)),
            ("get_trading_dates", _read("get_trading_dates", lambda: client.get_trading_dates)),
            ("get_trading_period", _read("get_trading_period", lambda: client.get_trading_period)),
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
            # Raised outside any active except block, so __cause__ and
            # __context__ never carry the original attribute exception.
            raise MarketDataAdapterConfigError(
                f"client of type {type(client).__name__} must provide callable "
                f"read-only query methods: {', '.join(sorted(set(problems)))}"
            ) from None
        return methods

    # -- public read-only queries ---------------------------------------------

    def get_full_tick(self, stock_codes: Sequence[str]) -> object:
        codes = _snapshot_symbol_sequence(
            stock_codes, "stock_codes", allow_empty=False
        )
        return self._query(
            "get_full_tick",
            self._methods["get_full_tick"],
            codes,
        )

    def get_market_data(
        self,
        field_list: Sequence[str],
        stock_list: Sequence[str],
        period: str,
        *,
        start_time: str = "",
        end_time: str = "",
        count: int = -1,
        dividend_type: str = "none",
        fill_data: bool = True,
    ) -> object:
        fields = _snapshot_symbol_sequence(
            field_list, "field_list", allow_empty=True
        )
        stocks = _snapshot_symbol_sequence(
            stock_list, "stock_list", allow_empty=False
        )
        _require_nonempty_string(period, "period")
        _require_string(start_time, "start_time")
        _require_string(end_time, "end_time")
        _require_count(count, "count")
        _require_string(dividend_type, "dividend_type")
        _require_bool(fill_data, "fill_data")
        return self._query(
            "get_market_data",
            self._methods["get_market_data"],
            fields,
            stocks,
            period,
            start_time,
            end_time,
            count,
            dividend_type,
            fill_data,
        )

    def get_market_data_ex(
        self,
        field_list: Sequence[str],
        stock_list: Sequence[str],
        period: str,
        *,
        start_time: str = "",
        end_time: str = "",
        count: int = -1,
        dividend_type: str = "none",
        fill_data: bool = True,
    ) -> object:
        fields = _snapshot_symbol_sequence(
            field_list, "field_list", allow_empty=True
        )
        stocks = _snapshot_symbol_sequence(
            stock_list, "stock_list", allow_empty=False
        )
        _require_nonempty_string(period, "period")
        _require_string(start_time, "start_time")
        _require_string(end_time, "end_time")
        _require_count(count, "count")
        _require_string(dividend_type, "dividend_type")
        _require_bool(fill_data, "fill_data")
        return self._query(
            "get_market_data_ex",
            self._methods["get_market_data_ex"],
            fields,
            stocks,
            period,
            start_time,
            end_time,
            count,
            dividend_type,
            fill_data,
        )

    def get_instrument_detail(
        self, stock_code: str, *, complete: bool = False
    ) -> object:
        _require_nonempty_string(stock_code, "stock_code")
        _require_bool(complete, "complete")
        return self._query(
            "get_instrument_detail",
            self._methods["get_instrument_detail"],
            stock_code,
            complete,
        )

    def get_divid_factors(
        self,
        stock_code: str,
        *,
        start_time: str = "",
        end_time: str = "",
    ) -> object:
        _require_nonempty_string(stock_code, "stock_code")
        _require_string(start_time, "start_time")
        _require_string(end_time, "end_time")
        return self._query(
            "get_divid_factors",
            self._methods["get_divid_factors"],
            stock_code,
            start_time,
            end_time,
        )

    def get_trading_calendar(
        self,
        market: str,
        *,
        start_time: str = "",
        end_time: str = "",
    ) -> object:
        _require_nonempty_string(market, "market")
        _require_string(start_time, "start_time")
        _require_string(end_time, "end_time")
        return self._query(
            "get_trading_calendar",
            self._methods["get_trading_calendar"],
            market,
            start_time,
            end_time,
        )

    def get_trading_dates(
        self,
        market: str,
        *,
        start_time: str = "",
        end_time: str = "",
        count: int = -1,
    ) -> object:
        _require_nonempty_string(market, "market")
        _require_string(start_time, "start_time")
        _require_string(end_time, "end_time")
        _require_count(count, "count")
        return self._query(
            "get_trading_dates",
            self._methods["get_trading_dates"],
            market,
            start_time,
            end_time,
            count,
        )

    def get_trading_period(self, stock_code: str) -> object:
        _require_nonempty_string(stock_code, "stock_code")
        return self._query(
            "get_trading_period",
            self._methods["get_trading_period"],
            stock_code,
        )

    # -- internals ------------------------------------------------------------

    def _query(self, operation: str, method: object, *args) -> object:
        result, failure = self._run_client_op(method, *args)
        if failure is not None:
            # Raised outside the active except block: __cause__/__context__
            # stay None and the original exception is unreachable.
            raise MarketDataQueryError(
                f"{operation} failed: {failure}"
            ) from None
        if result is None:
            raise MarketDataQueryError(f"{operation} returned None") from None
        return result

    def _run_client_op(self, method: object, *args):
        """Invoke a frozen client method with the safe exception contract.

        Returns ``(result, None)`` on success.  On an ordinary ``Exception``
        returns ``(None, type_name)``; the caller raises the project exception
        OUTSIDE any active ``except`` block.  Base exceptions are re-raised.
        """
        try:
            return method(*args), None
        except BaseException as exc:
            if isinstance(exc, _BASE_EXCEPTIONS):
                raise
            return None, type(exc).__name__
