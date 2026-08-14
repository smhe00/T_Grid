"""Offline, fail-closed position reconciliation decision engine (G2-T006).

Compares an externally supplied broker position against the local expected
decomposition for one symbol and returns an immutable reconciliation decision.
Any unexplained mismatch results in ``SAFE_MODE``; a delta is never guessed to
be Strategic, T-Lot, or a manual trade.  This is a pure decision primitive: it
does not connect to QMT, query SQLite, persist SAFE_MODE, or run startup
orchestration.

The core quantity is single-authority from ``SymbolConfig.core_qty``; there is
no alternate caller-supplied core value.

Decision priority:

1. Invalid/untrusted inputs -> ``PositionInvariantError`` (fail closed, no result).
2. ``broker_position < core_qty`` -> ``SAFE_MODE / CORE_FLOOR_BREACH``.
3. Else ``broker_position != LocalExpectedPosition`` -> ``SAFE_MODE / BROKER_POSITION_MISMATCH``.
4. Else -> ``RECONCILED / MATCH``.

``LocalExpectedPosition = core_qty + strategic_extra + open_t_lot_position``.
"""

from __future__ import annotations

from dataclasses import dataclass

from tgrid.models import SymbolConfig
from tgrid.risk.exceptions import PositionInvariantError

RECONCILED = "RECONCILED"
SAFE_MODE = "SAFE_MODE"
REASON_MATCH = "MATCH"
REASON_CORE_FLOOR_BREACH = "CORE_FLOOR_BREACH"
REASON_BROKER_POSITION_MISMATCH = "BROKER_POSITION_MISMATCH"


@dataclass(frozen=True)
class PositionReconciliationResult:
    """Frozen, data-only reconciliation decision.

    Contains no callable, connection, cursor, client, or external capability.
    """

    symbol: str
    decision: str
    reason: str
    broker_position: int
    local_expected_position: int
    delta: int
    core_qty: int
    strategic_extra: int
    open_t_lot_position: int


def _require_symbol_config(value) -> None:
    # Exact type only: a fake or subclass object is rejected before any
    # attribute is read, so its dunders are never invoked.
    if type(value) is not SymbolConfig:
        raise PositionInvariantError(
            "symbol_config must be an exact SymbolConfig instance"
        )


def _require_exact_nonempty_str(value, name: str) -> None:
    if type(value) is not str or value.strip() == "":
        raise PositionInvariantError(f"{name} must be a non-empty string")


def _require_nonneg_int(value, name: str) -> int:
    # Exact plain int: bool, float, str, bytes, containers, int subclasses and
    # arbitrary objects are rejected without invoking str/repr/bool/iter/
    # __eq__/__int__/__index__.
    if type(value) is not int or value < 0:
        raise PositionInvariantError(f"{name} must be a plain non-negative integer")
    return value


def reconcile_position(
    symbol_config,
    *,
    symbol,
    broker_position,
    strategic_extra,
    open_t_lot_position,
) -> PositionReconciliationResult:
    """Reconcile the broker position against the local expected position."""
    _require_symbol_config(symbol_config)
    _require_exact_nonempty_str(symbol, "symbol")
    core_qty = _require_nonneg_int(symbol_config.core_qty, "core_qty")
    broker = _require_nonneg_int(broker_position, "broker_position")
    strategic = _require_nonneg_int(strategic_extra, "strategic_extra")
    open_t = _require_nonneg_int(open_t_lot_position, "open_t_lot_position")

    local_expected = core_qty + strategic + open_t
    delta = broker - local_expected

    if broker < core_qty:
        decision = SAFE_MODE
        reason = REASON_CORE_FLOOR_BREACH
    elif delta != 0:
        decision = SAFE_MODE
        reason = REASON_BROKER_POSITION_MISMATCH
    else:
        decision = RECONCILED
        reason = REASON_MATCH

    return PositionReconciliationResult(
        symbol=symbol,
        decision=decision,
        reason=reason,
        broker_position=broker,
        local_expected_position=local_expected,
        delta=delta,
        core_qty=core_qty,
        strategic_extra=strategic,
        open_t_lot_position=open_t,
    )
