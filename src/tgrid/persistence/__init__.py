"""TGrid persistence layer (Gate 0 foundation).

Provides a fail-closed SQLite database lifecycle: explicit-path open,
integrity checking, transactional idempotent migrations, and version
consistency verification.  No trading domain tables exist yet.
"""

from tgrid.persistence.database import (
    BUSY_TIMEOUT_MS,
    connect,
    initialize,
    open_database,
)
from tgrid.persistence.migrations import MAX_SCHEMA_VERSION, MIGRATIONS, Migration

__all__ = [
    "connect",
    "initialize",
    "open_database",
    "BUSY_TIMEOUT_MS",
    "Migration",
    "MIGRATIONS",
    "MAX_SCHEMA_VERSION",
]
