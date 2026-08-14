"""Gate 1 read-only integration probe orchestrator (offline).

Combines the approved ``ReadOnlyTraderAdapter`` and ``ReadOnlyMarketDataAdapter``
into a fixed-order probe of 15 read-only operations plus at-most-once trader
cleanup.  It never imports XtQuant, never connects to QMT, never reads a real
account/market, and returns only a data-free audit summary.  All query results
are discarded; the runner must not observe repr/str/len/iter on account,
symbols, or returned objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from tgrid.adapters.marketdata_readonly import ReadOnlyMarketDataAdapter
from tgrid.adapters.qmt_readonly import ReadOnlyTraderAdapter
from tgrid.risk.exceptions import (
    Gate1ProbeConfigError,
    Gate1ProbeExecutionError,
)

_BASE_EXCEPTIONS = (KeyboardInterrupt, SystemExit, GeneratorExit)

# Fixed, data-free operation names in exact execution order.  The runner only
# ever records these literals; the final summary exposes only this fixed tuple.
_COMPLETED_NAMES = (
    "trader.start",
    "trader.connect",
    "trader.subscribe",
    "trader.query_asset",
    "trader.query_positions",
    "trader.query_orders",
    "trader.query_trades",
    "market_data.get_full_tick",
    "market_data.get_market_data",
    "market_data.get_market_data_ex",
    "market_data.get_instrument_detail",
    "market_data.get_divid_factors",
    "market_data.get_trading_calendar",
    "market_data.get_trading_dates",
    "market_data.get_trading_period",
)


@dataclass(frozen=True)
class Gate1ReadOnlyProbeSummary:
    """Fixed, data-free audit summary of a Gate 1 read-only probe.

    ``completed_operations`` is always a literal-name tuple and carries no
    object types, return counts, symbols, account values, or any data.
    """

    completed_operations: tuple
    cleanup_completed: bool


def _require_type(value: object, expected_type: type, name: str) -> None:
    # Exact type check (not isinstance) so a subclass override or duck-typed
    # raw client cannot bypass the approved adapter boundary.
    if type(value) is not expected_type:
        raise Gate1ProbeConfigError(
            f"{name} must be exactly {expected_type.__name__}"
        ) from None


def run_gate1_readonly_probe(
    trader: ReadOnlyTraderAdapter,
    market_data: ReadOnlyMarketDataAdapter,
    account: object,
    stock_code: str,
    exchange: str,
) -> Gate1ReadOnlyProbeSummary:
    """Run the fixed Gate 1 read-only probe sequence with guaranteed cleanup.

    Raises ``Gate1ProbeConfigError`` before any adapter call for invalid
    arguments, and ``Gate1ProbeExecutionError`` (data-free) if an operation or
    its cleanup fails.  ``KeyboardInterrupt``/``SystemExit``/``GeneratorExit``
    propagate after at-most-once cleanup.
    """
    _require_type(trader, ReadOnlyTraderAdapter, "trader")
    _require_type(market_data, ReadOnlyMarketDataAdapter, "market_data")
    if account is None:
        raise Gate1ProbeConfigError("account must not be None") from None
    if not isinstance(stock_code, str) or not stock_code:
        raise Gate1ProbeConfigError("stock_code must be a non-empty string") from None
    if not isinstance(exchange, str) or not exchange:
        raise Gate1ProbeConfigError("exchange must be a non-empty string") from None

    completed = []
    # Tracker for at-most-once cleanup, set True only when stop() has actually
    # been attempted (whether or not it succeeded).
    stop_attempted = False

    def _run_operations() -> None:
        # 1-7 trader lifecycle + read-only queries (fixed order, exact args).
        trader.start()
        completed.append(_COMPLETED_NAMES[0])
        trader.connect()
        completed.append(_COMPLETED_NAMES[1])
        trader.subscribe(account)
        completed.append(_COMPLETED_NAMES[2])
        trader.query_asset(account)
        completed.append(_COMPLETED_NAMES[3])
        trader.query_positions(account)
        completed.append(_COMPLETED_NAMES[4])
        trader.query_orders(account, cancelable_only=False)
        completed.append(_COMPLETED_NAMES[5])
        trader.query_trades(account)
        completed.append(_COMPLETED_NAMES[6])
        # 8-15 market data read-only queries.
        market_data.get_full_tick([stock_code])
        completed.append(_COMPLETED_NAMES[7])
        market_data.get_market_data([], [stock_code], "1d", count=1)
        completed.append(_COMPLETED_NAMES[8])
        market_data.get_market_data_ex([], [stock_code], "5m", count=1)
        completed.append(_COMPLETED_NAMES[9])
        market_data.get_instrument_detail(stock_code, complete=False)
        completed.append(_COMPLETED_NAMES[10])
        market_data.get_divid_factors(stock_code)
        completed.append(_COMPLETED_NAMES[11])
        market_data.get_trading_calendar(exchange)
        completed.append(_COMPLETED_NAMES[12])
        market_data.get_trading_dates(exchange, count=1)
        completed.append(_COMPLETED_NAMES[13])
        market_data.get_trading_period(stock_code)
        completed.append(_COMPLETED_NAMES[14])

    def _cleanup() -> Optional[BaseException]:
        # Attempt stop exactly once and NEVER propagate.  Returns None on
        # success, or the raised exception object (ordinary or BaseException)
        # so the caller decides priority (REV-G1T005-001).
        nonlocal stop_attempted
        if stop_attempted:
            return None
        stop_attempted = True
        try:
            trader.stop()
        except BaseException as exc:
            return exc
        return None

    # ``failure`` is set only on an ordinary (non-Base) primary failure; the
    # project exception is raised OUTSIDE the active except block so
    # ``__cause__``/``__context__`` stay clean (no original exception chain).
    failure = None
    try:
        _run_operations()
    except _BASE_EXCEPTIONS:
        # Primary BaseException: attempt cleanup at most once and swallow
        # whatever it raises; the primary BaseException always propagates.
        _cleanup()
        raise
    except BaseException:
        # Ordinary primary failure: record the failing operation name and run
        # cleanup exactly once.  Any cleanup failure (ordinary or BaseException)
        # is folded into the fixed project error and must NOT override or leak.
        failure = _COMPLETED_NAMES[len(completed)]
        cleanup_exc = _cleanup()

    if failure is not None:
        if cleanup_exc is not None:
            raise Gate1ProbeExecutionError(
                f"{failure} failed; cleanup failed"
            ) from None
        raise Gate1ProbeExecutionError(f"{failure} failed") from None

    # All 15 primary operations succeeded; cleanup must still be attempted.
    cleanup_exc = _cleanup()
    if cleanup_exc is not None:
        if isinstance(cleanup_exc, _BASE_EXCEPTIONS):
            # Only with no primary failure does a cleanup BaseException
            # propagate as-is.
            raise cleanup_exc
        raise Gate1ProbeExecutionError("cleanup failed") from None

    return Gate1ReadOnlyProbeSummary(
        completed_operations=tuple(completed),
        cleanup_completed=True,
    )
