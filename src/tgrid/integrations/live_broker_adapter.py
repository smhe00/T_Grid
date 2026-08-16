"""TGrid pre-live risk policy + exception vocabulary (migration Phase D).

The old ``LiveBrokerAdapter`` safety-boundary class is gone: its risk gates
are re-expressed through :class:`~tgrid.integrations.qec_adapter.TGridExecutionGuard`
over the public-core session (see ``qec_runtime.build_qec_runtime``), and the
broker side effects live only in qmt-execution-core.  This module retains the
immutable :class:`LiveBrokerPolicy` (allowlist / qty / cash caps consumed by
the TGrid guard) and the exception vocabulary used by TGrid callers/tests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from tgrid.risk.exceptions import TGridError


class LiveBrokerError(TGridError):
    """Base class for live broker policy / gate failures."""


class LiveTradingDisabledError(LiveBrokerError):
    """live_trading is not enabled (config-level enable missing)."""


class LiveTradingNotConfirmedError(LiveBrokerError):
    """The explicit runtime confirmation (token-gated) is missing."""


class RuntimeConfirmationTokenError(LiveBrokerError):
    """The runtime confirmation token is missing or mismatched."""


class SymbolNotAllowedError(LiveBrokerError):
    """The symbol is not on the trusted allowlist."""


class OrderQtyLimitError(LiveBrokerError):
    """The order qty exceeds the per-order limit."""


class CashExposureLimitError(LiveBrokerError):
    """The order notional or daily exposure would exceed the limit."""


class KillSwitchEngagedError(LiveBrokerError):
    """The kill switch is engaged; no NEW orders."""


class ExposureNotReadyError(LiveBrokerError):
    """Daily exposure has not been reconstructed at startup."""


class ExecutionUnhealthyError(LiveBrokerError):
    """Broker execution health is degraded (e.g. event queue failed)."""


@dataclass(frozen=True)
class LiveBrokerPolicy:
    """Immutable pre-live safety policy (NODE-B items 2-6)."""

    allowlist: frozenset
    max_order_qty: int
    max_cash_per_order: float
    max_cash_per_day: float

    def __post_init__(self) -> None:
        if not isinstance(self.allowlist, frozenset) or not self.allowlist:
            raise LiveBrokerError("allowlist must be a non-empty frozenset of symbols")
        for symbol in self.allowlist:
            if type(symbol) is not str or symbol == "":
                raise LiveBrokerError("allowlist entries must be non-empty strings")
        if type(self.max_order_qty) is not int or self.max_order_qty <= 0:
            raise LiveBrokerError("max_order_qty must be a positive plain int")
        # NODEB-006: finite positive plain numeric values only (NaN/Inf rejected).
        for name, value in (
            ("max_cash_per_order", self.max_cash_per_order),
            ("max_cash_per_day", self.max_cash_per_day),
        ):
            if type(value) not in (int, float) or isinstance(value, bool):
                raise LiveBrokerError(f"{name} must be a plain number")
            if not math.isfinite(float(value)) or value <= 0:
                raise LiveBrokerError(f"{name} must be a finite positive number")
