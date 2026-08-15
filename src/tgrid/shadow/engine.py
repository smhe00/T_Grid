"""Shadow-mode execution engine (Gate 5, design §40).

Gate 5 keeps ``MarketData = REAL`` and ``BrokerQuery = REAL`` but execution is
**SHADOW**: the engine generates ``WOULD_BUY`` / ``WOULD_SELL`` decisions with
the full strategy + risk pipeline, but never sends an order to a broker.  The
shadow order book is compared against real broker positions/orders daily so a
drift signals a real problem before any money is at risk.

This module is fully offline-testable: market data arrives as plain bars (from
the real QMT adapters in production, from fixtures in tests), and no broker
surface is required — :class:`ShadowEngine` never calls ``order_stock`` or
``cancel_order`` (INV-009; a hard scan guard).

Deliverables per design §40:

* Shadow Orders (``WOULD_BUY`` / ``WOULD_SELL`` records)
* Signal Log (every strategy decision with reason)
* Reconciliation Report (shadow vs broker positions)
* Daily Report (per-symbol state, T PnL, violations, next-day state)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from tgrid.models import GlobalConfig, SymbolConfig
from tgrid.strategy.bars import Bar, SessionWindow
from tgrid.strategy.engine import AccumulateStrategy, BarDecision, DecisionKind, Reason


class ShadowError(Exception):
    """Base class for shadow-mode failures."""


class ShadowInputError(ShadowError):
    """A shadow-mode argument is invalid (fail closed before use)."""


@dataclass(frozen=True)
class ShadowOrder:
    """A WOULD order: the order the strategy WOULD have sent (never sent)."""

    symbol: str
    side: str  # WOULD_BUY | WOULD_SELL
    qty: int
    limit_price: float
    bar_time: str
    decision_kind: str
    reason: str


@dataclass(frozen=True)
class SignalRecord:
    """One strategy decision record for the signal log."""

    symbol: str
    bar_time: str
    kind: str
    reason: str
    qty: int
    limit_price: float


@dataclass(frozen=True)
class ReconciliationRow:
    """Shadow vs broker position comparison for one symbol."""

    symbol: str
    shadow_position: int
    broker_position: int
    delta: int
    reconciled: bool


@dataclass(frozen=True)
class DailyReport:
    """Per-symbol daily report row (design §46)."""

    symbol: str
    trade_date: str
    anchor: float
    atr_pct: float
    grid_g: float
    open_t_lots: int
    open_t_qty: int
    realized_t_pnl: float
    shadow_orders: int
    halted: str
    violations: int


class ShadowEngine:
    """Runs the strategy pipeline in shadow mode for one symbol.

    ``strategy`` is an :class:`AccumulateStrategy`; the engine feeds it bars,
    records every decision to the signal log, converts BUY_T/SELL_T into
    :class:`ShadowOrder` records (never executed), and tracks an internal
    shadow position so daily reconciliation against the real broker position is
    possible (design §40/§22).
    """

    def __init__(self, strategy: object, *, symbol: str) -> None:
        if not isinstance(strategy, AccumulateStrategy):
            raise ShadowInputError("strategy must be an AccumulateStrategy")
        if type(symbol) is not str or symbol == "":
            raise ShadowInputError("symbol must be a non-empty string")
        self._strategy = strategy
        self._symbol = symbol
        self._shadow_orders: list = []
        self._signal_log: list = []
        self._shadow_position = 0
        self._realized_t_pnl = 0.0
        self._violations = 0

    # ------------------------------------------------------------ properties

    @property
    def shadow_orders(self) -> tuple:
        return tuple(self._shadow_orders)

    @property
    def signal_log(self) -> tuple:
        return tuple(self._signal_log)

    @property
    def shadow_position(self) -> int:
        return self._shadow_position

    @property
    def realized_t_pnl(self) -> float:
        return self._realized_t_pnl

    # ------------------------------------------------------------------ flow

    def begin_day(self, daily_bars: object, *, trade_date: str) -> None:
        self._strategy.begin_day(daily_bars, trade_date=trade_date)

    def on_bar(
        self,
        bar: object,
        *,
        broker_position: object,
        can_use_qty: object,
        strategic_extra: object,
        available_cash: object,
        now: object = None,
        assume_fill_price: object = None,
    ) -> BarDecision:
        """Feed one 5m bar; record decisions and shadow orders.

        ``assume_fill_price`` lets the caller model what WOULD have happened
        (e.g. fill at the limit price, or at the bar close) without any broker;
        when None, a BUY_T/SELL_T shadow order is recorded but the shadow
        position is left unchanged (the caller decides the assumption model).
        """
        if not isinstance(bar, Bar):
            raise ShadowInputError("bar must be a Bar")
        reserved_sell = 0
        decision = self._strategy.on_bar(
            bar,
            broker_position=broker_position,
            can_use_qty=can_use_qty,
            strategic_extra=strategic_extra,
            reserved_sell_qty=reserved_sell,
            available_cash=available_cash,
            now=now if now is not None else bar.time,
        )
        self._signal_log.append(
            SignalRecord(
                symbol=bar.symbol, bar_time=bar.time, kind=decision.kind,
                reason=decision.reason, qty=decision.qty,
                limit_price=decision.limit_price,
            )
        )
        if decision.kind in (DecisionKind.BUY_T, DecisionKind.SELL_T):
            side = "WOULD_BUY" if decision.kind == DecisionKind.BUY_T else "WOULD_SELL"
            order = ShadowOrder(
                symbol=bar.symbol, side=side, qty=decision.qty,
                limit_price=decision.limit_price, bar_time=bar.time,
                decision_kind=decision.kind, reason=decision.reason,
            )
            self._shadow_orders.append(order)
            if assume_fill_price is not None:
                fill = float(assume_fill_price)
                if decision.kind == DecisionKind.BUY_T:
                    self._shadow_position += decision.qty
                    self._strategy.record_buy_fill(
                        f"SHADOW-{len(self._shadow_orders):05d}",
                        qty=decision.qty, price=fill, entry_time=bar.time,
                    )
                else:
                    if decision.t_lot_id is None:
                        raise ShadowError("SELL_T decision without a t_lot_id")
                    lot = self._strategy.record_sell_fill(
                        decision.t_lot_id, price=fill, exit_time=bar.time,
                    )
                    self._shadow_position -= decision.qty
                    self._realized_t_pnl += (fill - lot.entry_price) * decision.qty
        elif decision.kind in (
            DecisionKind.SELL_REJECTED, DecisionKind.BUY_REJECTED,
            DecisionKind.HALTED,
        ):
            # Only genuine risk/invariant failures are violations; routine
            # gates (time window, price above level) are normal market states.
            if decision.reason in (
                Reason.CORE_FLOOR,
                Reason.INSUFFICIENT_AVAILABLE_VOLUME,
                Reason.SELL_RESERVATION_CONFLICT,
                Reason.POSITION_INVARIANT,
                Reason.T_CAPACITY_FULL,
                Reason.TARGET_CEILING,
                Reason.INSUFFICIENT_CASH,
                Reason.DATA_HALT,
            ):
                self._violations += 1
        return decision

    def reconcile(self, broker_position: object) -> ReconciliationRow:
        """Compare the shadow position against the real broker position."""
        if type(broker_position) is not int or broker_position < 0:
            raise ShadowInputError("broker_position must be a non-negative int")
        delta = self._shadow_position - broker_position
        return ReconciliationRow(
            symbol=self._symbol,
            shadow_position=self._shadow_position,
            broker_position=broker_position,
            delta=delta,
            reconciled=(delta == 0),
        )

    def daily_report(self, trade_date: str) -> DailyReport:
        basis = self._strategy.daily_basis
        halted = "NONE"
        state = self._strategy.state()
        if state in ("EVENT_BLOCK", "VOLATILITY_HALT", "DATA_HALT"):
            halted = state
        return DailyReport(
            symbol=self._symbol,
            trade_date=trade_date,
            anchor=basis.anchor if basis is not None else 0.0,
            atr_pct=basis.atr_pct if basis is not None else 0.0,
            grid_g=basis.grid_g if basis is not None else 0.0,
            open_t_lots=self._strategy.open_lot_count(),
            open_t_qty=sum(lot.qty for lot in self._strategy.open_t_lots()),
            realized_t_pnl=round(self._realized_t_pnl, 4),
            shadow_orders=len(self._shadow_orders),
            halted=halted,
            violations=self._violations,
        )


def build_shadow_reports(
    engine: object,
    *,
    trade_date: str,
    broker_positions: object,
) -> dict:
    """Assemble the four §40 deliverables into a plain dict.

    ``engine`` is a :class:`ShadowEngine`; ``broker_positions`` maps symbol ->
    int.  Returns ``{"shadow_orders": [...], "signal_log": [...],
    "reconciliation": [...], "daily_report": {...}}`` — all data-only.
    """
    if not isinstance(engine, ShadowEngine):
        raise ShadowInputError("engine must be a ShadowEngine")
    if type(trade_date) is not str or trade_date == "":
        raise ShadowInputError("trade_date must be a non-empty string")
    if broker_positions is None or not hasattr(broker_positions, "items"):
        raise ShadowInputError("broker_positions must be a mapping")
    rows = []
    for symbol, position in broker_positions.items():
        if type(symbol) is not str:
            raise ShadowInputError("broker_positions keys must be strings")
        rows.append(engine.reconcile(position))
    return {
        "shadow_orders": [
            {
                "symbol": o.symbol, "side": o.side, "qty": o.qty,
                "limit_price": o.limit_price, "bar_time": o.bar_time,
                "decision_kind": o.decision_kind, "reason": o.reason,
            }
            for o in engine.shadow_orders
        ],
        "signal_log": [
            {
                "symbol": s.symbol, "bar_time": s.bar_time, "kind": s.kind,
                "reason": s.reason, "qty": s.qty, "limit_price": s.limit_price,
            }
            for s in engine.signal_log
        ],
        "reconciliation": [
            {
                "symbol": r.symbol, "shadow_position": r.shadow_position,
                "broker_position": r.broker_position, "delta": r.delta,
                "reconciled": r.reconciled,
            }
            for r in rows
        ],
        "daily_report": {
            "symbol": engine.daily_report(trade_date).symbol,
            "trade_date": trade_date,
            "anchor": engine.daily_report(trade_date).anchor,
            "atr_pct": engine.daily_report(trade_date).atr_pct,
            "grid_g": engine.daily_report(trade_date).grid_g,
            "open_t_lots": engine.daily_report(trade_date).open_t_lots,
            "open_t_qty": engine.daily_report(trade_date).open_t_qty,
            "realized_t_pnl": engine.daily_report(trade_date).realized_t_pnl,
            "shadow_orders": engine.daily_report(trade_date).shadow_orders,
            "halted": engine.daily_report(trade_date).halted,
            "violations": engine.daily_report(trade_date).violations,
        },
    }
