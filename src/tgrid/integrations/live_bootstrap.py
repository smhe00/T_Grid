"""Single production-shaped live-stack bootstrap (NODEB-I2-006, NODEB-RR-003).

One audited construction path binds the whole pre-live stack in a safe order:

::

    validated runtime config (live=false default)
    -> LiveBrokerPolicy
    -> durable DailyExposure store
    -> real TGrid EventQueue
    -> XtQuantBrokerBridge
    -> LiveBrokerAdapter
    -> mandatory startup order/intent recovery   (RR-003)
    -> separate non-persisted runtime confirmation
    -> ExecutionEngine

:func:`build_live_stack` returns a :class:`LiveStack`.  Production activation
(NODEB-RR-003) ALWAYS performs order/intent recovery — it does NOT accept a
``None`` recovery path — and runtime confirmation happens only after recovery
is complete.  ``UNKNOWN`` statuses, duplicate/ambiguous matches,
``UNMATCHED_BROKER_ORDER``, and unresolved ``INTENT_ONLY`` intents block
activation until explicitly reconciled.  SAFE_MODE is cleared only through the
reconciliation-driven :meth:`LiveStack.reconcile_and_resume` transition, never
by flipping a naked flag (the engine's public ``clear_safe_mode`` remains a
low-level unit hook; the production path uses the driven transition).

Tests use fake XtQuant only; no real order/cancel is invoked.
"""

from __future__ import annotations

from dataclasses import dataclass

from tgrid.events import EventQueue
from tgrid.execution.executor import ExecutionEngine
from tgrid.execution.recovery import reconcile_open_intents
from tgrid.execution.store import ExecutionStore
from tgrid.integrations.live_broker_adapter import (
    LiveBrokerAdapter,
    LiveBrokerPolicy,
)
from tgrid.integrations.xtquant_bridge import XtQuantBrokerBridge


class LiveBootstrapError(Exception):
    """Base class for live-stack bootstrap failures."""


