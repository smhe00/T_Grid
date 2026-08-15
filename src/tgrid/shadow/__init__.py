"""TGrid shadow mode (Gate 5, design §40).

Shadow mode uses REAL market data and REAL broker queries but SHADOW execution:
the full strategy + risk pipeline generates ``WOULD_BUY`` / ``WOULD_SELL``
records and never sends an order.  The package is fully offline-testable; the
real-QMT wiring is the caller's job (reuse the Gate 1 read-only adapters).
``live_trading_allowed=false`` by construction.
"""

from tgrid.shadow.engine import (
    DailyReport,
    ReconciliationRow,
    ShadowDeltaRow,
    ShadowEngine,
    ShadowError,
    ShadowInputError,
    ShadowOrder,
    SignalRecord,
    build_shadow_reports,
)
from tgrid.shadow.marketdata import (
    BasisBinding,
    fetch_bars,
    resolve_basis,
)
from tgrid.shadow.settlement import (
    SETTLE_T0,
    SETTLE_T1,
    SettlementPolicy,
    SettlementTracker,
    compute_sellable,
)

__all__ = [
    "ShadowEngine",
    "ShadowOrder",
    "SignalRecord",
    "ReconciliationRow",
    "ShadowDeltaRow",
    "DailyReport",
    "ShadowError",
    "ShadowInputError",
    "build_shadow_reports",
    "BasisBinding",
    "fetch_bars",
    "resolve_basis",
    "SETTLE_T0",
    "SETTLE_T1",
    "SettlementPolicy",
    "SettlementTracker",
    "compute_sellable",
]
