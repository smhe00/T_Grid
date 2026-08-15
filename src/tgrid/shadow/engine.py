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


def _require_plain_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ShadowInputError(f"{name} must be a plain non-negative int")
    return value


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
    """Real-broker reconciliation for one symbol (AUD-R1-003).

    Compares the REAL broker total position against the local REAL expected
    decomposition (``core + strategic + open_t``).  This is the only row that
    may be called a broker reconciliation; shadow hypothetical activity is
    reported separately via :class:`ShadowDeltaRow`.
    """

    symbol: str
    broker_position: int
    local_expected_position: int
    delta: int
    reconciled: bool


@dataclass(frozen=True)
class ShadowDeltaRow:
    """Hypothetical shadow activity for one symbol (AUD-R1-003).

    ``shadow_delta`` is the net hypothetical position change from shadow
    fills.  It is NEVER mixed into the real reconciliation; the effective
    (hypothetical) position is ``real + shadow_delta`` and is labelled as
    hypothetical wherever it appears.
    """

    symbol: str
    shadow_delta: int
    effective_position: int
    real_position: int


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

    def __init__(
        self,
        strategy: object,
        *,
        symbol: str,
        settlement_policy: object = None,
        core_qty: object = 0,
    ) -> None:
        if not isinstance(strategy, AccumulateStrategy):
            raise ShadowInputError("strategy must be an AccumulateStrategy")
        if type(symbol) is not str or symbol == "":
            raise ShadowInputError("symbol must be a non-empty string")
        if settlement_policy is not None:
            from tgrid.shadow.settlement import SettlementPolicy, SettlementTracker

            if not isinstance(settlement_policy, SettlementPolicy):
                raise ShadowInputError(
                    "settlement_policy must be a SettlementPolicy or None"
                )
            self._settlement = SettlementTracker(settlement_policy)
        else:
            self._settlement = None
        if type(core_qty) is not int or core_qty < 0:
            raise ShadowInputError("core_qty must be a plain non-negative int")
        self._strategy = strategy
        self._symbol = symbol
        self._core_qty = core_qty
        self._shadow_orders: list = []
        self._signal_log: list = []
        self._shadow_position = 0
        self._realized_t_pnl = 0.0
        self._violations = 0
        self._current_day: str | None = None

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
        if self._settlement is not None and self._current_day is not None:
            if trade_date != self._current_day:
                # Next trading session: release yesterday's locked buys (T1).
                self._settlement.advance_trading_day(
                    self._current_day, trade_date
                )
        self._strategy.begin_day(daily_bars, trade_date=trade_date)
        if self._settlement is not None:
            self._current_day = trade_date

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
        trade_date: object = None,
    ) -> BarDecision:
        """Feed one 5m bar; record decisions and shadow orders.

        ``assume_fill_price`` lets the caller model what WOULD have happened
        (e.g. fill at the limit price, or at the bar close) without any broker;
        when None, a BUY_T/SELL_T shadow order is recorded but the shadow
        position is left unchanged (the caller decides the assumption model).

        ``broker_position``/``can_use_qty`` are the REAL broker quantities.
        Under a settlement policy the effective sellable quantity is computed
        as ``real can_use + released shadow``; a same-day shadow BUY under T1
        never becomes sellable that day (AUD-R1-002).
        """
        if not isinstance(bar, Bar):
            raise ShadowInputError("bar must be a Bar")
        day = trade_date if trade_date is not None else bar.time[:10]

        if self._settlement is not None:
            if self._current_day is not None and day != self._current_day:
                # Next trading session: release yesterday's locked buys (T1).
                self._settlement.advance_trading_day(self._current_day, day)
                self._current_day = day
            shadow_released = self._settlement.sellable_from_released(day)
        else:
            shadow_released = 0

        effective_can_use = (
            _require_plain_int(can_use_qty, "can_use_qty") + shadow_released
        )
        # Strategy view uses the EFFECTIVE (hypothetical) position = real broker
        # + shadow delta, so the Broker = Core + Strategic + OpenT decomposition
        # holds for the hypothetical book (AUD-R1-003).  Real reconciliation is
        # never affected: reconcile()/shadow_delta() keep the real broker and
        # the shadow delta strictly separate.
        effective_position = (
            _require_plain_int(broker_position, "broker_position")
            + self._shadow_position
        )
        decision = self._strategy.on_bar(
            bar,
            broker_position=effective_position,
            can_use_qty=effective_can_use,
            strategic_extra=strategic_extra,
            reserved_sell_qty=0,
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
                    if self._settlement is not None:
                        # T1: same-day buy is locked; T0: immediately sellable.
                        self._settlement.record_buy(decision.qty, trade_date=day)
                else:
                    if decision.t_lot_id is None:
                        raise ShadowError("SELL_T decision without a t_lot_id")
                    lot = self._strategy.record_sell_fill(
                        decision.t_lot_id, price=fill, exit_time=bar.time,
                    )
                    self._shadow_position -= decision.qty
                    self._realized_t_pnl += (fill - lot.entry_price) * decision.qty
                    if self._settlement is not None:
                        self._settlement.record_sell(decision.qty, trade_date=day)
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

    def reconcile(
        self,
        broker_position: object,
        *,
        strategic_extra: object = 0,
        open_t_lot_position: object = 0,
    ) -> ReconciliationRow:
        """Reconcile the REAL broker position vs the REAL local expectation.

        ``local_expected = core_qty + strategic_extra + open_t_lot_position``
        (design §21–§22).  This is the authoritative broker reconciliation;
        shadow hypothetical activity is excluded (AUD-R1-003).
        """
        broker = _require_plain_int(broker_position, "broker_position")
        strategic = _require_plain_int(strategic_extra, "strategic_extra")
        open_t = _require_plain_int(open_t_lot_position, "open_t_lot_position")
        expected = self._core_qty + strategic + open_t
        delta = broker - expected
        return ReconciliationRow(
            symbol=self._symbol,
            broker_position=broker,
            local_expected_position=expected,
            delta=delta,
            reconciled=(delta == 0),
        )

    def shadow_delta(self, *, real_position: object) -> ShadowDeltaRow:
        """Report the hypothetical shadow activity vs the real position."""
        real = _require_plain_int(real_position, "real_position")
        return ShadowDeltaRow(
            symbol=self._symbol,
            shadow_delta=self._shadow_position,
            effective_position=real + self._shadow_position,
            real_position=real,
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
    strategic_extras: object = None,
    open_t_positions: object = None,
) -> dict:
    """Assemble the four §40 deliverables into a plain dict.

    ``engine`` is a :class:`ShadowEngine`; ``broker_positions`` maps symbol ->
    real broker total position (plain int).  ``strategic_extras`` and
    ``open_t_positions`` optionally map symbol -> plain int for the REAL
    reconciliation decomposition (default 0).

    Returns:

    * ``shadow_orders`` — WOULD_BUY/WOULD_SELL records;
    * ``signal_log`` — every strategy decision;
    * ``reconciliation`` — REAL broker vs REAL local expectation (AUD-R1-003);
    * ``shadow_delta`` — hypothetical shadow activity, explicitly separated;
    * ``daily_report`` — per-symbol daily state.

    All values are data-only.
    """
    if not isinstance(engine, ShadowEngine):
        raise ShadowInputError("engine must be a ShadowEngine")
    if type(trade_date) is not str or trade_date == "":
        raise ShadowInputError("trade_date must be a non-empty string")
    if broker_positions is None or not hasattr(broker_positions, "items"):
        raise ShadowInputError("broker_positions must be a mapping")
    strategic_extras = strategic_extras or {}
    open_t_positions = open_t_positions or {}

    rows = []
    delta_rows = []
    for symbol, position in broker_positions.items():
        if type(symbol) is not str:
            raise ShadowInputError("broker_positions keys must be strings")
        strategic = strategic_extras.get(symbol, 0)
        open_t = open_t_positions.get(symbol, 0)
        rows.append(engine.reconcile(position, strategic_extra=strategic,
                                     open_t_lot_position=open_t))
        delta_rows.append(engine.shadow_delta(real_position=position))
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
                "symbol": r.symbol, "broker_position": r.broker_position,
                "local_expected_position": r.local_expected_position,
                "delta": r.delta, "reconciled": r.reconciled,
            }
            for r in rows
        ],
        "shadow_delta": [
            {
                "symbol": d.symbol, "shadow_delta": d.shadow_delta,
                "effective_position": d.effective_position,
                "real_position": d.real_position,
            }
            for d in delta_rows
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
