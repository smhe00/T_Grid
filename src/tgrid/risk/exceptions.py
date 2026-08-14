"""Explicit exception types for TGrid configuration and risk safety.

All TGrid safety-relevant failures raise one of the types below.  Production
code must never rely on Python ``assert`` for safety enforcement (INV-011);
instead it raises these explicit exceptions and callers decide how to fail
closed.
"""


class TGridError(Exception):
    """Base class for every explicit TGrid error."""


class ConfigError(TGridError):
    """Raised when configuration is missing, malformed, or violates a safety bound.

    ``field_path`` locates the offending value (e.g. ``symbols.0700.HK.t_unit``)
    so failures are deterministic and auditable.
    """

    def __init__(self, message: str, field_path: str = "") -> None:
        self.field_path = field_path
        if field_path:
            message = f"{field_path}: {message}"
        super().__init__(message)


class RiskError(TGridError):
    """Base class for runtime risk / safety violations."""


class CoreFloorViolation(RiskError):
    """A sell would reduce the position below the protected ``core_qty`` floor."""


class InsufficientAvailableVolume(RiskError):
    """A sell requests more volume than is currently available to the T module."""


class SellReservationConflict(RiskError):
    """A sell intent conflicts with quantity already reserved for another order."""


class CashReservationConflict(RiskError):
    """A buy intent conflicts with cash already reserved for another order."""


class PersistenceError(TGridError):
    """Base class for database lifecycle failures.

    All persistence failures are fail-closed: they never delete, overwrite, or
    silently "repair" the underlying file.
    """


class DatabaseOpenError(PersistenceError):
    """The database path is unusable or the file could not be opened."""


class DatabaseIntegrityError(PersistenceError):
    """The database file is corrupt or fails its integrity check."""


class SchemaVersionError(PersistenceError):
    """The on-disk schema version is inconsistent with the supported version.

    Covers future ``user_version``, future migration records, gaps, duplicates,
    and ``user_version`` vs ``schema_migrations`` mismatch.  Never auto-downgrade.
    """


class MigrationError(PersistenceError):
    """A schema migration failed and was rolled back."""


class LoggingError(TGridError):
    """Base class for structured logging failures."""


class LoggingConfigError(LoggingError):
    """Logger configuration or file path is invalid."""


class LoggingEmitError(LoggingError):
    """A log event could not be serialized or written."""
