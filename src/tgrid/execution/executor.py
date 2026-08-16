"""TGrid execution engine — TGrid-specific orchestration over the public core.

Migration Phase D: the generic broker lifecycle / state machine / journal /
mutex / recovery now live in qmt-execution-core.  :class:`ExecutionEngine`
keeps only TGrid-specific orchestration:

* exact-type + finiteness validation of decision inputs (AUD-R1-007,
  NODEB-I2-005) BEFORE any arithmetic, persistence or broker call;
* idempotency guard on ``client_order_key`` (INV-013);
* the reservation-vs-declared-capacity gate;
* SAFE_MODE bookkeeping and the authoritative broker/local reconciliation
  that clears it (NODEB-RR6-001 semantics, executed here against the public
  broker surface);
* mapping decisions to public ``ExecutionRequest`` and folding public
  ``ExecutionSnapshot`` outcomes back into the TGrid SQLite ledger.

The engine drives an injected public-core ``ExecutionSession`` (broker +
``ExecutionGuard`` + journal/mutex + the TGrid ``TGridSidecar`` pre-broker
durable-ledger hooks).  The engine never touches raw QMT order/cancel APIs.
"""

from __future__ import annotations

import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

from qmt_execution_core.domain import ExecutionRequest, TradeState
from qmt_execution_core.session import ExecutionSession

from tgrid.execution.models import BUY, SELL, OrderIntent, OrderStatus
from tgrid.execution.store import (
    ExecutionStore,
    ExecutionStoreError,
    IntentNotFoundError,
)
from tgrid.integrations.daily_exposure import DailyExposureLedger
from tgrid.integrations.qec_adapter import (
    TGridEvidenceSource,
    TGridExecutionGuard,
    TGridSidecar,
    apply_snapshot,
    make_execution_request,
)
from tgrid.risk.exceptions import TGridError

__all__ = [
    "ExecutionEngine",
    "ExecutionError",
    "ExecutionInputError",
    "ExecutionResult",
    "OrderSendFailedError",
    "OrderReconciliationError",
    "OrderTimeoutError",
    "CancelFailedError",
    "ReservationConflictError",
]


class ExecutionError(TGridError):
    """Base class for execution failures."""


class ExecutionInputError(ExecutionError):
    """A decision input failed exact-type / finiteness validation."""


class OrderSendFailedError(ExecutionError):
    """The broker refused or could not accept the order."""


class OrderReconciliationError(ExecutionError):
    """A broker status cannot be reconciled with the local intent."""


class OrderTimeoutError(ExecutionError):
    """An order exceeded order_timeout_seconds (design §25)."""


class CancelFailedError(ExecutionError):
    """Cancel failed; the order must be re-queried, never assumed (design §25)."""


class ReservationConflictError(ExecutionError):
    """The reservation cannot be booked (capacity or duplicate)."""


@dataclass(frozen=True)
class ExecutionResult:
    """Data-only outcome of one strategy decision execution."""

    client_order_key: str
    symbol: str
    side: str
    status: str
    broker_order_id: str | None
    filled_qty: int
    message: str
    fill_price: float | None = None


