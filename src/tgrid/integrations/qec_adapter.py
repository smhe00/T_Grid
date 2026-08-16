"""TGrid <-> qmt-execution-core integration adapter (migration Phase B).

A thin, broker-neutral layer that maps TGrid execution decisions onto the
independently audited public ``qmt-execution-core`` model and satisfies the
TGrid durable-ledger invariant:

    TGrid SQLite OrderIntent + Reservation + pre-send daily exposure
    MUST COMMIT BEFORE any broker side effect.

Components:

* :func:`make_execution_request` — TGrid plan -> public ``ExecutionRequest``;
* :class:`TGridExecutionGuard` — public ``ExecutionGuard`` fed by the TGrid
  layer's CURRENT verified checks (evidence is never fabricated, and no
  durable side effect lives here — the sidecar owns that);
* :class:`TGridSidecar` — the public ``before_broker_submit`` /
  ``before_broker_cancel`` hooks that atomically persist TGrid's SQLite
  OrderIntent + Reservation + daily exposure AFTER the public-core durable
  intent and BEFORE the broker side effect (a raised hook proves the broker
  call was never invoked — fail closed);
* :func:`snapshot_status_to_tgrid` / :func:`apply_snapshot` — fold public
  execution snapshots / normalized broker observations back into the TGrid
  ledger.

Raw QMT status values never cross this layer (the public core normalizes
them); broker order ids stay native ints in the public core and are stored as
their decimal strings in TGrid's SQLite ledger (existing TGrid convention).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from qmt_execution_core.domain import (
    ExecutionRequest,
    ExecutionSnapshot,
    PrecheckEvidence,
    SessionEvidence,
    Side,
    TradeState,
)

from tgrid.execution.models import OrderStatus
from tgrid.execution.store import ExecutionStore
from tgrid.integrations.daily_exposure import DailyExposureLedger
from tgrid.integrations.live_broker_adapter import LiveBrokerPolicy


@dataclass(frozen=True)
class TGridEvidenceSource:
    """Live evidence suppliers for the production guard (iteration 14, P1-1).

    The production cutover builder REQUIRES every supplier (no permissive
    default): a missing or unhealthy evidence source must fail closed.  Fake
    tests may pass explicit ``lambda: True`` suppliers.
    """

    environment_verified: Callable[[], bool]
    account_verified: Callable[[], bool]
    broker_snapshot_verified: Callable[[], bool]
    position_verified: Callable[[], bool]
    cash_verified: Callable[[], bool]
    quote_verified: Callable[[], bool]
    kill_switch_active: Callable[[], bool]
    exposure_ready: Callable[[], bool]
    exposure_used: Callable[[], float]


def make_execution_request(
    *,
    client_order_key: str,
    symbol: str,
    side: str,
    qty: int,
    limit_price: float,
    strategy_name: str,
    order_remark: str,
) -> ExecutionRequest:
    """Map a TGrid execution decision onto the public ``ExecutionRequest``.

    ``client_order_key`` becomes the public ``client_order_id`` (the durable
    idempotency key in both systems); ``strategy_name`` becomes
    ``strategy_id``.  The public core validates all fields strictly.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    return ExecutionRequest(
        client_order_id=client_order_key,
        symbol=symbol,
        side=Side(side),
        qty=qty,
        limit_price=limit_price,
        strategy_id=strategy_name,
        order_remark=order_remark,
    )


