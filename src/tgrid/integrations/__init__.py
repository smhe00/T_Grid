"""TGrid integration boundary (Gate 1 read-only; qmt-execution-core pre-live).

Migration Phase D: the raw XtQuant bridge and the old live bootstrap/session
factory are gone — the broker side effects live only in qmt-execution-core
and TGrid wires the production-shaped runtime through
:func:`~tgrid.integrations.qec_runtime.build_qec_runtime`.  This module
retains the risk policy/exceptions, the durable daily-exposure ledger, the
exposure store, and the Gate-1 read-only probe surface.  Nothing here enables
``live_trading_allowed``.
"""

from tgrid.integrations.live_broker_adapter import (
    CashExposureLimitError,
    ExecutionUnhealthyError,
    ExposureNotReadyError,
    KillSwitchEngagedError,
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
from tgrid.integrations.exposure_store import SqliteExposureStore
from tgrid.integrations.qec_adapter import (
    TGridEvidenceSource,
    TGridExecutionGuard,
    TGridSidecar,
    apply_snapshot,
    make_execution_request,
    snapshot_status_to_tgrid,
)
from tgrid.integrations.qec_runtime import (
    QecRuntimeError,
    build_qec_runtime,
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
    "SqliteExposureStore",
    "TGridEvidenceSource",
    "TGridExecutionGuard",
    "TGridSidecar",
    "apply_snapshot",
    "make_execution_request",
    "snapshot_status_to_tgrid",
    "QecRuntimeError",
    "build_qec_runtime",
]
