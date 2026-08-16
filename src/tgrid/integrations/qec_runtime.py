"""Production-shaped qmt-execution-core 0.4 construction (migration Iter 16).

Routes TGrid production-shaped simulation/shadow construction onto the
independently audited public execution core.  ``MiniQmtRuntime`` owns the QMT
transport, broker adapter, session, journal/mutex, account-level coordination
and live gate; TGrid owns the SQLite business ledger (OrderIntent +
Reservation + daily exposure) which is persisted through the public sidecar
seam AFTER Core 0.4 shared coordination COMMIT and BEFORE any broker side
effect:

    Core durable intent -> Core symbol/cash coordination COMMIT
    -> TGrid business sidecar COMMIT -> broker submit

Iteration 16 (Core 0.4 / acf20d9): the production composition defaults to
``runtime_lock_mode="shared"`` with an EXPLICIT canonical account-level
``coordination_path`` (common to every strategy process sharing the broker
account) and an EXPLICIT conservative ``CashRequirementEstimator``.  Shared
mode without either is refused at build time (fail closed); the builder never
defaults coordination to a strategy-specific path.  A journal bound to a
different qmt-execution-core source/spec build is REJECTED (never silently
migrated); the documented cutover is: reconcile the old execution under the
old deployment, archive the old 0.3.1 journal, configure a new 0.4 journal
path, then start the 0.4 runtime.

No TGrid code calls raw ``order_stock`` / ``cancel_order_stock`` here — the
public core is the ONLY QMT side-effect authority (capability scan gate).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from qmt_execution_core.coordination import ConservativeCashRequirementEstimator
from qmt_execution_core.journal import JournalIntegrityError
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


@dataclass
class TGridQecStack:
    """Production composition: ONE execution authority (Iteration 15, P1-1).

    ``runtime`` (MiniQmtRuntime) OWNS the ExecutionSession, journal/mutex,
    broker adapter, guard + sidecar hooks and transport teardown.  ``engine``
    is TGrid orchestration bound to ``runtime.session`` — the SAME session
    instance — so exactly one execution-session authority drives the QMT
    transport.  ``close()`` releases the runtime (and therefore the session)
    exactly once; the engine's close is a no-op for the injected session.
    """

    runtime: MiniQmtRuntime
    engine: ExecutionEngine

    def close(self) -> None:
        self.engine.close()  # forgets the injected session (no second close)
        self.runtime.close()  # owns session/mutex/transport teardown


def build_tgrid_qec_stack(
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
    evidence: TGridEvidenceSource,
    live_trading_enabled: bool = False,
    trader_factory: object | None = None,
    stock_account_factory: object | None = None,
    xtconstant: object | None = None,
    callback_base: object | None = None,
    auto_open: bool = True,
    runtime_lock_mode: str = "shared",
    coordination_path: object | None = None,
    cash_estimator: object | None = None,
    coordinator: object | None = None,
) -> TGridQecStack:
    """Assemble the production composition: runtime + engine over the SAME session.

    The runtime owns the single ExecutionSession (with the TGrid guard +
    sidecar hooks wired once); the TGrid :class:`ExecutionEngine` binds to
    ``runtime.session`` instead of creating a second execution authority.

    Core 0.4 (Iteration 16): ``runtime_lock_mode`` defaults to ``"shared"``
    (multi-strategy multi-process capable).  Shared mode requires an explicit
    account-level ``coordination_path`` (or injected ``coordinator`` for
    tests) and an explicit conservative ``cash_estimator`` — build fails
    closed otherwise.  ``engine.session is runtime.session`` remains the
    one-authority identity invariant.
    """
    runtime = build_qec_runtime(
        environment=environment,
        qmt_path=qmt_path,
        binding_path=binding_path,
        journal_path=journal_path,
        lock_path=lock_path,
        strategy_name=strategy_name,
        trade_date=trade_date,
        store=store,
        exposure=exposure,
        policy=policy,
        now=now,
        evidence=evidence,
        live_trading_enabled=live_trading_enabled,
        trader_factory=trader_factory,
        stock_account_factory=stock_account_factory,
        xtconstant=xtconstant,
        callback_base=callback_base,
        auto_open=auto_open,
        runtime_lock_mode=runtime_lock_mode,
        coordination_path=coordination_path,
        cash_estimator=cash_estimator,
        coordinator=coordinator,
    )
    # Lazy import: executor -> qec_adapter -> tgrid.integrations would cycle
    # through this module at import time (Iteration 15 P1-1 composition).
    from tgrid.execution.executor import ExecutionEngine

    engine = ExecutionEngine(
        store, session=runtime.session, strategy_name=strategy_name,
    )
    return TGridQecStack(runtime=runtime, engine=engine)


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
    runtime_lock_mode: str = "shared",
    coordination_path: object | None = None,
    cash_estimator: object | None = None,
    coordinator: object | None = None,
) -> MiniQmtRuntime:
    """Assemble a public-core runtime driven through the TGrid guard + sidecar.

    ``environment`` must be exactly ``"simulation"`` or ``"live"``.  The
    ``TGridExecutionGuard`` consumes the REQUIRED :class:`TGridEvidenceSource`
    (iteration 14, P1-1): every evidence supplier comes from the caller —
    there are NO permissive/self-certified defaults in the production builder,
    so construction fails closed when evidence sources are absent.  The
    ``TGridSidecar`` persists the TGrid SQLite OrderIntent + Reservation +
    daily exposure through ``before_broker_submit`` / ``before_broker_cancel``.

    Iteration 16 (Core 0.4): ``runtime_lock_mode`` defaults to ``"shared"``.
    Shared mode wires the runtime session as Core's
    ``CoordinatedExecutionSession``: it REQUIRES an explicit account-level
    ``coordination_path`` (the canonical coordination DB common to every
    strategy process sharing the broker account) or an injected
    ``coordinator`` (tests), plus an explicit conservative ``cash_estimator``
    (no implicit ``qty * price`` fallback).  The builder fails closed if
    shared mode is requested without them, and never defaults coordination to
    a strategy-specific journal/database path.  ``exclusive`` mode remains
    available for explicitly single-writer test/compatibility use.

    A journal bound to a different qmt-execution-core source/spec build
    (:class:`JournalIntegrityError`) is REJECTED — the builder never disables
    or bypasses the public-core hash binding and never silently migrates an
    old 0.3.1 journal.  The documented cutover is operator-driven: reconcile
    the old execution under the old deployment, archive the old journal,
    configure a new 0.4 journal path, then build.

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
    if runtime_lock_mode not in ("shared", "exclusive"):
        raise QecRuntimeError(
            "runtime_lock_mode must be exactly 'shared' or 'exclusive'"
        )
    if runtime_lock_mode == "shared":
        if coordinator is None and coordination_path is None:
            raise QecRuntimeError(
                "shared runtime mode requires an explicit account-level "
                "coordination_path (canonical coordination DB common to every "
                "strategy process sharing the broker account) or an injected "
                "coordinator; refusing to run shared mode without coordination"
            )
        if cash_estimator is None:
            raise QecRuntimeError(
                "shared runtime mode requires an explicit conservative "
                "CashRequirementEstimator for coordinated BUY (no implicit "
                "qty*price fallback); refusing to build without one"
            )
        if not callable(getattr(cash_estimator, "estimate", None)):
            raise QecRuntimeError(
                "cash_estimator must implement estimate(request, account_snapshot)"
            )
    if coordinator is not None and not callable(
        getattr(coordinator, "prepare", None)
    ):
        raise QecRuntimeError(
            "coordinator must implement the ExecutionCoordinator protocol"
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
        runtime_lock_mode=runtime_lock_mode,
        coordination_path=(
            Path(coordination_path) if coordination_path is not None else None
        ),
    )
    try:
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
            coordinator=coordinator,
            cash_estimator=cash_estimator,
        )
    except JournalIntegrityError as exc:
        raise QecRuntimeError(
            "journal is bound to a different qmt-execution-core source/spec "
            "build; public-core hash binding must not be disabled. Reconcile "
            "the old execution under the old deployment, archive the old "
            "journal, and configure a new 0.4 journal path before rebuilding"
        ) from exc
    return runtime


def default_cash_requirement_estimator() -> ConservativeCashRequirementEstimator:
    """Explicit conservative A-share BUY estimator used by Gate-6 wiring.

    The estimator is ALWAYS passed explicitly to Core coordinated BUY — there
    is no implicit ``qty * price`` fallback anywhere in the TGrid composition.
    Buffers are documented per plan §5:

    * order notional:            ``qty * limit_price`` (Core computes it);
    * transaction cost buffer:   commission rate 0.03% with a 5 CNY minimum
                                 (plus transfer-fee margin folded into the
                                 rate);
    * temporary withholding:     not applicable to A-share stock BUY (0);
    * FX / rounding buffer:      not applicable (CNY-denominated) (0);
    * safety buffer:             0 by default — deployments may raise it for
                                 extra headroom.

    Conservative direction: every configured buffer is ADDED to the required
    cash before Core atomically reserves it against fresh broker cash.
    """
    return ConservativeCashRequirementEstimator(
        fee_rate=0.0003,
        minimum_fee=5.0,
        temporary_withholding_buffer=0.0,
        fx_rounding_rate=0.0,
        safety_buffer=0.0,
    )