class TGridExecutionGuard:
    """Public-core ``ExecutionGuard`` backed by TGrid's current verified state.

    All evidence flags are evaluated at call time from the injected callables
    (TGrid layer state), so the guard cannot fabricate verification.  It
    performs NO durable side effects — TGrid's pre-send persistence belongs to
    :class:`TGridSidecar`.
    """

    def __init__(
        self,
        *,
        policy: LiveBrokerPolicy,
        environment_verified: Callable[[], bool],
        account_verified: Callable[[], bool],
        broker_snapshot_verified: Callable[[], bool],
        position_verified: Callable[[], bool],
        cash_verified: Callable[[], bool],
        quote_verified: Callable[[], bool],
        kill_switch_active: Callable[[], bool],
        exposure_ready: Callable[[], bool],
        exposure_used: Callable[[], float],
    ) -> None:
        if not isinstance(policy, LiveBrokerPolicy):
            raise TypeError("policy must be a LiveBrokerPolicy")
        self._policy = policy
        self._environment_verified = environment_verified
        self._account_verified = account_verified
        self._broker_snapshot_verified = broker_snapshot_verified
        self._position_verified = position_verified
        self._cash_verified = cash_verified
        self._quote_verified = quote_verified
        self._kill_switch_active = kill_switch_active
        self._exposure_ready = exposure_ready
        self._exposure_used = exposure_used

    def verify_session(self) -> SessionEvidence:
        environment_verified = bool(self._environment_verified())
        account_verified = bool(self._account_verified())
        return SessionEvidence(
            ready=environment_verified and account_verified,
            environment_verified=environment_verified,
            account_verified=account_verified,
        )

    def verify(self, request: ExecutionRequest) -> PrecheckEvidence:
        environment_verified = bool(self._environment_verified())
        account_verified = bool(self._account_verified())
        broker_snapshot_verified = bool(self._broker_snapshot_verified())
        position_verified = bool(self._position_verified())
        cash_verified = bool(self._cash_verified())
        quote_verified = bool(self._quote_verified())
        kill_active = bool(self._kill_switch_active())
        exposure_ready = bool(self._exposure_ready())
        notional = request.qty * float(request.limit_price)
        exposure_used = float(self._exposure_used())

        allowed = (
            environment_verified
            and account_verified
            and broker_snapshot_verified
            and position_verified
            and cash_verified
            and quote_verified
            and not kill_active
            and exposure_ready
            and request.symbol in self._policy.allowlist
            and request.qty <= self._policy.max_order_qty
            and notional <= self._policy.max_cash_per_order
            and exposure_used + notional <= self._policy.max_cash_per_day
        )
        return PrecheckEvidence(
            allowed=allowed,
            environment_verified=environment_verified,
            account_verified=account_verified,
            broker_snapshot_verified=broker_snapshot_verified,
            position_verified=position_verified,
            cash_verified=cash_verified,
            quote_verified=quote_verified,
            reason="" if allowed else "TGrid risk gate rejected the request",
        )


class TGridSidecar:
    """Public-core sidecar hooks that persist the TGrid durable ledger.

    ``before_broker_submit`` runs AFTER the public core committed its generic
    durable intent and BEFORE ``BrokerPort.place_order()``: it atomically
    creates the TGrid SQLite OrderIntent + Reservation and records the
    submitted BUY notional in the daily exposure ledger.  Any exception
    propagates out of the public submit and PROVES the broker call was never
    invoked (fail closed).
    """

    def __init__(
        self,
        *,
        store: ExecutionStore,
        exposure: DailyExposureLedger,
        strategy_name: str,
        now: Callable[[], str],
    ) -> None:
        if not isinstance(store, ExecutionStore):
            raise TypeError("store must be an ExecutionStore")
        if not isinstance(exposure, DailyExposureLedger):
            raise TypeError("exposure must be a DailyExposureLedger")
        if type(strategy_name) is not str or not strategy_name:
            raise TypeError("strategy_name must be a non-empty string")
        self._store = store
        self._exposure = exposure
        self._strategy_name = strategy_name
        self._now = now

    def before_broker_submit(self, request: ExecutionRequest) -> None:
        """TGrid invariant: SQLite intent + reservation + exposure first."""
        cash_amount = request.qty * float(request.limit_price)
        self._store.create_intent_with_reservation(
            client_order_key=request.client_order_id,
            symbol=request.symbol,
            side=request.side.value,
            qty=request.qty,
            limit_price=float(request.limit_price),
            strategy_name=self._strategy_name,
            order_remark=request.order_remark,
            created_at=self._now(),
            # TGrid store: BUY reservations carry cash_amount; SELL must not.
            cash_amount=cash_amount if request.side is Side.BUY else None,
        )
        if request.side is Side.BUY:
            self._exposure.record_submitted_buy(cash_amount)

    def before_broker_cancel(self, order_id: int) -> None:
        """TGrid cancel accounting: mark the owning intent CANCEL_REQUESTED
        after the public durable cancel intent and before the broker cancel."""
        intent = self._intent_for_broker_order_id(order_id)
        if intent is None:
            return
        self._store.update_intent_status(
            intent.client_order_key,
            status=OrderStatus.CANCEL_REQUESTED,
            updated_at=self._now(),
        )

    def _intent_for_broker_order_id(self, order_id: int) -> object | None:
        for intent in self._store.list_intents():
            if intent.broker_order_id == str(order_id):
                return intent
        return None


