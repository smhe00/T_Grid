"""Explicit ADJUSTED -> RAW trading-price domain transform (Gate 5, NODEA-001).

The strategy freezes ``DailyBasis`` (anchor / previous_close / ATR as a price)
from ADJUSTED daily indicator history, but 5m ``bar.close`` and live execution
prices are RAW.  Comparing those two domains directly is dimensionally wrong
around any corporate action / ex-date.

This module provides the one auditable transform that maps an ADJUSTED-domain
price to the RAW trading domain for the active trading day:

    RAW = ADJUSTED * factor

where ``factor`` is the explicit, externally supplied same-day adjustment
factor (e.g. from XtQuant dividend factors or a trusted configuration).  The
transform is a pure function: it never guesses a factor, and it fails closed
if the factor is missing, non-positive, or non-finite.  Dimensionless values
(ATR%, grid%) must never be transformed — the caller keeps them dimensionless.

All values that enter a price comparison (anchor, previous_close, absolute
ATR used as a price, buy levels, exit targets) are converted to the RAW domain
exactly once at ``begin_day``; afterwards every comparison is RAW vs RAW.
"""

from __future__ import annotations

from tgrid.strategy.exceptions import StrategyInputError

# The two supported price bases (kept here to avoid a circular import with
# corporate_action which also defines PriceBasis-like constants).
_RAW = "RAW"
_ADJUSTED = "ADJUSTED"


def resolve_same_day_factor(
    *,
    dividend_type: object,
    adjusted_to_raw_factor: object,
) -> float:
    """Return the validated same-day ``ADJUSTED -> RAW`` multiplier.

    ``adjusted_to_raw_factor`` is the explicit factor such that
    ``RAW_price = ADJUSTED_price * factor`` for the active trading day.  It
    must be supplied by a trusted source (real XtQuant dividend factors or
    explicit configuration); the engine never derives it from prices.

    Fails closed when the factor is not a finite positive number, or when the
    requested ``dividend_type`` is not an ADJUSTED-acquisition mode (a RAW
    acquisition has no adjustment and must not pretend to need one).
    """
    if type(dividend_type) is not str or dividend_type not in ("front", "front_ratio"):
        raise StrategyInputError(
            "same-day factor is only defined for an ADJUSTED acquisition mode"
        )
    if type(adjusted_to_raw_factor) not in (int, float) or isinstance(
        adjusted_to_raw_factor, bool
    ):
        raise StrategyInputError("adjusted_to_raw_factor must be a number")
    factor = float(adjusted_to_raw_factor)
    if factor != factor or factor in (float("inf"), float("-inf")) or factor <= 0:
        raise StrategyInputError(
            "adjusted_to_raw_factor must be finite and > 0"
        )
    return factor


def to_raw_domain(adjusted_price: object, factor: object) -> float:
    """Map one ADJUSTED-domain price to the RAW trading domain.

    ``adjusted_price`` must be a finite positive number (a real price);
    ``factor`` the validated same-day factor (RAW = ADJUSTED * factor).
    """
    if type(adjusted_price) not in (int, float) or isinstance(adjusted_price, bool):
        raise StrategyInputError("adjusted_price must be a number")
    price = float(adjusted_price)
    if price != price or price in (float("inf"), float("-inf")) or price <= 0:
        raise StrategyInputError("adjusted_price must be finite and > 0")
    factor_value = resolve_same_day_factor(
        dividend_type="front", adjusted_to_raw_factor=factor
    )
    raw = price * factor_value
    if raw != raw or raw in (float("inf"), float("-inf")) or raw <= 0:
        raise StrategyInputError("transformed RAW price must be finite and > 0")
    return raw


def to_raw_domain_sequence(adjusted_prices, factor: object) -> tuple:
    """Map every ADJUSTED-domain price in a sequence to the RAW domain."""
    if adjusted_prices is None or isinstance(adjusted_prices, (str, bytes)):
        raise StrategyInputError("adjusted_prices must be a sequence of numbers")
    return tuple(to_raw_domain(p, factor) for p in adjusted_prices)


def to_raw_domain_factor(adjusted_to_raw_factor: object) -> float:
    """Validate and return the same-day ADJUSTED->RAW factor (NODEA-001).

    Thin alias of :func:`resolve_same_day_factor` used by the strategy engine
    when the caller already knows the daily acquisition was ADJUSTED.  A
    missing or invalid factor fails closed.
    """
    return resolve_same_day_factor(
        dividend_type="front", adjusted_to_raw_factor=adjusted_to_raw_factor
    )
