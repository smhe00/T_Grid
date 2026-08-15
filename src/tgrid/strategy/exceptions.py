"""TGrid strategy domain exceptions (Gate 3, offline).

One explicit root for all strategy failures, deriving from the project-wide
:class:`tgrid.risk.exceptions.TGridError` so callers can catch one base type.
Messages are fixed and data-free; no secret, price, quantity, or underlying
exception graph is ever embedded.
"""

from tgrid.risk.exceptions import TGridError


class StrategyError(TGridError):
    """Base class for every offline strategy failure."""


class StrategyInputError(StrategyError):
    """A strategy argument or bar sequence is invalid (fail closed before use)."""


class StrategyDataQualityError(StrategyError):
    """A bar violates the data-quality guard (freshness/missing/duplicate/order/
    price/volume/suspension); new T orders must not be generated from it."""
