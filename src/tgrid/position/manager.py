"""Immutable Core Position snapshot and sell guard (Gate 2, offline).

Implements the design decomposition ``Broker = Core + StrategicExtra + OpenTLot``
(design §5) and the dual sell protections (design §4, INV-001, INV-005, §50):

    AvailableTQty = min(CanUseVolume, OpenTLotPosition) - ReservedSellQty

The T module may only ever sell the open T-lot position: Strategic Extra and
Core lots are off-limits to automatic T exits (design §17, INV-008).  The
protected floor for a T sell is therefore ``Core + StrategicExtra``.

Everything is immutable and fail-closed: a snapshot whose fields are internally
inconsistent, or a sell whose quantity is not a plain positive int, raises an
explicit project exception.  No quantity is ever reclassified, guessed, or
silently repaired.  No Python ``assert`` is used for safety (INV-011).
"""

from __future__ import annotations

from dataclasses import dataclass

from tgrid.models import SymbolConfig
from tgrid.risk.exceptions import (
    CoreFloorViolation,
    InsufficientAvailableVolume,
    PositionInvariantError,
    SellReservationConflict,
)


def _require_plain_nonneg_int(value: object, name: str) -> int:
    # Plain int exactly: bool/float/str/int-subclasses are rejected.  No
    # str()/repr()/conversion is invoked on the rejected object, so a malicious
    # int subclass can never execute custom methods (INV-011, fail-closed).
    if type(value) is not int or value < 0:
        raise PositionInvariantError(f"{name} must be a plain non-negative int")
    return value


def _require_plain_symbol(value: object) -> str:
    # Plain str exactly; a whitespace-only string is rejected without being
    # accepted via any implicit trim/normalize.
    if type(value) is not str or not value.strip():
        raise PositionInvariantError("symbol must be a non-empty plain string")
    return value


@dataclass(frozen=True)
class PositionSnapshot:
    """Immutable snapshot of one symbol's Broker/Core/Strategic/T-Lot position.

    ``open_t_lot_position`` is the total open T-lot quantity in shares (design
    ``OpenTLotPosition``); the T module may only ever sell within it.

    Construction enforces the exact decomposition equality and rejects a
    negative available T quantity (reserved exceeding capacity).  No field can
    be mutated after construction.
    """

    symbol: str
    broker_position: int
    core_position: int
    strategic_extra: int
    open_t_lot_position: int
    can_use_qty: int
    reserved_sell_qty: int

    def __post_init__(self) -> None:
        symbol = _require_plain_symbol(self.symbol)
        object.__setattr__(self, "symbol", symbol)
        _require_plain_nonneg_int(self.broker_position, "broker_position")
        _require_plain_nonneg_int(self.core_position, "core_position")
        _require_plain_nonneg_int(self.strategic_extra, "strategic_extra")
        _require_plain_nonneg_int(self.open_t_lot_position, "open_t_lot_position")
        _require_plain_nonneg_int(self.can_use_qty, "can_use_qty")
        _require_plain_nonneg_int(self.reserved_sell_qty, "reserved_sell_qty")
        # Highest-priority safety first (INV-001, §50): a broker position below
        # the core floor is always a CoreFloorViolation.
        if self.broker_position < self.core_position:
            raise CoreFloorViolation(
                "broker position is below the core floor"
            )
        # Broker authority: Broker must equal Core + StrategicExtra + OpenTLot
        # (design §5).  No silent repair or reclassification.
        total = (
            self.core_position
            + self.strategic_extra
            + self.open_t_lot_position
        )
        if self.broker_position != total:
            raise PositionInvariantError(
                "broker position must equal core + strategic extra + open t lots"
            )
        # AvailableTQty = min(can_use, open_t_lot_position) - reserved must not
        # be negative (INV-005); a reservation exceeding capacity is corrupt.
        if self.reserved_sell_qty > min(
            self.can_use_qty, self.open_t_lot_position
        ):
            raise PositionInvariantError(
                "reserved sell qty exceeds the available T capacity"
            )

    def protected_floor(self) -> int:
        """T-module protected floor: Core + StrategicExtra (design §17, INV-008)."""
        return self.core_position + self.strategic_extra

    def available_headroom(self) -> int:
        """``Position - CoreQty`` (core-only headroom, informational)."""
        return self.broker_position - self.core_position

    @property
    def available_t_qty(self) -> int:
        """Design formula: min(CanUse, OpenTLotPosition) - ReservedSellQty.

        The T module may only sell open T-lot shares; Core/Strategic are never
        auto-sellable, so the headroom term is exactly the open T-lot position
        (REV-G2T001-001).
        """
        return min(
            self.can_use_qty, self.open_t_lot_position
        ) - self.reserved_sell_qty


