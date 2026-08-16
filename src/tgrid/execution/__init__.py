"""TGrid execution domain — TGrid-specific orchestration over the public core.

Migration Phase D: the generic broker lifecycle / state machine / journal /
mutex / recovery now live in ``qmt-execution-core`` (see the module mapping in
``work/gates/QMT_EXECUTION_CORE/TGRID_MIGRATION_EVIDENCE_20260816.md``).
TGrid keeps its business ledger (``store.py`` / ``models.py``), the
TGrid-specific :class:`ExecutionEngine` orchestration, and the offline
simulation fakes (``SimBroker`` / ``SimulationDriver`` / ``DryRunHarness``).

No real QMT order is ever placed; ``live_trading_allowed=false``.
"""

from tgrid.execution.models import (
    BUY,
    SELL,
    OrderSide,
    OrderStatus,
    OrderStatusError,
    OrderIntent,
    OrderIntentError,
    Reservation,
    ReservationError,
)
from tgrid.execution.simbroker import (
    SimBroker,
    SimFill,
    SimOrder,
)
from tgrid.execution.executor import (
    ExecutionEngine,
    ExecutionError,
    ExecutionInputError,
    ExecutionResult,
    OrderSendFailedError,
    OrderReconciliationError,
    OrderTimeoutError,
    CancelFailedError,
    ReservationConflictError,
)
from tgrid.execution.simdriver import SimulationDriver, SimulationDriverError
from tgrid.execution.dryrun import (
    DryRunHarness,
    DryRunResult,
    PnLRecord,
    DryRunError,
)

__all__ = [
    "OrderSide",
    "OrderStatus",
    "OrderStatusError",
    "BUY",
    "SELL",
    "OrderIntent",
    "OrderIntentError",
    "Reservation",
    "ReservationError",
    "SimBroker",
    "SimOrder",
    "SimFill",
    "ExecutionEngine",
    "ExecutionError",
    "ExecutionInputError",
    "ExecutionResult",
    "OrderSendFailedError",
    "OrderReconciliationError",
    "OrderTimeoutError",
    "CancelFailedError",
    "ReservationConflictError",
    "SimulationDriver",
    "SimulationDriverError",
    "DryRunHarness",
    "DryRunResult",
    "PnLRecord",
    "DryRunError",
]
