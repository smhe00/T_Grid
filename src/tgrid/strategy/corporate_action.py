"""Corporate-action price basis and factor application (Gate 3, offline).

Design §7.1 requires an explicit distinction between:

* RAW_PRICE       — the real traded price used for live orders and quotes;
* ADJUSTED_PRICE  — the unified, history-continuous price used for indicators.

A :class:`CorporateActionFactor` describes one quantity-changing corporate
action (split, bonus, rights, etc.): ``price_factor`` is the multiplicative
factor applied to *pre-action* prices so that historical indicators stay
continuous with post-action prices (e.g. a 1:2 split halves pre-action prices),
and ``qty_factor`` is the factor applied to pre-action share quantities (e.g.
2.0 for a 1:2 split).  :func:`adjust_historical_prices` produces a new,
immutable bar sequence on a single ADJUSTED basis; it never mutates the input.
Indicators are only computed on one basis at a time (no mixing, INV / §7.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from tgrid.strategy.bars import Bar
from tgrid.strategy.exceptions import StrategyInputError


class _PriceBasis:
    """Fixed price-basis constants (design §7.1)."""

    RAW = "RAW"
    ADJUSTED = "ADJUSTED"


PriceBasis = _PriceBasis()


@dataclass(frozen=True)
class CorporateActionFactor:
    """One quantity-changing corporate action and its adjustment factors.

    ``effective_time`` is the exchange-local ISO time at which the action takes
    effect; bars strictly *before* it are adjusted.  ``price_factor`` (> 0) is
    applied multiplicatively to pre-action prices, ``qty_factor`` (> 0) to
    pre-action quantities.  Both must be finite and positive.
    """

    action_type: str
    effective_time: str
    price_factor: float
    qty_factor: float

    def __post_init__(self) -> None:
        if type(self.action_type) is not str or self.action_type == "":
            raise StrategyInputError("action_type must be a non-empty string")
        if type(self.effective_time) is not str or self.effective_time == "":
            raise StrategyInputError("effective_time must be a non-empty string")
        for name in ("price_factor", "qty_factor"):
            value = getattr(self, name)
            if type(value) not in (int, float) or isinstance(value, bool):
                raise StrategyInputError(f"{name} must be a number")
            value = float(value)
            if value != value or value in (float("inf"), float("-inf")) or value <= 0:
                raise StrategyInputError(f"{name} must be finite and > 0")
            object.__setattr__(self, name, value)


def adjust_historical_prices(
    bars: Sequence,
    factor: object,
) -> tuple:
    """Return a new ADJUSTED-basis bar tuple for bars before ``effective_time``.

    Bars at or after ``effective_time`` are copied unchanged onto the ADJUSTED
    basis; earlier bars have price/volume scaled by the factor.  The input is
    never mutated and the returned tuple shares no mutable state with it.
    Fails closed on a non-Bar element, a negative resulting price, or a missing
    factor type.
    """
    if factor is None or not isinstance(factor, CorporateActionFactor):
        raise StrategyInputError("factor must be a CorporateActionFactor")
    if bars is None or isinstance(bars, (str, bytes)) or not hasattr(bars, "__len__"):
        raise StrategyInputError("bars must be a sequence of Bar objects")
    price_factor = float(factor.price_factor)
    qty_factor = float(factor.qty_factor)
    adjusted = []
    for bar in bars:
        if not isinstance(bar, Bar):
            raise StrategyInputError("bars must contain only Bar objects")
        if bar.time < factor.effective_time:
            new_price = float(bar.close) * price_factor
            if new_price <= 0 or new_price != new_price:
                raise StrategyInputError("adjusted price must be finite and positive")
            if type(bar.volume) is not int or bar.volume < 0:
                raise StrategyInputError("bar volume must be a non-negative int")
            adjusted.append(
                Bar(
                    symbol=bar.symbol,
                    time=bar.time,
                    open=float(bar.open) * price_factor,
                    high=float(bar.high) * price_factor,
                    low=float(bar.low) * price_factor,
                    close=new_price,
                    volume=int(round(bar.volume * qty_factor)),
                    kind=bar.kind,
                    price_basis=PriceBasis.ADJUSTED,
                )
            )
        else:
            adjusted.append(
                Bar(
                    symbol=bar.symbol,
                    time=bar.time,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    kind=bar.kind,
                    price_basis=PriceBasis.ADJUSTED,
                )
            )
    return tuple(adjusted)