def snapshot_status_to_tgrid(state: TradeState) -> str:
    """Map a public normalized TradeState to the TGrid OrderStatus vocabulary."""
    return {
        TradeState.IDLE: OrderStatus.NEW,
        TradeState.WAIT_TRIGGER: OrderStatus.NEW,
        TradeState.TRIGGER: OrderStatus.NEW,
        TradeState.PRE_CHECK: OrderStatus.NEW,
        TradeState.SUBMITTED: OrderStatus.SUBMITTED,
        TradeState.ACCEPTED: OrderStatus.SUBMITTED,
        TradeState.WORKING: OrderStatus.SUBMITTED,
        TradeState.PARTIALLY_FILLED: OrderStatus.PARTIAL,
        TradeState.FILLED: OrderStatus.FILLED,
        TradeState.PENDING_CANCEL: OrderStatus.CANCEL_REQUESTED,
        TradeState.CANCELLING: OrderStatus.CANCEL_REQUESTED,
        TradeState.CANCELLED: OrderStatus.CANCELED,
        TradeState.REJECTED: OrderStatus.REJECTED,
        TradeState.CANCEL_REJECTED: OrderStatus.UNKNOWN,
        TradeState.UNKNOWN: OrderStatus.UNKNOWN,
        TradeState.FAILED: OrderStatus.UNKNOWN,
    }[state]


def apply_snapshot(
    store: ExecutionStore,
    snapshot: ExecutionSnapshot,
    *,
    client_order_key: str,
    now: str,
) -> None:
    """Fold a public-core execution snapshot back into the TGrid SQLite ledger.

    Updates the TGrid intent's status and broker_order_id (stored as the
    decimal string of the native int, TGrid convention) and releases active
    reservations on true terminal outcomes (FILLED / CANCELED / REJECTED).

    Transient-UNKNOWN semantics (iteration 14, P1-2): public
    ``TradeState.UNKNOWN`` is a RECOVERABLE state, so it must NOT irreversibly
    terminalize the TGrid business intent.  While UNKNOWN, the last durable
    pending TGrid status is KEPT (e.g. SUBMITTED / PARTIAL / CANCEL_REQUESTED)
    so a later authoritative public recovery (WORKING / PARTIALLY_FILLED /
    FILLED / CANCELLED) can still update the same intent.  Only a terminal
    public recovery failure (``TradeState.FAILED``) maps to the terminal
    TGrid ``OrderStatus.UNKNOWN``.
    """
    intent = store.get_intent(client_order_key)
    if intent.status in ("FILLED", "CANCELED", "REJECTED", "UNKNOWN"):
        return
    if snapshot.state is TradeState.UNKNOWN:
        # Transient unresolved: keep the pending TGrid status; still persist
        # a broker_order_id discovered by public recovery.
        if snapshot.broker_order_id is not None:
            store.update_intent_status(
                client_order_key,
                status=intent.status,
                updated_at=now,
                broker_order_id=str(snapshot.broker_order_id),
            )
        return
    status = snapshot_status_to_tgrid(snapshot.state)
    broker_order_id = (
        str(snapshot.broker_order_id)
        if snapshot.broker_order_id is not None
        else None
    )
    store.update_intent_status(
        client_order_key,
        status=status,
        updated_at=now,
        broker_order_id=broker_order_id,
    )
    if status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED):
        for reservation in store.list_active_reservations():
            if reservation.client_order_key == client_order_key:
                store.release_reservation(reservation.id, released_at=now)
