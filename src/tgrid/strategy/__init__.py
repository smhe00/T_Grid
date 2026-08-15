"""TGrid strategy domain (Gate 3, offline).

Pure, fail-closed strategy mathematics that never touches QMT, a broker, an
account, or a database: indicators (VWAP20 / EMA20 / ATR14), the adaptive
geometric grid, the RAW vs ADJUSTED price basis and corporate-action factor
application, the data-quality guard, volatility/event halts, and the
ACCUMULATE engine that turns 5-minute bars into T order decisions.

Everything here is deterministic and unit-testable with synthetic data
(design §38).  No order is ever placed; decisions are data-only and the caller
(execution layer, Gate 4+) decides whether/how to act on them.
"""

from tgrid.strategy.engine import (
    AccumulateStrategy,
    BarDecision,
    DecisionKind,
)
from tgrid.strategy.indicators import atr14, atr_pct, ema20, vwap20
from tgrid.strategy.corporate_action import (
    CorporateActionFactor,
    PriceBasis,
    adjust_historical_prices,
)
from tgrid.strategy.grid import buy_level, exit_target_price, grid_pct
from tgrid.strategy.quality import (
    BarQualityIssue,
    DataQualityGuard,
    check_bar_quality,
)
from tgrid.strategy.halts import (
    EventBlockRule,
    event_blocked,
    volatility_halt,
)
from tgrid.strategy.bars import Bar, BarKind, SessionWindow

__all__ = [
    "Bar",
    "BarKind",
    "SessionWindow",
    "PriceBasis",
    "CorporateActionFactor",
    "adjust_historical_prices",
    "vwap20",
    "ema20",
    "atr14",
    "atr_pct",
    "grid_pct",
    "buy_level",
    "exit_target_price",
    "BarQualityIssue",
    "DataQualityGuard",
    "check_bar_quality",
    "EventBlockRule",
    "event_blocked",
    "volatility_halt",
    "AccumulateStrategy",
    "BarDecision",
    "DecisionKind",
]
