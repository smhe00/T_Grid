"""Immutable, typed configuration models for TGrid.

These dataclasses only *describe* the validated configuration shape.  All
bounds and type checks live in :mod:`tgrid.config`; the models themselves hold
no validation logic and perform no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

# V1 supports exactly one trading mode.  Any other value (including NEUTRAL and
# DISTRIBUTE, which are reserved for V2) must be rejected at load time.
ACCUMULATE_MODE = "ACCUMULATE"

# Design 8 / 20: V1 is driven exclusively by 5-minute bars, never ticks.
BAR_PERIOD_5M = "5m"

# Design 9: the daily anchor is VWAP20, falling back to EMA20 when VWAP data
# is insufficient.  No other anchor is defined for V1.
ANCHOR_VWAP20 = "VWAP20"
ANCHOR_EMA20 = "EMA20"
ALLOWED_ANCHORS = frozenset({ANCHOR_VWAP20, ANCHOR_EMA20})


@dataclass(frozen=True)
class GlobalConfig:
    """Process-wide configuration.

    ``live_trading`` defaults to ``False`` and, in Gate 0, there is no code path
    that could flip it on; it exists only so the invariant INV-009 is expressed
    in the data model.
    """

    live_trading: bool
    database: str
    log_dir: str
    bar_period: str
    order_timeout_seconds: int
    skip_open_minutes: int
    skip_close_minutes: int
    volatility_halt_atr: float
    minimum_cash_buffer: float


@dataclass(frozen=True)
class SymbolConfig:
    """Per-symbol configuration.

    ``core_qty`` is the protected floor; ``target_qty`` the strategic ceiling.
    ``t_unit`` must be a positive multiple of ``lot_size`` and ``price_tick`` is
    the exchange minimum price increment (INV / design 18.1).
    """

    enabled: bool
    mode: str
    core_qty: int
    target_qty: int
    t_unit: int
    lot_size: int
    price_tick: float
    max_t_lots: int
    max_t_capital: float
    anchor: str
    atr_period: int
    atr_k: float
    min_grid: float
    max_grid: float
    exit_multiple: float


@dataclass(frozen=True)
class RootConfig:
    """The validated root of a configuration file.

    ``symbols`` is re-wrapped in a :class:`types.MappingProxyType` on
    construction so that, together with the frozen dataclass, the validated
    configuration is read-only at runtime: callers cannot ``clear``/``pop``/
    ``update``/assign the symbol map after validation.
    """

    global_config: GlobalConfig
    symbols: Mapping[str, SymbolConfig]

    def __post_init__(self) -> None:
        # Copy first so the proxy owns a private dict; the caller's original
        # mapping (if any) cannot later mutate through the same object.
        object.__setattr__(self, "symbols", MappingProxyType(dict(self.symbols)))
