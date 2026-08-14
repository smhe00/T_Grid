"""TGrid position domain (Gate 2, offline).

Exposes the immutable ``PositionSnapshot``, the highest-priority
``CorePositionGuard`` sell check, and the ``SymbolConfig``-bound snapshot factory.
No Ledger, DB, reconciliation, OrderIntent, QMT, or trading surface lives here.
"""

from tgrid.position.manager import (
    CorePositionGuard,
    PositionSnapshot,
    snapshot_from_symbol_config,
)

__all__ = [
    "PositionSnapshot",
    "CorePositionGuard",
    "snapshot_from_symbol_config",
]