@dataclass
class LiveStack:
    """The assembled pre-live stack, ready only after :meth:`activate`."""

    engine: ExecutionEngine
    adapter: LiveBrokerAdapter
    bridge: XtQuantBrokerBridge
    event_queue: EventQueue
    strategy_name: str

    def activate(
        self,
        *,
        token: str,
        session_date: str | None = None,
    ) -> None:
        """Perform MANDATORY startup recovery + runtime confirmation (RR-003).

        Startup order/intent recovery is never optional: every non-terminal
        local intent is reconciled against the broker; ``UNKNOWN`` statuses,
        duplicate/ambiguous matches, ``UNMATCHED_BROKER_ORDER`` and unresolved
        ``INTENT_ONLY`` outcomes fail closed.  Runtime confirmation happens
        only after recovery completes.
        """
        if self.event_queue.state.value != "RUNNING":
            self.event_queue.start()
        if session_date is not None:
            self.adapter.roll_day(session_date, session_date=session_date)
        # 1) Startup exposure reconstruction (mandatory readiness gate),
        #    joined to durable OrderIntent dates (NODEB-RR4-003).
        self.adapter.reconstruct_daily_exposure(
            intents=self.engine.store.list_intents()
        )
        # 2) MANDATORY startup order/intent recovery (RR-003): the recovery
        #    entry point is never None on the production path.
        results = reconcile_open_intents(self.engine.store, self.adapter)
        blocked = [
            r for r in results
            if r.outcome in ("UNMATCHED_BROKER_ORDER", "INTENT_ONLY")
        ]
        if blocked:
            self.engine.engage_safe_mode(
                "startup recovery found unresolved intents"
            )
            raise LiveBootstrapError(
                "startup recovery found unresolved intents: "
                + ", ".join(f"{r.outcome}:{r.client_order_key}" for r in blocked)
                + "; refusing to activate (SAFE_MODE)"
            )
        # 3) Separate, non-persisted runtime confirmation.
        self.adapter.confirm_runtime(token)

    def reconcile_and_resume(self, *, token: str, session_date: str | None = None) -> None:
        """Reconciliation-driven SAFE_MODE release (RR-003 / RR4-002 / RR5-002).

        The ONLY production SAFE_MODE release path.  The engine itself executes
        the authoritative broker/local reconciliation — no public caller-
        supplied proof API exists and a fabricated result cannot clear
        SAFE_MODE (NODEB-RR6-001).
        """
        if session_date is not None:
            self.adapter.roll_day(session_date, session_date=session_date)
        self.adapter.reconstruct_daily_exposure(
            intents=self.engine.store.list_intents()
        )
        self.engine.reconcile_and_clear_safe_mode()
        self.adapter.confirm_runtime(token)

    def recover_after_disconnect(
        self,
        *,
        token: str,
        session_date: str | None = None,
    ) -> None:
        """LiveStack-orchestrated disconnect recovery (NODEB-RR5-003).

        Low-level transport reconnection alone must NOT restore order
        capability.  Production disconnect recovery runs, in order:

        EventQueue RUNNING -> exact connect success -> bound securities
        account type/OK-status verification -> subscribe/verification ->
        exposure reconstruction -> authoritative broker/local reconciliation
        -> explicit runtime reconfirmation -> only then clear the disconnect
        latch.
        """
        bridge = self.bridge
        # 1) Transport verification (queue RUNNING + exact connect success).
        bridge.verify_transport()
        # 2) Bound account type/status verification.
        bridge._verify_bound_account_healthy()
        # 3) Re-subscribe + exact result verification.
        subscribe_fn = getattr(bridge._trader, "subscribe", None)
        if not callable(subscribe_fn):
            raise LiveBootstrapError(
                "broker has no subscribe surface; disconnect recovery denied"
            )
        try:
            subscribe_result = subscribe_fn(bridge._account)
        except Exception as exc:  # noqa: BLE001 - broker boundary
            raise LiveBootstrapError("re-subscribe failed") from exc
        if type(subscribe_result) is not int or subscribe_result != 0:
            raise LiveBootstrapError(
                "re-subscribe did not return the exact success value"
            )
        # 4) Exposure reconstruction (mandatory readiness gate).
        self.adapter.reconstruct_daily_exposure(
            intents=self.engine.store.list_intents()
        )
        # 5) Authoritative broker/local reconciliation; unresolved intents
        #    keep execution blocked.  The engine executes it itself (RR6-001).
        self.engine.reconcile_and_clear_safe_mode()
        # 6) Explicit runtime reconfirmation.
        self.adapter.confirm_runtime(token)
        # 7) Only now clear the disconnect latch.
        bridge._clear_disconnect_latch()


def build_live_stack(
    *,
    trader: object,
    account: object,
    store: ExecutionStore,
    policy: LiveBrokerPolicy,
    exposure_store: object,
    event_queue: EventQueue,
    trade_date: str = "",
    runtime_confirmation_token: str = "",
    strategy_name: str = "TGRID",
    order_timeout_seconds: int = 120,
    config_live_enabled: bool = False,
    security_account_type: int | None = None,
    account_status_ok: int | None = None,
) -> LiveStack:
    """Assemble the live stack in the audited order (fake/real trader both ok).

    ``trader`` is the injected XtQuantTrader-like object (fake in tests, real
    in production wiring); the stack NEVER invokes a real order/cancel itself.
    ``config_live_enabled`` is the trusted runtime-config live flag; it
    defaults **false** and is applied via the adapter's trusted config path.
    ``security_account_type`` / ``account_status_ok`` are the exact XtQuant
    constants resolved during production session construction; they are
    persisted into the bridge for reconnect account-health verification
    (NODEB-RR6-002).
    """
    bridge = XtQuantBrokerBridge(
        trader, account, strategy_name=strategy_name, event_sink=event_queue,
        security_account_type=security_account_type,
        account_status_ok=account_status_ok,
    )
    adapter = LiveBrokerAdapter(
        broker=bridge, policy=policy,
        trade_date=trade_date,
        exposure_store=exposure_store,
        runtime_confirmation_token=runtime_confirmation_token,
    )
    adapter.apply_config_enable(config_live_enabled)
    engine = ExecutionEngine(
        store, adapter, strategy_name=strategy_name,
        order_timeout_seconds=order_timeout_seconds,
    )
    return LiveStack(
        engine=engine, adapter=adapter, bridge=bridge,
        event_queue=event_queue, strategy_name=strategy_name,
    )
