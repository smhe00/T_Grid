"""TGrid execution domain (Gate 4, offline dry run + NODEB-001 port).

The Gate 4 execution layer turns strategy decisions into durable OrderIntents
(idempotency, design §18.2), books and releases position/cash reservations
(design §18.3), drives a broker through fills/partials/rejects/timeouts/cancel
failures (design §24–§26), and reconciles the broker orders + trades + local
intents on startup (design §21–§23).  All broker access goes through the narrow
:class:`BrokerPort` (NODEB-001); the deterministic §39 simulation scripts are
owned by :class:`SimulationDriver` and never by the engine.  No real QMT order
is ever placed; ``live_trading_allowed=false``.
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
from tgrid.execution.port import (
    BrokerCancelFailedError,
    BrokerDisconnectedError,
    BrokerError,
    BrokerOrder,
    BrokerOrderRejectedError,
    BrokerPort,
    BrokerTrade,
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
    OrderSendFailedError,
    OrderReconciliationError,
    OrderTimeoutError,
    CancelFailedError,
    ReservationConflictError,
)
from tgrid.execution.simdriver import SimulationDriver, SimulationDriverError
from tgrid.execution.execution_mutex import (
    ConcurrentExecutionError,
    ExecutionMutex,
)
from tgrid.execution.statemachine import (
    InvariantViolation,
    InvalidTransition,
    MachineSnapshot,
    SafetyFacts,
    TGridEvent,
    TGridState,
    TGRID_TRANSITIONS,
    advance,
    assert_invariants,
    initial_snapshot,
    snapshot_from_payload,
    snapshot_to_payload,
    verify_state_machines,
)
from tgrid.execution.execution_journal import (
    ExecutionJournal,
    ExecutionJournalError,
    JournalIntegrityError,
    JournalSchemaError,
    JournalVerification,
    JOURNAL_SCHEMA_VERSION,
)
from tgrid.execution.recovery import (
    BrokerOrderStatus,
    reconcile_open_intents,
)
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
    "BrokerPort",
    "BrokerOrder",
    "BrokerTrade",
    "BrokerError",
    "BrokerDisconnectedError",
    "BrokerOrderRejectedError",
    "BrokerCancelFailedError",
    "SimBroker",
    "SimOrder",
    "SimFill",
    "ExecutionEngine",
    "ExecutionError",
    "ExecutionInputError",
    "OrderSendFailedError",
    "OrderReconciliationError",
    "OrderTimeoutError",
    "CancelFailedError",
    "ReservationConflictError",
    "SimulationDriver",
    "SimulationDriverError",
    "ExecutionMutex",
    "ConcurrentExecutionError",
    "TGridState",
    "TGridEvent",
    "SafetyFacts",
    "MachineSnapshot",
    "TGRID_TRANSITIONS",
    "advance",
    "assert_invariants",
    "initial_snapshot",
    "snapshot_to_payload",
    "snapshot_from_payload",
    "verify_state_machines",
    "InvalidTransition",
    "InvariantViolation",
    "ExecutionJournal",
    "ExecutionJournalError",
    "JournalSchemaError",
    "JournalIntegrityError",
    "JournalVerification",
    "JOURNAL_SCHEMA_VERSION",
    "BrokerOrderStatus",
    "reconcile_open_intents",
    "DryRunHarness",
    "DryRunResult",
    "PnLRecord",
    "DryRunError",
]
