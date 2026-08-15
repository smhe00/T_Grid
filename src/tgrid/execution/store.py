"""Durable OrderIntent + Reservation store (Gate 4, offline, design §18.2/§18.3).

All writes go through the fail-closed :class:`ExecutionStore`, which requires an
initialized ``sqlite3.Connection`` and never creates/updates intents or
reservations outside a transaction.  The atomic :meth:`create_intent_with_reservation`
books the reservation in the SAME transaction as the READY_TO_SEND intent
(design §18.3: intent + reservation must be one atomic semantic), so a crash
can never leave a reservation without its intent or an intent without its
reservation.

Failures raise :class:`ExecutionStoreError` subclasses; no SQL, parameter
values or underlying exception graph is ever embedded in project messages.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from tgrid.execution.models import (
    BUY,
    SELL,
    OrderIntent,
    OrderStatus,
    Reservation,
)
from tgrid.risk.exceptions import PersistenceError


class ExecutionStoreError(PersistenceError):
    """Base class for OrderIntent/Reservation store failures."""


class IntentAlreadyExistsError(ExecutionStoreError):
    """A client_order_key is already recorded (idempotency contract, INV-013)."""


class IntentNotFoundError(ExecutionStoreError):
    """The referenced client_order_key does not exist."""


class ReservationConflictError(ExecutionStoreError):
    """The reservation cannot be booked (duplicate id or capacity violation)."""


class StoreWriteFailedError(ExecutionStoreError):
    """The intent/reservation write failed and was rolled back."""


@dataclass(frozen=True)
class IntentWithReservation:
    """Atomic result of booking an intent and its reservation together."""

    intent: OrderIntent
    reservation: Reservation


def _require_exact_str(value, name: str) -> str:
    if type(value) is not str or value == "":
        raise ExecutionStoreError(f"{name} must be a non-empty string")
    return value


class ExecutionStore:
    """Fail-closed store over an initialized connection.

    The connection must have no active transaction when entering the store (the
    store manages its own transactions and never commits/rolls back a caller
    transaction).  Reads are plain queries; writes are transactional.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        if not isinstance(conn, sqlite3.Connection):
            raise ExecutionStoreError("conn must be a sqlite3.Connection")
        self._conn = conn

    # ------------------------------------------------------------- intents

    def create_intent_with_reservation(
        self,
        *,
        client_order_key: str,
        symbol: str,
        side: str,
        qty: int,
        limit_price: float,
        strategy_name: str,
        order_remark: str,
        created_at: str,
        cash_amount: float | None = None,
        reservation_id: str = "",
    ) -> IntentWithReservation:
        """Atomically insert a READY_TO_SEND intent + its reservation.

        SELL intents reserve ``qty`` (ReservedSellQty); BUY intents reserve
        ``cash_amount`` (ReservedCash).  ``reservation_id`` defaults to the
        intent key when not supplied.  Any failure rolls the whole transaction
        back; a duplicate client_order_key is a hard idempotency error.
        """
        _require_exact_str(client_order_key, "client_order_key")
        _require_exact_str(symbol, "symbol")
        _require_exact_str(strategy_name, "strategy_name")
        _require_exact_str(order_remark, "order_remark")
        _require_exact_str(created_at, "created_at")
        if side not in (BUY, SELL):
            raise ExecutionStoreError("side must be BUY or SELL")
        if type(qty) is not int or qty <= 0:
            raise ExecutionStoreError("qty must be a positive plain int")
        if type(limit_price) not in (int, float) or isinstance(limit_price, bool) or limit_price <= 0:
            raise ExecutionStoreError("limit_price must be a positive number")
        if side == BUY:
            if type(cash_amount) not in (int, float) or isinstance(cash_amount, bool) or cash_amount < 0:
                raise ExecutionStoreError("BUY reservation requires a non-negative cash_amount")
        else:
            if cash_amount is not None:
                raise ExecutionStoreError("SELL reservation must not carry cash_amount")
        reservation_id = reservation_id or client_order_key

        if self._conn.in_transaction:
            raise ExecutionStoreError(
                "store requires a connection with no active transaction"
            )
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "INSERT INTO order_intents (client_order_key, symbol, side,"
                    " qty, limit_price, status, strategy_name, order_remark,"
                    " broker_order_id, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                    (
                        client_order_key, symbol, side, qty, limit_price,
                        OrderStatus.NEW, strategy_name, order_remark,
                        created_at, created_at,
                    ),
                )
                self._conn.execute(
                    "INSERT INTO order_reservations (id, symbol, side, qty,"
                    " cash_amount, client_order_key, created_at, released_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                    (
                        reservation_id, symbol, side, qty, cash_amount,
                        client_order_key, created_at,
                    ),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                try:
                    self._conn.execute("ROLLBACK")
                except BaseException:
                    self._conn.close()
                raise
        except sqlite3.IntegrityError as exc:
            raise IntentAlreadyExistsError(
                "client_order_key already exists; refusing to duplicate an intent"
            ) from exc
        except ExecutionStoreError:
            raise
        except sqlite3.Error as exc:
            raise StoreWriteFailedError("intent/reservation write failed") from exc

        intent = self.get_intent(client_order_key)
        reservation = self.get_reservation(reservation_id)
        return IntentWithReservation(intent=intent, reservation=reservation)

    def get_intent(self, client_order_key: str) -> OrderIntent:
        _require_exact_str(client_order_key, "client_order_key")
        try:
            row = self._conn.execute(
                "SELECT client_order_key, symbol, side, qty, limit_price,"
                " strategy_name, order_remark, status, broker_order_id,"
                " created_at, updated_at FROM order_intents"
                " WHERE client_order_key = ?",
                (client_order_key,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StoreWriteFailedError("intent read failed") from exc
        if row is None:
            raise IntentNotFoundError("no order intent with this client_order_key")
        return OrderIntent(
            client_order_key=row[0], symbol=row[1], side=row[2], qty=row[3],
            limit_price=row[4], strategy_name=row[5], order_remark=row[6],
            status=row[7], broker_order_id=row[8], created_at=row[9],
            updated_at=row[10],
        )

    def list_intents(self, *, status: str | None = None) -> tuple:
        """All intents (optionally filtered by exact status), newest last."""
        if status is not None:
            _require_exact_str(status, "status")
            rows = self._conn.execute(
                "SELECT client_order_key, symbol, side, qty, limit_price,"
                " strategy_name, order_remark, status, broker_order_id,"
                " created_at, updated_at FROM order_intents"
                " WHERE status = ? ORDER BY created_at",
                (status,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT client_order_key, symbol, side, qty, limit_price,"
                " strategy_name, order_remark, status, broker_order_id,"
                " created_at, updated_at FROM order_intents"
                " ORDER BY created_at",
            ).fetchall()
        return tuple(
            OrderIntent(
                client_order_key=r[0], symbol=r[1], side=r[2], qty=r[3],
                limit_price=r[4], strategy_name=r[5], order_remark=r[6],
                status=r[7], broker_order_id=r[8], created_at=r[9],
                updated_at=r[10],
            )
            for r in rows
        )

    def update_intent_status(
        self, client_order_key: str, *, status: str, updated_at: str,
        broker_order_id: str | None = None,
    ) -> OrderIntent:
        """Transition one intent to ``status`` (fail closed on unknown status)."""
        _require_exact_str(client_order_key, "client_order_key")
        _require_exact_str(status, "status")
        _require_exact_str(updated_at, "updated_at")
        if broker_order_id is not None and type(broker_order_id) is not str:
            raise ExecutionStoreError("broker_order_id must be a string or None")
        current = self.get_intent(client_order_key)
        if current.status in ("FILLED", "CANCELED", "REJECTED", "UNKNOWN"):
            raise ExecutionStoreError(
                f"cannot transition terminal intent {current.status!r}"
            )
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "UPDATE order_intents SET status = ?, updated_at = ?,"
                    " broker_order_id = COALESCE(?, broker_order_id)"
                    " WHERE client_order_key = ?",
                    (status, updated_at, broker_order_id, client_order_key),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                try:
                    self._conn.execute("ROLLBACK")
                except BaseException:
                    self._conn.close()
                raise
        except ExecutionStoreError:
            raise
        except sqlite3.Error as exc:
            raise StoreWriteFailedError("intent status update failed") from exc
        return self.get_intent(client_order_key)

    # --------------------------------------------------------- reservations

    def get_reservation(self, reservation_id: str) -> Reservation:
        _require_exact_str(reservation_id, "reservation_id")
        try:
            row = self._conn.execute(
                "SELECT id, symbol, side, qty, cash_amount, client_order_key,"
                " created_at, released_at FROM order_reservations"
                " WHERE id = ?",
                (reservation_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StoreWriteFailedError("reservation read failed") from exc
        if row is None:
            raise ExecutionStoreError("no reservation with this id")
        return Reservation(
            id=row[0], symbol=row[1], side=row[2], qty=row[3],
            cash_amount=row[4], client_order_key=row[5], created_at=row[6],
            released_at=row[7],
        )

    def list_active_reservations(self, *, symbol: str | None = None) -> tuple:
        """Active (unreleased) reservations, oldest first."""
        if symbol is None:
            rows = self._conn.execute(
                "SELECT id, symbol, side, qty, cash_amount, client_order_key,"
                " created_at, released_at FROM order_reservations"
                " WHERE released_at IS NULL ORDER BY created_at",
            ).fetchall()
        else:
            _require_exact_str(symbol, "symbol")
            rows = self._conn.execute(
                "SELECT id, symbol, side, qty, cash_amount, client_order_key,"
                " created_at, released_at FROM order_reservations"
                " WHERE released_at IS NULL AND symbol = ? ORDER BY created_at",
                (symbol,),
            ).fetchall()
        return tuple(
            Reservation(
                id=r[0], symbol=r[1], side=r[2], qty=r[3], cash_amount=r[4],
                client_order_key=r[5], created_at=r[6], released_at=r[7],
            )
            for r in rows
        )

    def release_reservation(self, reservation_id: str, *, released_at: str) -> Reservation:
        """Release one reservation (idempotent: already-released is a no-op)."""
        _require_exact_str(reservation_id, "reservation_id")
        _require_exact_str(released_at, "released_at")
        current = self.get_reservation(reservation_id)
        if current.released_at is not None:
            return current
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "UPDATE order_reservations SET released_at = ? WHERE id = ?",
                    (released_at, reservation_id),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                try:
                    self._conn.execute("ROLLBACK")
                except BaseException:
                    self._conn.close()
                raise
        except sqlite3.Error as exc:
            raise StoreWriteFailedError("reservation release failed") from exc
        return self.get_reservation(reservation_id)

    def reserved_sell_qty(self, symbol: str) -> int:
        """Active ReservedSellQty for ``symbol`` (design §18.3)."""
        _require_exact_str(symbol, "symbol")
        row = self._conn.execute(
            "SELECT COALESCE(SUM(qty), 0) FROM order_reservations"
            " WHERE released_at IS NULL AND side = ? AND symbol = ?",
            (SELL, symbol),
        ).fetchone()
        return int(row[0])

    def reserved_cash(self, symbol: str) -> float:
        """Active ReservedCash for ``symbol`` (design §18.3)."""
        _require_exact_str(symbol, "symbol")
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cash_amount), 0) FROM order_reservations"
            " WHERE released_at IS NULL AND side = ? AND symbol = ?",
            (BUY, symbol),
        ).fetchone()
        return float(row[0])
