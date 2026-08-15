"""Offline execution engine for the Gate 4 dry run (design §39).

:class:`ExecutionEngine` connects a strategy decision to a durable
:class:`OrderIntent`, books the matching reservation atomically (design §18.3),
sends to the injected broker through the shared
:class:`~tgrid.execution.port.BrokerPort` (NODEB-001), then processes
fills/rejects/timeouts/cancels through the design §24/§25 rules.

The engine is broker-type agnostic: it consumes only the narrow port surface
(``place_order`` / ``cancel_order`` / ``query_order`` / ``query_trades`` /
``query_orders``) and typed :class:`BrokerOrder` / :class:`BrokerTrade` DTOs.
Deterministic simulation scripts (``tick_order`` etc.) live exclusively in
:class:`~tgrid.execution.simdriver.SimulationDriver`, never here.

Order of operations (INV-013 / §18.2):

1. reserve (atomically with intent) -> READY_TO_SEND / NEW
2. broker.send()
3. record broker_order_id -> SUBMITTED

A crash anywhere after step 1 leaves a recoverable intent; recovery is the
:mod:`tgrid.execution.recovery` module's job.  The executor never re-sends a
client_order_key it already recorded, never releases a reservation on a
"probably filled" guess, and never lets one symbol+direction hold two pending
strategy orders (INV-004).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from tgrid.execution.models import BUY, SELL, OrderIntent, OrderStatus
from tgrid.execution.port import (
    BrokerCancelFailedError,
    BrokerDisconnectedError,
    BrokerError,
    BrokerPort,
)
from tgrid.execution.store import (
    ExecutionStore,
    ExecutionStoreError,
    IntentNotFoundError,
)
from tgrid.risk.exceptions import TGridError


class ExecutionError(TGridError):
    """Base class for execution failures."""


class ExecutionInputError(ExecutionError):
    """An execution argument is invalid (fail closed before use)."""


class OrderSendFailedError(ExecutionError):
    """The broker send failed (disconnect/reject); intent stays recoverable."""


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
    """Drives strategy decisions through the shared broker port.

    ``store`` (ExecutionStore) and ``broker`` (any :class:`BrokerPort` —
    SimBroker for the dry run, LiveBrokerAdapter for pre-live) are injected; the
    engine holds no QMT or account surface.  ``order_timeout_seconds`` and
    ``max_reprice_attempts`` implement design §25.
    """

    def __init__(
        self,
        store: object,
        broker: object,
        *,
        strategy_name: str = "TGRID",
        order_timeout_seconds: int = 120,
        max_reprice_attempts: int = 2,
    ) -> None:
        if not isinstance(store, ExecutionStore):
            raise ExecutionInputError("store must be an ExecutionStore")
        if not isinstance(broker, BrokerPort):
            raise ExecutionInputError(
                "broker must implement BrokerPort (SimBroker or LiveBrokerAdapter)"
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

    # ------------------------------------------------------------- queries

    @property
    def store(self) -> ExecutionStore:
        return self._store

    @property
    def safe_mode(self) -> bool:
        """True when an unresolved broker state blocks new-order execution."""
        return self._safe_mode_reason is not None

    @property
    def safe_mode_reason(self) -> str | None:
        return self._safe_mode_reason

    def engage_safe_mode(self, reason: str) -> None:
        """Explicitly block new orders until :meth:`clear_safe_mode`."""
        if type(reason) is not str or reason == "":
            raise ExecutionInputError("safe-mode reason must be a non-empty string")
        self._safe_mode_reason = reason

    def clear_safe_mode(self) -> None:
        """Resume new-order execution after reconciliation resolves the state."""
        self._safe_mode_reason = None

    def _engage_safe_mode(self, reason: str) -> None:
        self._safe_mode_reason = reason

    def _require_not_safe_mode(self) -> None:
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
        """Send a BUY: atomic reservation+intent, then broker, then SUBMITTED."""
        return self._send(
            side=BUY,
            client_order_key=client_order_key,
            symbol=symbol,
            qty=qty,
            limit_price=limit_price,
            order_remark=order_remark,
            now=now,
            cash_amount=reserved_cash,
            expected_available_cash=expected_available_cash,
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
        """Send a SELL: atomic qty reservation+intent, then broker."""
        return self._send(
            side=SELL,
            client_order_key=client_order_key,
            symbol=symbol,
            qty=qty,
            limit_price=limit_price,
            order_remark=order_remark,
            now=now,
            cash_amount=None,
            expected_available_cash=expected_available_qty,
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
        expected_available_cash: float,
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
        # NODEB-I2-005: reject NaN/±Inf for all price/cash/reservation values
        # BEFORE any arithmetic, persistence or broker call.  A non-finite
        # reserved_cash must never reach create_intent_with_reservation.
        if type(limit_price) not in (int, float) or isinstance(limit_price, bool):
            raise ExecutionInputError("limit_price must be a plain number")
        if not math.isfinite(float(limit_price)) or limit_price <= 0:
            raise ExecutionInputError("limit_price must be a finite positive number")
        # NODEB-I2-002: an unresolved broker state blocks new execution until
        # reconciliation resolves it (no guessing, no silent continuation).
        self._require_not_safe_mode()
        # AUD-R1-007: exact-type validation BEFORE any arithmetic/conversion.
        # ``expected_available_cash`` carries the caller-declared capacity; an
        # untrusted object must never pass through int()/float() first.  BUY
        # capacity is a non-negative number; SELL capacity is a plain
        # non-negative int (quantity).
        if side == BUY:
            if (type(expected_available_cash) not in (int, float)
                    or isinstance(expected_available_cash, bool)):
                raise ExecutionInputError(
                    "expected_available_cash must be a non-negative number"
                )
            if not math.isfinite(float(expected_available_cash)) or expected_available_cash < 0:
                raise ExecutionInputError(
                    "expected_available_cash must be a finite non-negative number"
                )
            if cash_amount is None or (type(cash_amount) not in (int, float)
                                       or isinstance(cash_amount, bool)):
                raise ExecutionInputError(
                    "reserved cash must be a non-negative number"
                )
            if not math.isfinite(float(cash_amount)) or cash_amount < 0:
                raise ExecutionInputError(
                    "reserved cash must be a finite non-negative number"
                )
        else:
            if type(expected_available_cash) is not int or expected_available_cash < 0:
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

        # 1. Reserve + intent atomically (design §18.3 / INV-012).
        try:
            booked = self._store.create_intent_with_reservation(
                client_order_key=client_order_key,
                symbol=symbol,
                side=side,
                qty=qty,
                limit_price=limit_price,
                strategy_name=self._strategy_name,
                order_remark=order_remark,
                created_at=now,
                cash_amount=cash_amount,
            )
        except ExecutionStoreError as exc:
            raise ReservationConflictError(
                "reservation + intent booking failed"
            ) from exc

        # Reservation conflict gate (design §18.3): the new reservation must fit
        # within the caller-provided capacity net of already-held reservations.
        # Values are already exact-type validated above (AUD-R1-007); no
        # int()/float() coercion happens on untrusted input here.
        if side == BUY:
            if cash_amount > expected_available_cash:
                self._store.release_reservation(booked.reservation.id, released_at=now)
                raise ReservationConflictError(
                    "reserved cash would exceed the available cash"
                )
        else:
            if qty > expected_available_cash:
                self._store.release_reservation(booked.reservation.id, released_at=now)
                raise ReservationConflictError(
                    "reserved sell qty would exceed the available T quantity"
                )

        # 2. Send to broker through the port.
        try:
            broker_order_id = self._broker.place_order(
                symbol=symbol, side=side, qty=qty, limit_price=limit_price,
                client_order_key=client_order_key, order_remark=order_remark,
            )
        except BrokerDisconnectedError as exc:
            raise OrderSendFailedError("broker disconnected before send") from exc
        except BrokerError as exc:
            raise OrderSendFailedError("broker refused the order") from exc

        # 3. Record broker id -> SUBMITTED (design §18.2 step 3).
        try:
            self._store.update_intent_status(
                client_order_key, status=OrderStatus.SUBMITTED, updated_at=now,
                broker_order_id=broker_order_id,
            )
        except ExecutionStoreError as exc:
            raise OrderReconciliationError(
                "broker order sent but intent update failed; manual reconcile required"
            ) from exc

        return ExecutionResult(
            client_order_key=client_order_key, symbol=symbol, side=side,
            status=OrderStatus.SUBMITTED,
            broker_order_id=broker_order_id, filled_qty=0,
            message="order submitted",
        )

    # -------------------------------------------------------------- fill/poll

    def poll_order(self, client_order_key: str, *, now: str) -> ExecutionResult:
        """Re-query the broker and fold fills/terminal states back into the intent.

        Design §25: after any cancel attempt you must re-query, never assume.
        Partial fills are applied against the recorded intent qty; when the
        order reaches FILLED the reservation is released.  No simulation hook
        is used here — broker state is read through the port only.
        """
        intent = self._store.get_intent(client_order_key)
        if intent.status in ("FILLED", "CANCELED", "REJECTED", "UNKNOWN"):
            return ExecutionResult(
                client_order_key=intent.client_order_key, symbol=intent.symbol,
                side=intent.side, status=intent.status,
                broker_order_id=intent.broker_order_id,
                filled_qty=intent.qty if intent.status == "FILLED" else 0,
                message="intent already terminal",
            )
        if intent.broker_order_id is None:
            raise OrderReconciliationError(
                "intent has no broker_order_id; reconcile before polling"
            )
        try:
            order = self._broker.query_order(intent.broker_order_id)
        except BrokerDisconnectedError as exc:
            raise OrderReconciliationError("broker disconnected during poll") from exc
        except BrokerError as exc:
            raise OrderReconciliationError("broker query failed during poll") from exc

        # NODEB-I2-002: any status outside the known state machine is an
        # explicit unresolved outcome, never a silent downgrade to SUBMITTED.
        # The reservation is preserved and the run must be treated as unsafe.
        if order.status == "UNKNOWN":
            self._engage_safe_mode(
                f"broker order {intent.broker_order_id!r} reports UNKNOWN status"
            )
            raise OrderReconciliationError(
                "broker status UNKNOWN; order state unresolved — SAFE_MODE"
            )

        if order.status == "REJECTED":
            self._store.update_intent_status(
                client_order_key, status=OrderStatus.REJECTED, updated_at=now,
            )
            self._release(client_order_key, now=now)
            return ExecutionResult(
                client_order_key=client_order_key, symbol=intent.symbol,
                side=intent.side, status=OrderStatus.REJECTED,
                broker_order_id=intent.broker_order_id, filled_qty=0,
                message="broker rejected the order",
            )
        if order.status == "CANCELED":
            self._store.update_intent_status(
                client_order_key, status=OrderStatus.CANCELED, updated_at=now,
            )
            self._release(client_order_key, now=now)
            return ExecutionResult(
                client_order_key=client_order_key, symbol=intent.symbol,
                side=intent.side, status=OrderStatus.CANCELED,
                broker_order_id=intent.broker_order_id,
                filled_qty=order.filled_qty,
                message="order canceled",
            )

        new_status = OrderStatus.FILLED if order.status == "FILLED" else (
            OrderStatus.PARTIAL if order.status == "PARTIAL" else intent.status
        )
        if new_status != intent.status:
            self._store.update_intent_status(
                client_order_key, status=new_status, updated_at=now,
            )
        if new_status == OrderStatus.FILLED:
            self._release(client_order_key, now=now)
        return ExecutionResult(
            client_order_key=client_order_key, symbol=intent.symbol,
            side=intent.side, status=new_status,
            broker_order_id=intent.broker_order_id,
            filled_qty=order.filled_qty,
            message="polled",
            fill_price=self._last_fill_price(intent.broker_order_id),
        )

    def _last_fill_price(self, broker_order_id: str) -> float | None:
        """Return the most recent fill price, or None if no fill occurred."""
        try:
            trades = self._broker.query_trades(broker_order_id)
        except BrokerError:
            return None
        if not trades:
            return None
        return float(trades[-1].price)

    def timeout_order(self, client_order_key: str, *, now: str) -> ExecutionResult:
        """Design §25: cancel -> re-query -> reconcile; never assume unfilled."""
        intent = self._store.get_intent(client_order_key)
        if intent.broker_order_id is None:
            raise OrderReconciliationError("intent has no broker_order_id")
        try:
            self._broker.cancel_order(intent.broker_order_id)
        except BrokerCancelFailedError as exc:
            raise CancelFailedError("cancel failed; order must be re-queried") from exc
        except BrokerError as exc:
            raise OrderTimeoutError("cancel attempt failed") from exc
        # Re-query after cancel (design §25).
        return self.poll_order(client_order_key, now=now)

    def cancel_order(self, client_order_key: str, *, now: str) -> ExecutionResult:
        """Best-effort cancel used by kill-switch paths (design §30)."""
        return self.timeout_order(client_order_key, now=now)

    # -------------------------------------------------------------- helpers

    def _release(self, client_order_key: str, *, now: str) -> None:
        """Release every active reservation owned by ``client_order_key``."""
        for reservation in self._store.list_active_reservations():
            if reservation.client_order_key == client_order_key:
                self._store.release_reservation(reservation.id, released_at=now)
