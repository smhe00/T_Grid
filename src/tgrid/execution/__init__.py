"""TGrid execution domain (Gate 4, offline dry run).

The Gate 4 execution layer turns strategy decisions into durable OrderIntents
(idempotency, design §18.2), books and releases position/cash reservations
(design §18.3), drives a simulated broker through fills/partials/rejects/
timeouts/cancel failures (design §24–§26), and reconciles the broker orders +
trades + local intents on startup (design §21–§23).  No real QMT order is ever
placed; ``live_trading_allowed=false``.
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
    BrokerDisconnectedError,
    BrokerOrderRejectedError,
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
from tgrid.execution.recovery import (
    BrokerOrderStatus,
    BrokerTrade,
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
    "SimBroker",
    "SimOrder",
    "SimFill",
    "BrokerDisconnectedError",
    "BrokerOrderRejectedError",
    "ExecutionEngine",
    "ExecutionError",
    "ExecutionInputError",
    "OrderSendFailedError",
    "OrderReconciliationError",
    "OrderTimeoutError",
    "CancelFailedError",
    "ReservationConflictError",
    "BrokerOrderStatus",
    "BrokerTrade",
    "reconcile_open_intents",
    "DryRunHarness",
    "DryRunResult",
    "PnLRecord",
    "DryRunError",
]
