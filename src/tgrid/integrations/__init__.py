"""TGrid XtQuant integration boundary (G1-T006 read-only; G5.5 pre-live).

Gate 1 exposes only ``run_gate1_readonly_acceptance``.  Gate 5.5 adds the
pre-live :class:`LiveBrokerAdapter` safety boundary (wraps an INJECTED broker
port and never invokes a real XtQuant order/cancel itself) plus the ONE
concrete :class:`XtQuantBrokerBridge` whose audited ``order_stock`` /
``cancel_order_stock`` call sites are the only permitted real-broker
invocations in the repository (NODEB-001).  Nothing here enables
``live_trading_allowed``.
"""

from tgrid.integrations.live_broker_adapter import (
    CashExposureLimitError,
    ExecutionUnhealthyError,
    ExposureNotReadyError,
    KillSwitchEngagedError,
    LiveBrokerAdapter,
    LiveBrokerError,
    LiveBrokerPolicy,
    LiveTradingDisabledError,
    LiveTradingNotConfirmedError,
    OrderQtyLimitError,
    RuntimeConfirmationTokenError,
    SymbolNotAllowedError,
)
from tgrid.integrations.daily_exposure import (
    DailyExposureError,
    DailyExposureLedger,
    ExposureDateError,
    ExposureValueError,
)
from tgrid.integrations.live_bootstrap import (
    LiveBootstrapError,
    LiveStack,
    build_live_stack,
)
from tgrid.integrations.live_session import (
    LiveSessionAccountError,
    LiveSessionError,
    build_live_session,
)
from tgrid.integrations.exposure_store import SqliteExposureStore
from tgrid.integrations.xtquant_bridge import (
    BrokerAccountStatusEvent,
    BrokerCancelErrorEvent,
    BrokerDisconnectEvent,
    BrokerOrderErrorEvent,
    BrokerOrderEvent,
    BrokerTradeEvent,
    XtQuantBrokerBridge,
    XtQuantCallbackHandler,
)
from tgrid.integrations.qmt_gate1_runtime import (
    QmtGate1RuntimeAccountError,
    QmtGate1RuntimeConfigError,
    QmtGate1RuntimeConnectionError,
    QmtGate1RuntimeError,
    run_gate1_readonly_acceptance,
)

__all__ = [
    "QmtGate1RuntimeError",
    "QmtGate1RuntimeConfigError",
    "QmtGate1RuntimeConnectionError",
    "QmtGate1RuntimeAccountError",
    "run_gate1_readonly_acceptance",
    "LiveBrokerAdapter",
    "LiveBrokerPolicy",
    "LiveBrokerError",
    "LiveTradingDisabledError",
    "LiveTradingNotConfirmedError",
    "RuntimeConfirmationTokenError",
    "SymbolNotAllowedError",
    "OrderQtyLimitError",
    "CashExposureLimitError",
    "KillSwitchEngagedError",
    "ExposureNotReadyError",
    "ExecutionUnhealthyError",
    "DailyExposureLedger",
    "DailyExposureError",
    "ExposureDateError",
    "ExposureValueError",
    "LiveBootstrapError",
    "LiveStack",
    "build_live_stack",
    "LiveSessionError",
    "LiveSessionAccountError",
    "build_live_session",
    "SqliteExposureStore",
    "XtQuantBrokerBridge",
    "XtQuantCallbackHandler",
    "BrokerOrderEvent",
    "BrokerTradeEvent",
    "BrokerDisconnectEvent",
    "BrokerAccountStatusEvent",
    "BrokerOrderErrorEvent",
    "BrokerCancelErrorEvent",
]