class ExecutionEngine:
    """TGrid-specific orchestration driving a public-core ExecutionSession.

    ``store`` (TGrid ``ExecutionStore``) is injected; ``broker`` is a
    qmt-execution-core ``BrokerPort`` (``SimBroker`` for the dry run,
    ``MiniQmtBrokerAdapter`` for pre-live via ``build_qec_runtime``).  The
    engine builds the public session with a TGrid guard + sidecar: the guard
    gates submissions from TGrid evidence (including this engine's SAFE_MODE),
    and the sidecar persists the TGrid SQLite OrderIntent + Reservation +
    daily exposure BEFORE any broker side effect.
    """

    def __init__(
        self,
        store: object,
        broker: object | None = None,
        *,
        strategy_name: str = "TGRID",
        order_timeout_seconds: int = 120,
        max_reprice_attempts: int = 2,
        journal_path: object | None = None,
        lock_path: object | None = None,
        guard: object | None = None,
        sidecar: object | None = None,
        exposure: object | None = None,
        evidence: TGridEvidenceSource | None = None,
        session: object | None = None,
    ) -> None:
        if not isinstance(store, ExecutionStore):
            raise ExecutionInputError("store must be an ExecutionStore")
        if (broker is None) == (session is None):
            raise ExecutionInputError(
                "exactly one of broker (own session) or session (injected, "
                "runtime-owned) must be provided"
            )
        if type(strategy_name) is not str or strategy_name == "":
            raise ExecutionInputError("strategy_name must be a non-empty string")
        if type(order_timeout_seconds) is not int or order_timeout_seconds <= 0:
            raise ExecutionInputError("order_timeout_seconds must be a positive int")
        if type(max_reprice_attempts) is not int or max_reprice_attempts < 0:
            raise ExecutionInputError("max_reprice_attempts must be a non-negative int")
        self._store = store
        self._broker = broker
        self._strategy_name = strategy_name
        self._order_timeout_seconds = order_timeout_seconds
        self._max_reprice_attempts = max_reprice_attempts
        self._safe_mode_reason: str | None = None
        self._permanent_block_reason: str | None = None

        # Default evidence: the engine's own gates are live suppliers
        # (SAFE_MODE acts as the kill switch).  Production wiring passes an
        # explicit TGridEvidenceSource via build_qec_runtime.
        if evidence is None:
            evidence = TGridEvidenceSource(
                environment_verified=lambda: True,
                account_verified=lambda: True,
                broker_snapshot_verified=lambda: True,
                position_verified=lambda: True,
                cash_verified=lambda: True,
                quote_verified=lambda: True,
                kill_switch_active=lambda: self._safe_mode_reason is not None
                or self._permanent_block_reason is not None,
                exposure_ready=lambda: True,
                exposure_used=lambda: 0.0,
            )
        self._guard = guard or _EngineDefaultGuard(
            kill_switch_active=evidence.kill_switch_active,
        )
        exposure = exposure or DailyExposureLedger()
        self._sidecar = sidecar or TGridSidecar(
            store=store, exposure=exposure, strategy_name=strategy_name, now=lambda: "",
        )
        if session is not None:
            # Production composition (Iteration 15, P1-1): bind to the SAME
            # session owned by the MiniQmtRuntime — exactly one execution
            # authority; the runtime owns journal/mutex/sidecar/guard and
            # final teardown.  The engine does NOT create a second session.
            self._session = session
            self._owns_session = False
            self._session_opened = True
            return
        journal_path = journal_path or str(
            Path(tempfile.mkdtemp(prefix="tgrid-exec-")) / "journal.json"
        )
        lock_path = lock_path or str(
            Path(tempfile.mkdtemp(prefix="tgrid-exec-")) / "exec.lock"
        )
        self._session = ExecutionSession(
            broker=broker,
            guard=self._guard,
            journal_path=journal_path,
            lock_path=lock_path,
            execution_id=strategy_name,
            before_broker_submit=self._sidecar.before_broker_submit,
            before_broker_cancel=self._sidecar.before_broker_cancel,
        )
        self._owns_session = True
        self._session_opened = False

    def _policy_from_broker(self):
        # Removed in Phase D: the dry-run engine does not enforce a production
        # policy; TGridExecutionGuard with a LiveBrokerPolicy is supplied by
        # production wiring (build_qec_runtime).
        return None

    # ------------------------------------------------------------- queries

    @property
    def store(self) -> ExecutionStore:
        return self._store

    @property
    def session(self) -> ExecutionSession:
        return self._session

    def close(self) -> None:
        """Release the session — idempotent.

        When the engine owns its session (broker mode) the session mutex is
        released.  When the session is INJECTED (production composition,
        Iteration 15 P1-1) the MiniQmtRuntime owns teardown: the engine only
        forgets its reference so no second close path exists.
        """
        if self._session_opened:
            if self._owns_session:
                try:
                    self._session.close()
                finally:
                    self._session_opened = False
            else:
                self._session_opened = False

    @property
    def safe_mode(self) -> bool:
        """True when an unresolved broker state blocks new-order execution."""
        return self._safe_mode_reason is not None

    @property
    def safe_mode_reason(self) -> str | None:
        return self._safe_mode_reason

    def engage_safe_mode(self, reason: str) -> None:
        """Explicitly block new orders until a reconciliation clears it."""
        if type(reason) is not str or reason == "":
            raise ExecutionInputError("safe-mode reason must be a non-empty string")
        self._safe_mode_reason = reason

    def block_permanently(self, reason: str) -> None:
        """IRREVERSIBLY disable new orders on this engine (SM9-002)."""
        if type(reason) is not str or reason == "":
            raise ExecutionInputError("block reason must be a non-empty string")
        self._permanent_block_reason = reason

    def _require_not_safe_mode(self) -> None:
        if self._permanent_block_reason is not None:
            raise ExecutionError(
                f"execution disabled: {self._permanent_block_reason}"
            )
        if self._safe_mode_reason is not None:
            raise ExecutionError(
                f"SAFE_MODE: {self._safe_mode_reason}; "
                "new orders blocked until reconciliation resolves"
            )

    def pending_order_keys(self, *, symbol: str | None = None) -> tuple:
        """client_order_keys in a pending (non-terminal) state."""
        keys = []
        for intent in self._store.list_intents():
            if intent.status in ("FILLED", "CANCELED", "REJECTED", "UNKNOWN"):
                continue
            if symbol is not None and intent.symbol != symbol:
                continue
            keys.append(intent.client_order_key)
        return tuple(keys)

    def reconcile_and_clear_safe_mode(self) -> None:
        """Authoritative SAFE_MODE release (NODEB-RR6-001 semantics).

        Executed HERE against the public broker surface (strict queries via
        the public session's broker): every non-terminal intent must match a
        known-status broker order; unresolved / UNKNOWN outcomes keep
        SAFE_MODE and fail closed.  No caller-supplied result object can
        clear SAFE_MODE.
        """
        from qmt_execution_core.domain import BrokerOrderStatus

        open_intents = [
            i for i in self._store.list_intents()
            if i.status not in ("FILLED", "CANCELED", "REJECTED", "UNKNOWN")
        ]
        orders = tuple(self._session.broker.query_orders())
        matched_ids = set()
        for intent in open_intents:
            matches = [
                o for o in orders
                if (o.client_order_id or "") == intent.client_order_key
                or (o.order_remark or "") == (intent.order_remark or "")
            ]
            if len(matches) != 1 or matches[0].status is BrokerOrderStatus.UNKNOWN:
                raise ExecutionError(
                    "authoritative reconciliation did not resolve all intents; "
                    "SAFE_MODE retained"
                )
            matched_ids.add(matches[0].order_id)
        # Broker orders tagged TGRID with no local intent: duplicate-order risk.
        local_keys = {i.client_order_key for i in self._store.list_intents()}
        for order in orders:
            remark = getattr(order, "order_remark", "") or ""
            if not remark.startswith("TG_"):
                continue
            if order.order_id in matched_ids:
                continue
            if (order.client_order_id or "") in local_keys:
                continue
            if order.status in (
                BrokerOrderStatus.FILLED,
                BrokerOrderStatus.CANCELLED,
                BrokerOrderStatus.REJECTED,
            ):
                continue
            raise ExecutionError(
                "authoritative reconciliation found an unmatched TGRID broker "
                "order; SAFE_MODE retained"
            )
        self._safe_mode_reason = None

    # -------------------------------------------------------------- actions

    def send_buy(
        self,
        *,
        client_order_key: str,
        symbol: str,
        qty: int,
        limit_price: float,
        order_remark: str,
        now: str,
        expected_available_cash: float,
        reserved_cash: float,
    ) -> ExecutionResult:
        """Send a BUY: validate, reserve via the sidecar, broker, SUBMITTED."""
        return self._send(
            side=BUY,
            client_order_key=client_order_key,
            symbol=symbol,
            qty=qty,
            limit_price=limit_price,
            order_remark=order_remark,
            now=now,
            cash_amount=reserved_cash,
            expected_available=expected_available_cash,
        )

    def send_sell(
        self,
        *,
        client_order_key: str,
        symbol: str,
        qty: int,
        limit_price: float,
        order_remark: str,
        now: str,
        expected_available_qty: int,
    ) -> ExecutionResult:
        """Send a SELL: validate, reserve via the sidecar, broker."""
        return self._send(
            side=SELL,
            client_order_key=client_order_key,
            symbol=symbol,
            qty=qty,
            limit_price=limit_price,
            order_remark=order_remark,
            now=now,
            cash_amount=None,
            expected_available=expected_available_qty,
        )

    def _send(
        self,
        *,
        side: str,
        client_order_key: str,
        symbol: str,
        qty: int,
        limit_price: float,
        order_remark: str,
        now: str,
        cash_amount: float | None,
        expected_available: object,
    ) -> ExecutionResult:
        for name, value in (
            ("client_order_key", client_order_key),
            ("symbol", symbol),
            ("order_remark", order_remark),
            ("now", now),
        ):
            if type(value) is not str or value == "":
                raise ExecutionInputError(f"{name} must be a non-empty string")
        if side not in (BUY, SELL):
            raise ExecutionInputError("side must be BUY or SELL")
        if type(qty) is not int or qty <= 0:
            raise ExecutionInputError("qty must be a positive plain int")
        # NODEB-I2-005 / AUD-R1-007: reject NaN/±Inf / wrong types BEFORE any
        # arithmetic, persistence or broker call.
        if type(limit_price) not in (int, float) or isinstance(limit_price, bool):
            raise ExecutionInputError("limit_price must be a plain number")
        if not math.isfinite(float(limit_price)) or limit_price <= 0:
            raise ExecutionInputError("limit_price must be a finite positive number")
        if side == BUY:
            if (type(expected_available) not in (int, float)
                    or isinstance(expected_available, bool)):
                raise ExecutionInputError(
                    "expected_available_cash must be a non-negative number"
                )
            if not math.isfinite(float(expected_available)) or expected_available < 0:
                raise ExecutionInputError(
                    "expected_available_cash must be a finite non-negative number"
                )
            if cash_amount is None or (type(cash_amount) not in (int, float)
                                       or isinstance(cash_amount, bool)):
                raise ExecutionInputError("reserved cash must be a non-negative number")
            if not math.isfinite(float(cash_amount)) or cash_amount < 0:
                raise ExecutionInputError(
                    "reserved cash must be a finite non-negative number"
                )
        else:
            if type(expected_available) is not int or expected_available < 0:
                raise ExecutionInputError(
                    "expected_available_qty must be a plain non-negative int"
                )

        # Idempotency (INV-013): never send twice.
        try:
            existing = self._store.get_intent(client_order_key)
        except IntentNotFoundError:
            existing = None
        except ExecutionStoreError as exc:
            raise ExecutionError("cannot read intent store") from exc
        if existing is not None:
            raise ExecutionError(
                f"client_order_key {client_order_key!r} already exists; "
                "refusing to duplicate an order intent"
            )

        # Reservation conflict gate (design §18.3): the new reservation must
        # fit within the caller-provided capacity (the sidecar creates it
        # atomically with the intent BEFORE the broker call).
        if side == BUY:
            if cash_amount > float(expected_available):
                raise ReservationConflictError(
                    "reserved cash would exceed the available cash"
                )
        else:
            if qty > int(expected_available):
                raise ReservationConflictError(
                    "reserved sell qty would exceed the available T quantity"
                )

        # NODEB-I2-002: an unresolved broker state blocks new execution.
        self._require_not_safe_mode()

        if not self._session_opened:
            self._session.open()
            self._session_opened = True

        # Public-core lifecycle: one order per cycle.  A completed cycle
        # (FILLED/CANCELLED/REJECTED) must advance to the next before a new
        # order is submitted (durable id reuse protection is preserved).
        if self._session.machine.state in (
            TradeState.FILLED,
            TradeState.CANCELLED,
            TradeState.REJECTED,
        ):
            self._session.next_cycle()

        # The sidecar's `now` provider: point it at THIS decision's timestamp
        # so the TGrid ledger gets the correct durable time.
        self._sidecar._now = lambda: now

        request = make_execution_request(
            client_order_key=client_order_key,
            symbol=symbol,
            side=side,
            qty=qty,
            limit_price=limit_price,
            strategy_name=self._strategy_name,
            order_remark=order_remark,
        )
        from qmt_execution_core.exceptions import (
            BrokerError,
            BrokerSubmissionAmbiguous,
            BrokerSubmissionRejected,
        )

        try:
            snapshot = self._session.submit(request)
        except (BrokerSubmissionRejected, BrokerSubmissionAmbiguous,
                BrokerError) as exc:
            # Public-core submission failure (incl. pre-submit health gate):
            # surface as the TGrid send-failure contract.  An ambiguous
            # outcome after broker acceptance is handled via
            # recover_unknown_submission (poll), not a raised error here.
            raise OrderSendFailedError(
                "broker refused or could not accept the order"
            ) from exc
        except RuntimeError as exc:
            # e.g. "cannot submit from working": the public-core lifecycle is
            # one order at a time — a TGrid orchestration concern.
            raise ExecutionError(str(exc)) from exc
        return self._result_from_snapshot(
            snapshot, client_order_key=client_order_key, symbol=symbol,
            side=side, now=now,
        )

    def poll_order(self, client_order_key: str, *, now: str) -> ExecutionResult:
        """Re-query the broker and fold fills/terminal states back into the intent."""
        intent = self._store.get_intent(client_order_key)
        if intent.status in ("FILLED", "CANCELED", "REJECTED", "UNKNOWN"):
            # Terminal intent: no broker re-query (the public session is
            # one-cycle and a terminal observation is not a refinement).
            return ExecutionResult(
                client_order_key=intent.client_order_key, symbol=intent.symbol,
                side=intent.side, status=intent.status,
                broker_order_id=intent.broker_order_id,
                filled_qty=intent.qty if intent.status == "FILLED" else 0,
                message="intent already terminal",
            )
        self._require_session()
        self._sidecar._now = lambda: now
        if self._session.machine.state in (
            TradeState.FILLED,
            TradeState.CANCELLED,
            TradeState.REJECTED,
            TradeState.CANCEL_REJECTED,
            TradeState.FAILED,
        ):
            # The session already consumed the terminal observation (e.g. on
            # restart recovery); fold the snapshot without re-polling.
            snapshot = self._session.snapshot()
        else:
            snapshot = self._session.poll()
        return self._result_from_snapshot(
            snapshot, client_order_key=client_order_key,
            symbol=intent.symbol, side=intent.side, now=now,
        )

    def timeout_order(self, client_order_key: str, *, now: str) -> ExecutionResult:
        """Design §25: cancel -> re-query -> reconcile; never assume unfilled."""
        self._require_session()
        self._sidecar._now = lambda: now
        intent = self._store.get_intent(client_order_key)
        if intent.broker_order_id is None:
            raise OrderReconciliationError("intent has no broker_order_id")
        snapshot = self._session.cancel()
        return self._result_from_snapshot(
            snapshot, client_order_key=client_order_key,
            symbol=intent.symbol, side=intent.side, now=now,
        )

    def cancel_order(self, client_order_key: str, *, now: str) -> ExecutionResult:
        """Best-effort cancel used by kill-switch paths (design §30)."""
        return self.timeout_order(client_order_key, now=now)

    def recover_unknown_submission(
        self,
        client_order_key: str,
        *,
        now: str,
    ) -> ExecutionResult:
        """Resolve a public UNKNOWN via the session's authoritative recovery.

        The public core forbids blind resend and recovers by the durable
        intent identity; a zero/duplicate/ambiguous match fails closed.
        """
        self._require_session()
        self._sidecar._now = lambda: now
        intent = self._store.get_intent(client_order_key)
        snapshot = self._session.poll()
        return self._result_from_snapshot(
            snapshot, client_order_key=client_order_key,
            symbol=intent.symbol, side=intent.side, now=now,
        )

    # -------------------------------------------------------------- helpers

    def _require_session(self) -> None:
        if not self._session_opened:
            self._session.open()
            self._session_opened = True

    def _result_from_snapshot(
        self,
        snapshot,
        *,
        client_order_key: str,
        symbol: str,
        side: str,
        now: str,
    ) -> ExecutionResult:
        """Fold a public snapshot into the TGrid ledger and build the result."""
        try:
            intent = self._store.get_intent(client_order_key)
        except IntentNotFoundError:
            intent = None
        if intent is not None:
            apply_snapshot(
                self._store, snapshot, client_order_key=client_order_key, now=now,
            )
            intent = self._store.get_intent(client_order_key)
        status = _snapshot_status(snapshot, intent)
        broker_order_id = (
            str(snapshot.broker_order_id)
            if snapshot.broker_order_id is not None
            else (intent.broker_order_id if intent is not None else None)
        )
        return ExecutionResult(
            client_order_key=client_order_key,
            symbol=symbol,
            side=side,
            status=status,
            broker_order_id=broker_order_id,
            filled_qty=int(snapshot.filled_qty or 0),
            message=f"state={snapshot.state.value}",
            fill_price=snapshot.average_fill_price,
        )


