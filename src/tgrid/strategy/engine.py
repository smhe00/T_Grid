"""Offline ACCUMULATE strategy engine (Gate 3, design §12–§16, §31).

The engine consumes a frozen daily basis (anchor / ATR / grid), then processes
5-minute bars one at a time and returns data-only decisions: ``BUY_T``,
``SELL_T`` (LIFO), rejections, or halts.  It never places an order; the caller
(Gate 4 execution layer) decides how to act on a decision and confirms fills
via :meth:`record_buy_fill` / :meth:`record_sell_fill`.

New-T-lot gates (design §13, INV-002/003/004/010):

* strategy enabled, mode ACCUMULATE
* no pending order in this direction (INV-004)
* not EVENT_BLOCK / VOLATILITY_HALT / DATA_HALT
* open lots < max_t_lots (INV-002)
* position + t_unit <= target_qty (INV-003)
* cash: t_unit * price <= available_cash - minimum_cash_buffer
* price <= BuyLevel_n with n = open_lots + 1

Exit gates (design §15): a lot is a SELL candidate when
``price >= Target_i = Entry_i * (1 + G * ExitMultiplier)``; LIFO picks the
newest qualifying lot; then Core Floor / Available Volume / Reservation /
pending-order checks all run through the Gate 2 guard
(:class:`~tgrid.position.CorePositionGuard`) before ``SELL_T`` is emitted.

Volatility halt (§28), event block (§29), data quality (§26.2) and the
time-window filter (§27) block new T-lots but never auto-close an existing lot
(INV-007: no price stop-loss; exits stay governed by the exit target only).

The engine is single-threaded by design (§3.1) and holds no QMT, DB, or order
surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from tgrid.models import ACCUMULATE_MODE, GlobalConfig, SymbolConfig
from tgrid.position import CorePositionGuard, snapshot_from_symbol_config
from tgrid.risk.exceptions import (
    CoreFloorViolation,
    InsufficientAvailableVolume,
    PositionInvariantError,
    SellReservationConflict,
)
from tgrid.strategy.bars import Bar, SessionWindow
from tgrid.strategy.basis_transform import to_raw_domain
from tgrid.strategy.exceptions import StrategyError, StrategyInputError
from tgrid.strategy.grid import buy_level, exit_target_price, grid_pct, legalize_price
from tgrid.strategy.halts import (
    EventBlockRule,
    daily_move_halted,
    event_blocked,
    gap_halted,
)
from tgrid.strategy.indicators import atr14, atr_pct, ema20, vwap20
from tgrid.strategy.quality import BarQualityIssue, DataQualityGuard


class _DecisionKind:
    BUY_T = "BUY_T"
    SELL_T = "SELL_T"
    NO_ACTION = "NO_ACTION"
    BUY_REJECTED = "BUY_REJECTED"
    SELL_REJECTED = "SELL_REJECTED"
    HALTED = "HALTED"


DecisionKind = _DecisionKind()


class _State:
    IDLE = "IDLE"
    BUY_TRIGGER = "BUY_TRIGGER"
    BUY_PENDING = "BUY_PENDING"
    OPEN = "OPEN"
    SELL_TRIGGER = "SELL_TRIGGER"
    SELL_PENDING = "SELL_PENDING"
    CLOSED = "CLOSED"
    EVENT_BLOCK = "EVENT_BLOCK"
    VOLATILITY_HALT = "VOLATILITY_HALT"
    DATA_HALT = "DATA_HALT"
    T_CAPACITY_FULL = "T_CAPACITY_FULL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


State = _State()


class _Reason:
    # buys
    NOT_ENABLED = "STRATEGY_DISABLED"
    WRONG_MODE = "MODE_NOT_ACCUMULATE"
    PENDING_ORDER = "PENDING_ORDER"
    EVENT_BLOCK = "EVENT_BLOCK"
    VOLATILITY_HALT = "VOLATILITY_HALT"
    DATA_HALT = "DATA_HALT"
    T_CAPACITY_FULL = "T_CAPACITY_FULL"
    TARGET_CEILING = "TARGET_CEILING"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    PRICE_ABOVE_BUY_LEVEL = "PRICE_ABOVE_BUY_LEVEL"
    TIME_WINDOW = "TIME_WINDOW"
    # sells
    NO_SELL_CANDIDATE = "NO_SELL_CANDIDATE"
    TARGET_NOT_REACHED = "TARGET_NOT_REACHED"
    EXIT_TRIGGERED = "EXIT_TRIGGERED"
    CORE_FLOOR = "CORE_FLOOR"
    INSUFFICIENT_AVAILABLE_VOLUME = "INSUFFICIENT_AVAILABLE_VOLUME"
    SELL_RESERVATION_CONFLICT = "SELL_RESERVATION_CONFLICT"
    POSITION_INVARIANT = "POSITION_INVARIANT"
    # generic
    NO_BASIS = "NO_DAILY_BASIS"
    QUALITY_ISSUES = "QUALITY_ISSUES"
    BUY_TRIGGERED = "BUY_TRIGGERED"


Reason = _Reason()


@dataclass(frozen=True)
class DailyBasis:
    """Frozen daily anchor/volatility/grid values (design §9–§11).

    All *price-like* fields (``anchor``, ``previous_close``) are stored in the
    RAW trading domain after an explicit same-day ADJUSTED->RAW transform
    (NODEA-001), so every subsequent comparison against RAW 5m ``bar.close``
    is dimensionally consistent.  Dimensionless fields (``atr_pct``,
    ``grid_g``) are never transformed.  ``adjusted_to_raw_factor`` records the
    factor used (auditable), or 1.0 when the basis was computed directly from
    RAW data.
    """

    trade_date: str
    anchor: float
    anchor_method: str
    atr14: float
    atr_pct: float
    grid_g: float
    previous_close: float
    adjusted_to_raw_factor: float = 1.0


@dataclass(frozen=True)
class OpenTLotView:
    """Data-only view of one open T-lot (LIFO newest-first ordering implied)."""

    t_lot_id: str
    qty: int
    entry_price: float
    entry_time: str
    target_price: float


@dataclass(frozen=True)
class BarDecision:
    """Data-only decision produced for one 5-minute bar.

    ``kind`` is one of :class:`DecisionKind`; ``reason`` a fixed
    :class:`Reason` constant.  A ``BUY_T`` decision carries the legalized limit
    price and t_unit quantity; a ``SELL_T`` decision carries the LIFO-picked
    lot id, its quantity and its target price.  No callable, connection, or
    external capability is included.
    """

    kind: str
    symbol: str
    bar_time: str
    reason: str
    qty: int = 0
    limit_price: float = 0.0
    t_lot_id: str | None = None
    target_price: float = 0.0


def _require_exact(value, cls, name: str):
    if type(value) is not cls:
        raise StrategyInputError(f"{name} must be an exact {cls.__name__}")
    return value


def _require_nonempty_str(value, name: str) -> str:
    if type(value) is not str or value == "":
        raise StrategyInputError(f"{name} must be a non-empty string")
    return value


def _minute_of_day(iso_time: str) -> int:
    # "YYYY-MM-DDTHH:MM:SS" -> minutes since midnight; fails closed on shape.
    try:
        time_part = iso_time[11:19]
        hours, minutes, _ = (int(p) for p in time_part.split(":"))
        return hours * 60 + minutes
    except Exception:
        raise StrategyInputError("bar time must be ISO-8601 HH:MM:SS") from None


class AccumulateStrategy:
    """Per-symbol ACCUMULATE engine over 5-minute bars (offline).

    Lifecycle: :meth:`begin_day` (freeze daily basis) then any number of
    :meth:`on_bar` calls; fill confirmations via :meth:`record_buy_fill` /
    :meth:`record_sell_fill` keep the simulated open-lot state consistent.
    """

    def __init__(
        self,
        symbol_config: object,
        global_config: object,
        *,
        session_window: object,
        allow_exit_near_close: bool = True,
    ) -> None:
        self._symbol_config = _require_exact(symbol_config, SymbolConfig, "symbol_config")
        self._global_config = _require_exact(global_config, GlobalConfig, "global_config")
        self._session = _require_exact(session_window, SessionWindow, "session_window")
        if type(allow_exit_near_close) is not bool:
            raise StrategyInputError("allow_exit_near_close must be a bool")
        self._allow_exit_near_close = allow_exit_near_close
        self._quality = DataQualityGuard(
            expected_interval_seconds=300,
            max_stale_seconds=600,
            max_gap_multiple=2.0,
            session=self._session,
        )
        self._basis: DailyBasis | None = None
        self._open_lots: list = []  # list of OpenTLotView (LIFO = newest last)
        self._pending_buy = False
        self._pending_sell = False
        self._day_halts: set = set()
        self._lot_seq = 0
        self._last_bar_close: float | None = None

    # ------------------------------------------------------------------ basis

    def begin_day(
        self,
        daily_bars: object,
        *,
        trade_date: str,
        adjusted_to_raw_factor: object = None,
        daily_price_basis: object = None,
    ) -> DailyBasis:
        """Freeze the day's anchor/ATR/grid from daily bars (design §9–§11).

        Anchor = VWAP20, falling back to EMA20 when VWAP20 cannot be computed
        (insufficient bars or zero volume).  ATR14 and ATR% drive the adaptive
        grid G.  ``previous_close`` is the last daily bar's close (volatility
        halt reference, §28).  Returns the frozen :class:`DailyBasis`.

        Basis discipline (NODEA-001): the daily bars are the *indicator*
        history (normally ADJUSTED).  When ``daily_price_basis`` is ADJUSTED,
        an explicit same-day ``adjusted_to_raw_factor`` must be supplied; the
        price-like basis fields (anchor, previous_close) are transformed to the
        RAW trading domain so comparisons against RAW 5m closes are consistent.
        If the factor is missing the engine fails closed rather than guessing.
        """
        _require_nonempty_str(trade_date, "trade_date")
        if daily_bars is None or isinstance(daily_bars, (str, bytes)) or not hasattr(daily_bars, "__len__"):
            raise StrategyInputError("daily_bars must be a sequence of Bar objects")
        bars = list(daily_bars)
        if len(bars) == 0:
            raise StrategyInputError("daily_bars must not be empty")
        for bar in bars:
            _require_exact(bar, Bar, "daily bar")

        basis_label = daily_price_basis if daily_price_basis is not None else "RAW"
        if type(basis_label) is not str or basis_label not in ("RAW", "ADJUSTED"):
            raise StrategyInputError(
                "daily_price_basis must be 'RAW' or 'ADJUSTED'"
            )

        anchor = None
        method = ""
        try:
            anchor = vwap20(bars)
            method = "VWAP20"
        except StrategyError:
            try:
                anchor = ema20([float(b.close) for b in bars])
                method = "EMA20"
            except StrategyError:
                raise StrategyInputError(
                    "daily basis requires >= 20 bars (VWAP20) or >= 20 closes (EMA20)"
                ) from None
        atr = atr14(bars)
        close = float(bars[-1].close)
        atr_pct_value = atr_pct(atr, close)
        g = grid_pct(
            atr_pct_value,
            atr_k=self._symbol_config.atr_k,
            min_grid=self._symbol_config.min_grid,
            max_grid=self._symbol_config.max_grid,
        )

        # NODEA-001: price-like basis values must live in the RAW trading
        # domain.  ADJUSTED indicator history needs an explicit same-day
        # factor; without it we fail closed instead of comparing ADJUSTED
        # values against RAW execution prices.
        factor = 1.0
        if basis_label == "ADJUSTED":
            factor = to_raw_domain_factor(adjusted_to_raw_factor)
            anchor = to_raw_domain(anchor, factor)
            close = to_raw_domain(close, factor)

        self._basis = DailyBasis(
            trade_date=trade_date,
            anchor=anchor,
            anchor_method=method,
            atr14=atr,
            atr_pct=atr_pct_value,
            grid_g=g,
            previous_close=close,
            adjusted_to_raw_factor=factor,
        )
        self._day_halts = set()
        self._quality = DataQualityGuard(
            expected_interval_seconds=300,
            max_stale_seconds=600,
            max_gap_multiple=2.0,
            session=self._session,
        )
        return self._basis

    # ---------------------------------------------------------------- queries

    @property
    def daily_basis(self) -> DailyBasis | None:
        return self._basis

    def open_t_lots(self) -> tuple:
        """Frozen tuple of open T-lot views, newest last (LIFO order)."""
        return tuple(self._open_lots)

    def open_lot_count(self) -> int:
        return len(self._open_lots)

    def state(self) -> str:
        """Current per-symbol state (design §31)."""
        if not self._basis:
            return State.IDLE
        if self._pending_sell:
            return State.SELL_PENDING
        if self._pending_buy:
            return State.BUY_PENDING
        if self._open_lots:
            return State.OPEN
        if Reason.VOLATILITY_HALT in self._day_halts:
            return State.VOLATILITY_HALT
        if Reason.EVENT_BLOCK in self._day_halts:
            return State.EVENT_BLOCK
        if Reason.DATA_HALT in self._day_halts:
            return State.DATA_HALT
        if self.open_lot_count() >= self._symbol_config.max_t_lots:
            return State.T_CAPACITY_FULL
        return State.IDLE

    # -------------------------------------------------------------- decisions

    def on_bar(
        self,
        bar: object,
        *,
        broker_position: object,
        can_use_qty: object,
        strategic_extra: object,
        reserved_sell_qty: object,
        available_cash: object,
        event_rule: object = None,
        now: object = None,
    ) -> BarDecision:
        """Process one 5-minute bar and return a data-only decision.

        Order of evaluation (fail closed at each gate): daily basis present →
        data quality → event block / volatility halt → time window → sell
        candidates (LIFO) → buy trigger.  A rejected/halted decision never
        mutates open lots or pending flags.
        """
        _require_exact(bar, Bar, "bar")
        now_value = _require_nonempty_str(now, "now") if now is not None else bar.time

        if self._basis is None:
            return BarDecision(
                kind=DecisionKind.HALTED,
                symbol=bar.symbol,
                bar_time=bar.time,
                reason=Reason.NO_BASIS,
            )

        # 1. Data quality (§26.2) — bad data is a hard stop: no decision at all.
        issues = self._quality.check(bar, now=now_value)
        if issues:
            self._day_halts.add(Reason.DATA_HALT)
            return BarDecision(
                kind=DecisionKind.HALTED,
                symbol=bar.symbol,
                bar_time=bar.time,
                reason=Reason.DATA_HALT,
            )

        # 2. Event block (§29) — blocks new T-lots; target exits stay eligible.
        if event_rule is not None:
            if not isinstance(event_rule, EventBlockRule):
                raise StrategyInputError("event_rule must be an EventBlockRule or None")
            trade_date = bar.time[:10]
            if event_blocked(event_rule, symbol=bar.symbol, trade_date=trade_date):
                self._day_halts.add(Reason.EVENT_BLOCK)

        # 3. Volatility halt (§28) — daily move vs the frozen daily reference and
        #    bar-to-bar gap vs the previous bar (first bar uses the daily close).
        #    Blocks new T-lots; target exits stay eligible.
        if Reason.VOLATILITY_HALT not in self._day_halts:
            daily_close = self._basis.previous_close
            if daily_move_halted(
                previous_close=daily_close,
                current_price=float(bar.close),
                atr_pct=self._basis.atr_pct,
                halt_atr_k=self._global_config.volatility_halt_atr,
            ) or gap_halted(
                gap_reference=self._last_bar_close if self._last_bar_close is not None else daily_close,
                current_price=float(bar.close),
                grid_g=self._basis.grid_g,
            ):
                self._day_halts.add(Reason.VOLATILITY_HALT)
        self._last_bar_close = float(bar.close)

        minute = _minute_of_day(bar.time)
        if not self._session.contains(minute):
            # Out of session entirely: no decisions (bar is not tradable).
            return BarDecision(
                kind=DecisionKind.NO_ACTION,
                symbol=bar.symbol,
                bar_time=bar.time,
                reason=Reason.TIME_WINDOW,
            )

        if self._pending_buy or self._pending_sell:
            return BarDecision(
                kind=DecisionKind.NO_ACTION,
                symbol=bar.symbol,
                bar_time=bar.time,
                reason=Reason.PENDING_ORDER,
            )

        # 4. Sell evaluation first (LIFO, design §7/§15); a non-actionable
        #    result falls through to buy evaluation so ACCUMULATE can still
        #    average down while a lot is open (design §13/§14, max_t_lots).
        sell_decision = self._evaluate_sell(
            bar,
            broker_position=broker_position,
            can_use_qty=can_use_qty,
            strategic_extra=strategic_extra,
            reserved_sell_qty=reserved_sell_qty,
            minute=minute,
        )
        if sell_decision is not None:
            return sell_decision

        # 5. Buy evaluation (design §13) — applies the halt gates internally.
        return self._evaluate_buy(
            bar,
            broker_position=broker_position,
            available_cash=available_cash,
            minute=minute,
        )

    def _evaluate_sell(
        self,
        bar: Bar,
        *,
        broker_position: object,
        can_use_qty: object,
        strategic_extra: object,
        reserved_sell_qty: object,
        minute: int,
    ) -> BarDecision | None:
        if not self._open_lots:
            return None
        price = float(bar.close)
        # LIFO: scan newest -> oldest for the first qualifying target.
        candidate = None
        for lot in reversed(self._open_lots):
            if price >= lot.target_price:
                candidate = lot
                break
        if candidate is None:
            return None  # not actionable: fall through to buy evaluation
        # Time window for exits (§27): exits allowed unless near close is banned.
        if not self._allow_exit_near_close:
            skip_close = self._global_config.skip_close_minutes
            if minute >= self._session.close_minute - skip_close:
                return BarDecision(
                    kind=DecisionKind.NO_ACTION,
                    symbol=bar.symbol,
                    bar_time=bar.time,
                    reason=Reason.TIME_WINDOW,
                )
        # Core floor / available volume / reservation through the Gate 2 guard.
        try:
            snapshot = snapshot_from_symbol_config(
                self._symbol_config,
                symbol=bar.symbol,
                broker_position=broker_position,
                strategic_extra=strategic_extra,
                open_t_lot_position=self._sum_open_qty(),
                can_use_qty=can_use_qty,
                reserved_sell_qty=reserved_sell_qty,
            )
            CorePositionGuard.validate_t_sell(snapshot, candidate.qty)
        except (CoreFloorViolation, InsufficientAvailableVolume,
                SellReservationConflict, PositionInvariantError) as exc:
            if isinstance(exc, CoreFloorViolation):
                reason = Reason.CORE_FLOOR
            elif isinstance(exc, InsufficientAvailableVolume):
                reason = Reason.INSUFFICIENT_AVAILABLE_VOLUME
            elif isinstance(exc, SellReservationConflict):
                reason = Reason.SELL_RESERVATION_CONFLICT
            else:
                reason = Reason.POSITION_INVARIANT
            return BarDecision(
                kind=DecisionKind.SELL_REJECTED,
                symbol=bar.symbol,
                bar_time=bar.time,
                reason=reason,
                qty=candidate.qty,
                t_lot_id=candidate.t_lot_id,
                target_price=candidate.target_price,
            )
        # Legalize the exit limit: never accept less than the target.
        limit = legalize_price(candidate.target_price, self._symbol_config.price_tick, side="SELL")
        return BarDecision(
            kind=DecisionKind.SELL_T,
            symbol=bar.symbol,
            bar_time=bar.time,
            reason=Reason.EXIT_TRIGGERED,
            qty=candidate.qty,
            limit_price=limit,
            t_lot_id=candidate.t_lot_id,
            target_price=candidate.target_price,
        )

    def _evaluate_buy(
        self,
        bar: Bar,
        *,
        broker_position: object,
        available_cash: object,
        minute: int,
    ) -> BarDecision:
        symbol_cfg = self._symbol_config
        symbol = bar.symbol
        price = float(bar.close)
        halts = self._day_halts
        if not symbol_cfg.enabled:
            return BarDecision(
                kind=DecisionKind.BUY_REJECTED, symbol=symbol, bar_time=bar.time,
                reason=Reason.NOT_ENABLED,
            )
        if symbol_cfg.mode != ACCUMULATE_MODE:
            return BarDecision(
                kind=DecisionKind.BUY_REJECTED, symbol=symbol, bar_time=bar.time,
                reason=Reason.WRONG_MODE,
            )
        if self._pending_buy or self._pending_sell:
            return BarDecision(
                kind=DecisionKind.BUY_REJECTED, symbol=symbol, bar_time=bar.time,
                reason=Reason.PENDING_ORDER,
            )
        if (
            Reason.EVENT_BLOCK in halts
            or Reason.VOLATILITY_HALT in halts
            or Reason.DATA_HALT in halts
        ):
            reason = (
                Reason.EVENT_BLOCK
                if Reason.EVENT_BLOCK in halts
                else Reason.VOLATILITY_HALT
                if Reason.VOLATILITY_HALT in halts
                else Reason.DATA_HALT
            )
            return BarDecision(
                kind=DecisionKind.HALTED, symbol=symbol, bar_time=bar.time, reason=reason,
            )
        if self.open_lot_count() >= symbol_cfg.max_t_lots:
            return BarDecision(
                kind=DecisionKind.BUY_REJECTED, symbol=symbol, bar_time=bar.time,
                reason=Reason.T_CAPACITY_FULL,
            )
        # INV-003: position + t_unit must not exceed target_qty.
        if type(broker_position) is not int or broker_position < 0:
            return BarDecision(
                kind=DecisionKind.BUY_REJECTED, symbol=symbol, bar_time=bar.time,
                reason=Reason.POSITION_INVARIANT,
            )
        if broker_position + symbol_cfg.t_unit > symbol_cfg.target_qty:
            return BarDecision(
                kind=DecisionKind.BUY_REJECTED, symbol=symbol, bar_time=bar.time,
                reason=Reason.TARGET_CEILING,
            )
        # Time window (§27): no new T-lots in the first/last N minutes.
        skip_open = self._global_config.skip_open_minutes
        skip_close = self._global_config.skip_close_minutes
        if minute < self._session.open_minute + skip_open:
            return BarDecision(
                kind=DecisionKind.BUY_REJECTED, symbol=symbol, bar_time=bar.time,
                reason=Reason.TIME_WINDOW,
            )
        if minute >= self._session.close_minute - skip_close:
            return BarDecision(
                kind=DecisionKind.BUY_REJECTED, symbol=symbol, bar_time=bar.time,
                reason=Reason.TIME_WINDOW,
            )
        # Buy level: n = open lots + 1 (design §13).
        level = buy_level(
            self._basis.anchor, self._basis.grid_g, self.open_lot_count() + 1
        )
        if price > level:
            return BarDecision(
                kind=DecisionKind.NO_ACTION, symbol=symbol, bar_time=bar.time,
                reason=Reason.PRICE_ABOVE_BUY_LEVEL,
            )
        # Cash (§18.3): t_unit * price <= available_cash - minimum_cash_buffer.
        cost = symbol_cfg.t_unit * price
        if type(available_cash) not in (int, float) or isinstance(available_cash, bool):
            return BarDecision(
                kind=DecisionKind.BUY_REJECTED, symbol=symbol, bar_time=bar.time,
                reason=Reason.INSUFFICIENT_CASH,
            )
        cash = float(available_cash)
        if cost > cash - self._global_config.minimum_cash_buffer:
            return BarDecision(
                kind=DecisionKind.BUY_REJECTED, symbol=symbol, bar_time=bar.time,
                reason=Reason.INSUFFICIENT_CASH,
            )
        limit = legalize_price(level, symbol_cfg.price_tick, side="BUY")
        return BarDecision(
            kind=DecisionKind.BUY_T, symbol=symbol, bar_time=bar.time,
            reason=Reason.BUY_TRIGGERED,
            qty=symbol_cfg.t_unit, limit_price=limit,
        )

    # ------------------------------------------------------------------ fills

    def record_buy_fill(
        self, t_lot_id: str, *, qty: int, price: float, entry_time: str
    ) -> OpenTLotView:
        """Record a confirmed buy fill as an OPEN T-lot (partial fills allowed).

        The lot's target price is computed from the *actual* fill price
        (design §15).  Fails closed on non-positive qty/price or a duplicate id.
        """
        lot_id = _require_nonempty_str(t_lot_id, "t_lot_id")
        if type(qty) is not int or qty <= 0:
            raise StrategyInputError("qty must be a positive plain int")
        if type(price) not in (int, float) or isinstance(price, bool) or price <= 0:
            raise StrategyInputError("price must be a positive number")
        _require_nonempty_str(entry_time, "entry_time")
        if any(lot.t_lot_id == lot_id for lot in self._open_lots):
            raise StrategyInputError(f"duplicate t_lot_id {lot_id!r}")
        target = exit_target_price(
            float(price), self._basis.grid_g, self._symbol_config.exit_multiple
        )
        lot = OpenTLotView(
            t_lot_id=lot_id,
            qty=qty,
            entry_price=float(price),
            entry_time=entry_time,
            target_price=target,
        )
        self._open_lots.append(lot)
        self._pending_buy = False
        return lot

    def record_sell_fill(self, t_lot_id: str, *, price: float, exit_time: str) -> OpenTLotView:
        """Record a confirmed sell fill and remove the lot (LIFO bookkeeping).

        Returns the closed lot view.  The lot must exist and be the LIFO pick
        (newest open lot); anything else fails closed.
        """
        lot_id = _require_nonempty_str(t_lot_id, "t_lot_id")
        if type(price) not in (int, float) or isinstance(price, bool) or price <= 0:
            raise StrategyInputError("price must be a positive number")
        _require_nonempty_str(exit_time, "exit_time")
        if not self._open_lots:
            raise StrategyInputError("no open T-lot to close")
        newest = self._open_lots[-1]
        if newest.t_lot_id != lot_id:
            raise StrategyInputError(
                "sell fill must match the newest (LIFO) open T-lot"
            )
        closed = self._open_lots.pop()
        self._pending_sell = False
        return closed

    def mark_buy_pending(self) -> None:
        """Mark a BUY_T decision as an in-flight order (INV-004)."""
        if self._pending_buy or self._pending_sell:
            raise StrategyInputError("a pending order already exists")
        self._pending_buy = True

    def mark_sell_pending(self) -> None:
        """Mark a SELL_T decision as an in-flight order (INV-004)."""
        if self._pending_buy or self._pending_sell:
            raise StrategyInputError("a pending order already exists")
        self._pending_sell = True

    def cancel_pending(self) -> None:
        """Release a pending order flag without changing lots (order rejected)."""
        self._pending_buy = False
        self._pending_sell = False

    def _sum_open_qty(self) -> int:
        return sum(lot.qty for lot in self._open_lots)
