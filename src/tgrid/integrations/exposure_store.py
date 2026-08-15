"""Concrete durable SQLite exposure store (NODEB-RR-004).

The daily-exposure ledger needs a PRODUCTION-proven persistence boundary, not
an abstract convention.  :class:`SqliteExposureStore` is the audited concrete
implementation: a single ``daily_exposure`` table (``trade_date`` primary key,
``buy_notional`` REAL) created idempotently over an injected
``sqlite3.Connection``, with exact-type validated ``get``/``set``.

Production wiring must construct this store itself (never accept an in-memory
fake on the real path); callers cannot substitute a fake store where the
bootstrap builds the durable journal (RR-004).
"""

from __future__ import annotations

import math
import sqlite3

from tgrid.integrations.daily_exposure import ExposureValueError
from tgrid.risk.exceptions import PersistenceError


class SqliteExposureStore:
    """Durable get/set exposure surface backed by SQLite.

    ``conn`` must be an initialized ``sqlite3.Connection``; the table is
    created idempotently on construction.  Values are validated as finite
    non-negative numbers before any write (fail closed).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        if not isinstance(conn, sqlite3.Connection):
            raise PersistenceError("exposure store requires a sqlite3.Connection")
        self._conn = conn
        try:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS daily_exposure ("
                " trade_date TEXT PRIMARY KEY,"
                " buy_notional REAL NOT NULL"
                ")"
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise PersistenceError("exposure table creation failed") from exc

    def get(self, trade_date: str):
        if type(trade_date) is not str or trade_date == "":
            raise ExposureValueError("trade_date must be a non-empty string")
        try:
            row = self._conn.execute(
                "SELECT buy_notional FROM daily_exposure WHERE trade_date = ?",
                (trade_date,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError("exposure read failed") from exc
        if row is None:
            return None
        value = float(row[0])
        if not math.isfinite(value) or value < 0:
            raise ExposureValueError("persisted exposure must be finite and non-negative")
        return value

    def set(self, trade_date: str, notional: float) -> None:
        if type(trade_date) is not str or trade_date == "":
            raise ExposureValueError("trade_date must be a non-empty string")
        if type(notional) not in (int, float) or isinstance(notional, bool):
            raise ExposureValueError("notional must be a number")
        if not math.isfinite(float(notional)) or notional < 0:
            raise ExposureValueError("notional must be a finite non-negative number")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "INSERT INTO daily_exposure (trade_date, buy_notional)"
                    " VALUES (?, ?)"
                    " ON CONFLICT(trade_date) DO UPDATE SET buy_notional = excluded.buy_notional",
                    (trade_date, float(notional)),
                )
                self._conn.commit()
            except BaseException:
                try:
                    self._conn.execute("ROLLBACK")
                except BaseException:
                    self._conn.close()
                raise
        except sqlite3.Error as exc:
            raise PersistenceError("exposure write failed") from exc