def _snapshot_status(snapshot, intent) -> str:
    """Map a public snapshot (or the folded TGrid intent) to an OrderStatus."""
    from tgrid.integrations.qec_adapter import snapshot_status_to_tgrid

    if snapshot.state is TradeState.UNKNOWN and intent is not None:
        # Transient UNKNOWN keeps the last durable pending TGrid status.
        return intent.status
    return snapshot_status_to_tgrid(snapshot.state)


class _EngineDefaultGuard:
    """Permissive dry-run guard: only the engine's SAFE_MODE blocks submits.

    Production wiring supplies a TGridExecutionGuard backed by a
    TGridEvidenceSource; this default exists only for the offline dry run.
    """

    def __init__(self, *, kill_switch_active):
        self._kill_switch_active = kill_switch_active

    def verify_session(self):
        from qmt_execution_core.domain import SessionEvidence

        return SessionEvidence(ready=True, environment_verified=True, account_verified=True)

    def verify(self, request):
        from qmt_execution_core.domain import PrecheckEvidence

        kill = bool(self._kill_switch_active())
        return PrecheckEvidence(
            allowed=not kill,
            environment_verified=True,
            account_verified=True,
            broker_snapshot_verified=True,
            position_verified=True,
            cash_verified=True,
            quote_verified=True,
            reason="" if not kill else "SAFE_MODE blocks new orders",
        )


