"""TGrid — QMT low-frequency T-trading engine.

Gate 0 skeleton only: this package provides configuration loading, explicit
risk exception types, and a fail-closed SQLite foundation.  It has no
QMT/XtQuant dependency and no trading, market-data, or account-access
capability.
"""

from tgrid.config import load_config, parse_config
from tgrid.models import ACCUMULATE_MODE, GlobalConfig, RootConfig, SymbolConfig
from tgrid.persistence import (
    connect as connect_database,
    initialize as initialize_database,
    open_database,
)
from tgrid.risk.exceptions import (
    CashReservationConflict,
    ConfigError,
    CoreFloorViolation,
    DatabaseIntegrityError,
    DatabaseOpenError,
    InsufficientAvailableVolume,
    MigrationError,
    PersistenceError,
    RiskError,
    SchemaVersionError,
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
    "connect_database",
    "initialize_database",
    "open_database",
    "TGridError",
    "ConfigError",
    "RiskError",
    "CoreFloorViolation",
    "InsufficientAvailableVolume",
    "SellReservationConflict",
    "CashReservationConflict",
    "PersistenceError",
    "DatabaseOpenError",
    "DatabaseIntegrityError",
    "SchemaVersionError",
    "MigrationError",
]
