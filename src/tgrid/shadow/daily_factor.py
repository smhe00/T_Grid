"""Trusted per-day ADJUSTED->RAW factor registry (Gate 5, NODEA-R3-001).

The real-QMT runner must never default the same-day adjustment factor to 1.0:
on/around a corporate action a stale or default factor makes ADJUSTED
indicator values numerically incomparable with RAW trading prices.

This registry is the explicit trusted source of same-day factors.  It is
keyed by ``(symbol, trade_date)`` with NO missing-day fallback: a day without
an entry fails closed, so the strategy cannot silently run on a guessed
factor.  Factors may be loaded from an XtQuant dividend-factor adapter or from
an explicit local map; provenance is recorded per binding so evidence can name
the source.
"""

from __future__ import annotations

from tgrid.strategy.exceptions import StrategyInputError

# Provenance tags: where the factor came from.
PROVENANCE_XTQUANT = "XTQUANT_DIVIDEND_FACTORS"
PROVENANCE_LOCAL_MAP = "TRUSTED_LOCAL_FACTOR_MAP"


class DailyFactorRegistry:
    """Immutable per-(symbol, trade_date) ADJUSTED->RAW factor map.

    ``factors`` maps ``(symbol, trade_date)`` -> float factor such that
    ``RAW = ADJUSTED * factor`` for that day.  Construction validates every
    entry (finite positive factor, non-empty symbol/date); lookups fail closed
    on any missing key — there is no 1.0 default.
    """

    def __init__(self, factors: object, *, provenance: str) -> None:
        if type(provenance) is not str or provenance not in (
            PROVENANCE_XTQUANT, PROVENANCE_LOCAL_MAP,
        ):
            raise StrategyInputError(
                f"unknown provenance {provenance!r}"
            )
        if factors is None or not hasattr(factors, "items"):
            raise StrategyInputError("factors must be a mapping")
        cleaned = {}
        for key, value in factors.items():
            if not isinstance(key, tuple) or len(key) != 2:
                raise StrategyInputError("factor keys must be (symbol, trade_date)")
            symbol, trade_date = key
            if type(symbol) is not str or symbol == "":
                raise StrategyInputError("factor symbol must be a non-empty string")
            if type(trade_date) is not str or trade_date == "":
                raise StrategyInputError("factor trade_date must be a non-empty string")
            if type(value) not in (int, float) or isinstance(value, bool):
                raise StrategyInputError("factor must be a number")
            factor = float(value)
            if factor != factor or factor in (float("inf"), float("-inf")) or factor <= 0:
                raise StrategyInputError("factor must be finite and > 0")
            cleaned[(symbol, trade_date)] = factor
        self._factors = cleaned
        self._provenance = provenance

    @property
    def provenance(self) -> str:
        return self._provenance

    def factor_for(self, symbol: object, trade_date: object) -> float:
        """Return the trusted same-day factor; missing key fails closed."""
        if type(symbol) is not str or type(trade_date) is not str:
            raise StrategyInputError("symbol and trade_date must be strings")
        try:
            return self._factors[(symbol, trade_date)]
        except KeyError:
            raise StrategyInputError(
                f"no trusted ADJUSTED->RAW factor for {symbol} on {trade_date}; "
                "refusing to guess a factor"
            ) from None

    def bindings(self) -> tuple:
        """Immutable view of all (symbol, trade_date, factor) bindings."""
        return tuple(
            (symbol, trade_date, factor)
            for (symbol, trade_date), factor in sorted(self._factors.items())
        )

    def sanitized_summary(self) -> dict:
        """Data-only provenance summary (no factor values, AUD-R1-005).

        Reports the provenance and the number of per-day bindings, not the
        actual factor magnitudes, so evidence can cite the source without
        leaking corporate-action economics.
        """
        return {
            "provenance": self._provenance,
            "binding_count": len(self._factors),
            "dates": sorted({trade_date for _, trade_date in self._factors}),
            "symbols": sorted({symbol for symbol, _ in self._factors}),
        }
