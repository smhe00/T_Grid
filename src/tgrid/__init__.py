"""TGrid — QMT low-frequency T-trading engine.

Gate 0/1 skeleton: configuration loading, explicit risk exception types, a
fail-closed SQLite foundation, and a strictly read-only QMT adapter boundary.
The package has no direct XtQuant dependency and no trading, market-data, or
account-access capability; the read-only adapter only talks to an injected
client object.
"""

from tgrid.adapters import (
    ReadOnlyMarketDataAdapter,
    ReadOnlyQuoteSubscriptionAdapter,
    ReadOnlyTraderAdapter,
    ReadOnlyTraderState,
    QuoteSubscriptionState,
)
from tgrid.config import load_config, parse_config
from tgrid.events import EventQueue, EventQueueState
from tgrid.models import ACCUMULATE_MODE, GlobalConfig, RootConfig, SymbolConfig
from tgrid.persistence import (
    connect as connect_database,
    initialize as initialize_database,
    open_database,
)
from tgrid.reporting import (
    SCHEMA_VERSION,
    configure_jsonl_logger,
    emit,
    shutdown_logger,
)
from tgrid.risk.exceptions import (
    CashReservationConflict,
    ConfigError,
    CoreFloorViolation,
    DatabaseIntegrityError,
    DatabaseOpenError,
    EventQueueConfigError,
    EventQueueError,
    EventQueueFull,
    EventQueueLifecycleError,
    EventQueueWorkerError,
    InsufficientAvailableVolume,
    LoggingConfigError,
    LoggingEmitError,
    LoggingError,
    MarketDataAdapterConfigError,
    MarketDataQueryError,
    MarketDataReadOnlyError,
    MarketDataValidationError,
    MigrationError,
    PersistenceError,
    QmtAdapterConfigError,
    QmtAdapterLifecycleError,
    QmtConnectionError,
    QmtQueryError,
    QmtReadOnlyError,
    QuoteSubscriptionConfigError,
    QuoteSubscriptionError,
    QuoteSubscriptionLifecycleError,
    QuoteSubscriptionStartError,
    QuoteSubscriptionStopError,
    QuoteSubscriptionValidationError,
    RiskError,
    SchemaVersionError,
    SellReservationConflict,
    TGridError,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "ReadOnlyTraderAdapter",
    "ReadOnlyTraderState",
    "load_config",
    "parse_config",
    "EventQueue",
    "EventQueueState",
    "ACCUMULATE_MODE",
    "GlobalConfig",
    "SymbolConfig",
    "RootConfig",
    "connect_database",
    "initialize_database",
    "open_database",
    "SCHEMA_VERSION",
    "configure_jsonl_logger",
    "emit",
    "shutdown_logger",
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
    "LoggingError",
    "LoggingConfigError",
    "LoggingEmitError",
    "EventQueueError",
    "EventQueueConfigError",
    "EventQueueLifecycleError",
    "EventQueueFull",
    "EventQueueWorkerError",
    "QmtReadOnlyError",
    "QmtAdapterConfigError",
    "QmtAdapterLifecycleError",
    "QmtConnectionError",
    "QmtQueryError",
    "MarketDataReadOnlyError",
    "MarketDataAdapterConfigError",
    "MarketDataValidationError",
    "MarketDataQueryError",
    "ReadOnlyMarketDataAdapter",
    "QuoteSubscriptionError",
    "QuoteSubscriptionConfigError",
    "QuoteSubscriptionValidationError",
    "QuoteSubscriptionLifecycleError",
    "QuoteSubscriptionStartError",
    "QuoteSubscriptionStopError",
    "ReadOnlyQuoteSubscriptionAdapter",
    "QuoteSubscriptionState",
]
