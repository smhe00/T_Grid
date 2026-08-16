"""Production-shaped qmt-execution-core construction (migration Phase C).

Routes TGrid production-shaped simulation/shadow construction onto the
independently audited public execution core.  ``MiniQmtRuntime`` owns the QMT
transport, broker adapter, session, journal/mutex and live gate; TGrid owns the
SQLite business ledger (OrderIntent + Reservation + daily exposure) which is
persisted through the public sidecar seam BEFORE any broker side effect.

No TGrid code calls raw ``order_stock`` / ``cancel_order_stock`` here — the
public core is the ONLY QMT side-effect authority (capability scan gate).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from qmt_execution_core.miniqmt.runtime import (
    MiniQmtRuntime,
    MiniQmtRuntimeConfig,
)

from tgrid.execution.store import ExecutionStore
from tgrid.integrations.daily_exposure import DailyExposureLedger
from tgrid.integrations.live_broker_adapter import LiveBrokerPolicy
from tgrid.integrations.qec_adapter import (
    TGridEvidenceSource,
    TGridExecutionGuard,
    TGridSidecar,
)


class QecRuntimeError(RuntimeError):
    """Base class for qec runtime construction failures."""


def build_qec_runtime(
    *,
    environment: str,
    qmt_path: object,
    binding_path: object,
    journal_path: object,
    lock_path: object,
    strategy_name: str,
    trade_date: str,
    store: ExecutionStore,
    exposure: DailyExposureLedger,
    policy: LiveBrokerPolicy,
    now: Callable[[], str],
    evidence: TGridEvidenceSource | None = None,
    live_trading_enabled: bool = False,
    trader_factory: object | None = None,
    stock_account_factory: object | None = None,
    xtconstant: object | None = None,
    callback_base: object | None = None,
    auto_open: bool = True,
) -> MiniQmtRuntime:
    """Assemble a public-core runtime driven through the TGrid guard + sidecar.

    ``environment`` must be exactly ``"simulation"`` or ``"live"``.  The
    ``TGridExecutionGuard`` consumes the REQUIRED :class:`TGridEvidenceSource`
    (iteration 14, P1-1): every evidence supplier comes from the caller —
    there are NO permissive/self-certified defaults in the production builder,
    so construction fails closed when evidence sources are absent.  The
    ``TGridSidecar`` persists the TGrid SQLite OrderIntent + Reservation +
    daily exposure through ``before_broker_submit`` / ``before_broker_cancel``.

    ``trader_factory`` / ``stock_account_factory`` / ``xtconstant`` /
    ``callback_base`` are test-only injections (fake XtQuant); production uses
    the public core's real lazy xtquant imports.
    """
    if environment not in ("simulation", "live"):
        raise QecRuntimeError("environment must be exactly 'simulation' or 'live'")
    if not isinstance(store, ExecutionStore):
        raise QecRuntimeError("store must be an ExecutionStore")
    if not isinstance(exposure, DailyExposureLedger):
        raise QecRuntimeError("exposure must be a DailyExposureLedger")
    if not isinstance(policy, LiveBrokerPolicy):
        raise QecRuntimeError("policy must be a LiveBrokerPolicy")
    if type(strategy_name) is not str or not strategy_name:
        raise QecRuntimeError("strategy_name must be a non-empty string")
    if evidence is None or not isinstance(evidence, TGridEvidenceSource):
        raise QecRuntimeError(
            "evidence must be a TGridEvidenceSource with live suppliers; "
            "refusing to build a production runtime with self-certified or "
            "absent evidence"
        )

    guard = TGridExecutionGuard(
        policy=policy,
        environment_verified=evidence.environment_verified,
        account_verified=evidence.account_verified,
        broker_snapshot_verified=evidence.broker_snapshot_verified,
        position_verified=evidence.position_verified,
        cash_verified=evidence.cash_verified,
        quote_verified=evidence.quote_verified,
        kill_switch_active=evidence.kill_switch_active,
        exposure_ready=evidence.exposure_ready,
        exposure_used=evidence.exposure_used,
    )
    sidecar = TGridSidecar(
        store=store, exposure=exposure, strategy_name=strategy_name, now=now,
    )
    config = MiniQmtRuntimeConfig(
        environment=environment,
        qmt_path=Path(qmt_path),
        binding_path=Path(binding_path),
        journal_path=Path(journal_path),
        lock_path=Path(lock_path),
        strategy_name=strategy_name,
        live_trading_enabled=live_trading_enabled,
    )
    runtime = MiniQmtRuntime.connect(
        config,
        guard=guard,
        trader_factory=trader_factory,
        stock_account_factory=stock_account_factory,
        xtconstant=xtconstant,
        callback_base=callback_base,
        auto_open=auto_open,
        before_broker_submit=sidecar.before_broker_submit,
        before_broker_cancel=sidecar.before_broker_cancel,
    )
    return runtime