def snapshot_from_symbol_config(
    symbol_config: object,
    *,
    symbol: str,
    broker_position: object,
    strategic_extra: object,
    open_t_lot_position: object,
    can_use_qty: object,
    reserved_sell_qty: object,
) -> PositionSnapshot:
    """Build a PositionSnapshot whose core comes only from ``SymbolConfig.core_qty``.

    Reuses ``SymbolConfig`` (REV-G2T001-002): the caller supplies the live
    broker/strategic/T-lot fields and the snapshot's ``core_position`` is taken
    verbatim from ``symbol_config.core_qty``.  There is no second core input and
    no configuration copy; ``symbol_config`` is validated as the exact
    ``SymbolConfig`` type and left frozen.
    """
    if type(symbol_config) is not SymbolConfig:
        raise PositionInvariantError(
            "symbol_config must be a SymbolConfig"
        )
    symbol_value = _require_plain_symbol(symbol)
    core = _require_plain_nonneg_int(symbol_config.core_qty, "core_qty")
    return PositionSnapshot(
        symbol=symbol_value,
        broker_position=broker_position,
        core_position=core,
        strategic_extra=strategic_extra,
        open_t_lot_position=open_t_lot_position,
        can_use_qty=can_use_qty,
        reserved_sell_qty=reserved_sell_qty,
    )


class CorePositionGuard:
    """Highest-priority sell protection for the T module (design §50).

    ``validate_t_sell`` is the explicit T-module sell check.  It applies three
    independent, mutually-exclusive boundary checks in strict priority order:

    1. Protected floor (Core + StrategicExtra; design §17, INV-008)
    2. QMT available volume (can_use_qty)
    3. Sell reservation conflict (reserved_sell_qty)
    """

    @staticmethod
    def validate_t_sell(
        snapshot: PositionSnapshot, sell_qty: object
    ) -> None:
        """Validate a T-module sell of ``sell_qty`` shares against ``snapshot``.

        Raises ``PositionInvariantError`` for an invalid sell quantity, then
        ``CoreFloorViolation``, ``InsufficientAvailableVolume`` or
        ``SellReservationConflict`` in that priority.  On failure the snapshot
        is never modified.
        """
        if type(snapshot) is not PositionSnapshot:
            raise PositionInvariantError(
                "snapshot must be a PositionSnapshot"
            )
        qty = _require_plain_nonneg_int(sell_qty, "sell_qty")
        if qty == 0:
            raise PositionInvariantError(
                "sell_qty must be a positive plain int"
            )
        # 1. Protected floor: selling must never cross into Core/Strategic lots.
        if qty > snapshot.open_t_lot_position:
            raise CoreFloorViolation(
                "sell would exceed the open T-lot position "
                "(Core/Strategic lots are protected)"
            )
        # 2. QMT available volume.
        if qty > snapshot.can_use_qty:
            raise InsufficientAvailableVolume(
                "sell exceeds the QMT available volume"
            )
        # 3. Reservation conflict: sell must not exceed the un-reserved T qty.
        if qty > snapshot.available_t_qty:
            raise SellReservationConflict(
                "sell conflicts with quantity already reserved"
            )
