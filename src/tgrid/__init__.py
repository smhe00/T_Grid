"""TGrid — QMT low-frequency T-trading engine.

Gate 0 skeleton only: this package provides configuration loading and explicit
risk exception types.  It performs no I/O, has no QMT/XtQuant dependency, and
has no trading, market-data, or account-access capability.
"""

from tgrid.config import load_config, parse_config
from tgrid.models import ACCUMULATE_MODE, GlobalConfig, RootConfig, SymbolConfig
from tgrid.risk.exceptions import (
    CashReservationConflict,
    ConfigError,
    CoreFloorViolation,
    InsufficientAvailableVolume,
    RiskError,
    SellReservationConflict,
    TGridError,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "load_config",
    "parse_config",
    "ACCUMULATE_MODE",
    "GlobalConfig",
    "SymbolConfig",
    "RootConfig",
    "TGridError",
    "ConfigError",
    "RiskError",
    "CoreFloorViolation",
    "InsufficientAvailableVolume",
    "SellReservationConflict",
    "CashReservationConflict",
]
