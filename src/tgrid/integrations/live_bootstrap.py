"""Single production-shaped live-stack bootstrap (NODEB-I2-006).

One audited construction path binds the whole pre-live stack in a safe order:

::

    validated runtime config (live=false default)
    -> LiveBrokerPolicy
    -> durable DailyExposure store
    -> real TGrid EventQueue
    -> XtQuantBrokerBridge
    -> LiveBrokerAdapter
    -> startup recovery / exposure reconciliation
    -> separate non-persisted runtime confirmation
    -> ExecutionEngine

:func:`build_live_stack` returns a :class:`LiveStack` whose
:meth:`LiveStack.activate` performs startup reconciliation (exposure
reconstruction + optional order/intent reconciliation) and token-gated runtime
confirmation; the returned engine cannot place a new order until both steps
complete (the adapter's ``exposure_ready`` / ``runtime_confirmed`` gates
enforce it).  Tests use fake XtQuant only; no real order/cancel is invoked.
"""

from __future__ import annotations

from dataclasses import dataclass

from tgrid.events import EventQueue
from tgrid.execution.executor import ExecutionEngine
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
        reconcile_open_intents=None,
        session_date: str | None = None,
    ) -> None:
        """Perform startup reconciliation + runtime confirmation.

        ``reconcile_open_intents`` (optional) is the recovery entry point
        (``reconcile_open_intents(store, broker)``); when provided, an
        unresolved/ambiguous result raises and activation fails closed.
        Exposure reconstruction always runs first; the token-gated runtime
        confirmation happens last, so a fresh process cannot place a new order
        until the whole bootstrap completes.
        """
        if self.event_queue.state.value != "RUNNING":
            self.event_queue.start()
        if session_date is not None:
            self.adapter.roll_day(session_date)
        # 1) Startup exposure reconstruction (mandatory readiness gate).
        self.adapter.reconstruct_daily_exposure()
        # 2) Optional startup order/intent reconciliation (fail closed).
        if reconcile_open_intents is not None:
            results = reconcile_open_intents(self.engine.store, self.adapter)
            # NODEB-I2-002 #5: an unmatched tagged broker order is a
            # duplicate-order risk (SAFE_MODE); activation must fail closed.
            if any(r.outcome == "UNMATCHED_BROKER_ORDER" for r in results):
                raise LiveBootstrapError(
                    "startup reconciliation found unmatched tagged broker "
                    "orders; refusing to activate (SAFE_MODE)"
                )
        # 3) Separate, non-persisted runtime confirmation.
        self.adapter.confirm_runtime(token)


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
) -> LiveStack:
    """Assemble the live stack in the audited order (fake/real trader both ok).

    ``trader`` is the injected XtQuantTrader-like object (fake in tests, real
    in production wiring); the stack NEVER invokes a real order/cancel itself.
    ``config_live_enabled`` is the trusted runtime-config live flag; it
    defaults **false** and is applied via the adapter's trusted config path.
    """
    bridge = XtQuantBrokerBridge(
        trader, account, strategy_name=strategy_name, event_sink=event_queue,
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
