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
from tgrid.persistence.t_lot_writer import (
    TLotNotFoundError,
    TLotStatusConflictError,
    TLotTransitionResult,
    TLotWriteFailedError,
    TLotWriterError,
    TLotWriterInputError,
    transition_t_lot_status,
)
from tgrid.persistence.t_lot_transition_policy import (
    TLotTransitionPlan,
    TLotTransitionPolicyError,
    TLotTransitionRejectedError,
    apply_t_lot_transition,
    resolve_t_lot_transition,
)

__all__ = [
    "connect",
    "initialize",
    "open_database",
    "BUSY_TIMEOUT_MS",
    "Migration",
    "MIGRATIONS",
    "MAX_SCHEMA_VERSION",
    "transition_t_lot_status",
    "TLotTransitionResult",
    "TLotWriterError",
    "TLotWriterInputError",
    "TLotNotFoundError",
    "TLotStatusConflictError",
    "TLotWriteFailedError",
    "resolve_t_lot_transition",
    "apply_t_lot_transition",
    "TLotTransitionPlan",
    "TLotTransitionPolicyError",
    "TLotTransitionRejectedError",
]
