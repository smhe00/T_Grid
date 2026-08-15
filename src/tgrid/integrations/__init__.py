"""TGrid XtQuant integration boundary (G1-T006 read-only; G5.5 pre-live).

Gate 1 exposes only ``run_gate1_readonly_acceptance``.  Gate 5.5 adds the
pre-live :class:`LiveBrokerAdapter` safety boundary: it wraps an INJECTED
order/cancel surface and never invokes a real XtQuant order/cancel itself.
Nothing here enables ``live_trading_allowed``.
"""

from tgrid.integrations.live_broker_adapter import (
    CallbackMutationForbiddenError,
    CashExposureLimitError,
    KillSwitchEngagedError,
    LiveBrokerAdapter,
    LiveBrokerError,
    LiveBrokerPolicy,
    LiveTradingDisabledError,
    LiveTradingNotConfirmedError,
    OrderQtyLimitError,
    SymbolNotAllowedError,
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
    "SymbolNotAllowedError",
    "OrderQtyLimitError",
    "CashExposureLimitError",
    "KillSwitchEngagedError",
    "CallbackMutationForbiddenError",
]
