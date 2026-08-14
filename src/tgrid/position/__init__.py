"""TGrid position domain (Gate 2, offline).

Exposes the immutable ``PositionSnapshot``, the highest-priority
``CorePositionGuard`` sell check, the ``SymbolConfig``-bound snapshot factory,
and the offline position reconciliation decision engine.  No Ledger, DB,
OrderIntent, QMT, or trading surface lives here.
"""

from tgrid.position.manager import (
    CorePositionGuard,
    PositionSnapshot,
    snapshot_from_symbol_config,
)
from tgrid.position.reconciliation import (
    RECONCILED,
    REASON_BROKER_POSITION_MISMATCH,
    REASON_CORE_FLOOR_BREACH,
    REASON_MATCH,
    SAFE_MODE,
    PositionReconciliationResult,
    reconcile_position,
)

__all__ = [
    "PositionSnapshot",
    "CorePositionGuard",
    "snapshot_from_symbol_config",
    "reconcile_position",
    "PositionReconciliationResult",
    "RECONCILED",
    "SAFE_MODE",
    "REASON_MATCH",
    "REASON_CORE_FLOOR_BREACH",
    "REASON_BROKER_POSITION_MISMATCH",
]
