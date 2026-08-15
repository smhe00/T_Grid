"""Dry-run harness tying strategy decisions to the execution engine (Gate 4).

:class:`DryRunHarness` connects the offline :class:`AccumulateStrategy` to the
:class:`ExecutionEngine` + :class:`SimBroker` (through the simulation-only
:class:`~tgrid.execution.simdriver.SimulationDriver`, NODEB-001) and computes
realized T PnL when a T-Lot closes (design §39: 行情→信号→订单→成交→T-Lot→卖出→PnL).
It is the reference wiring the Gate 5 shadow mode will reuse; it never touches
QMT and never places a real order.

The harness owns per-symbol open lots (mirroring the strategy's view) and, on a
confirmed SELL fill, computes gross realized PnL from the actual fill price and
the lot's recorded entry price, subtracting configured fees.
"""

from __future__ import annotations

from dataclasses import dataclass

from tgrid.execution.executor import ExecutionEngine
from tgrid.execution.models import BUY, SELL, OrderStatus
from tgrid.execution.simbroker import SimBroker
from tgrid.execution.simdriver import SimulationDriver, SimulationDriverError
from tgrid.strategy.bars import Bar
from tgrid.strategy.engine import AccumulateStrategy, BarDecision, DecisionKind


class DryRunError(Exception):
    """Base class for dry-run harness failures."""


@dataclass(frozen=True)
class PnLRecord:
    """Realized PnL of one closed T-Lot (gross and net of fees)."""

    t_lot_id: str
    symbol: str
    entry_price: float
    exit_price: float
    qty: int
    gross_pnl: float
    fees: float
    net_pnl: float


@dataclass(frozen=True)
class DryRunResult:
    """Outcome of processing one 5m bar through the harness."""

    decision: BarDecision
    execution_status: str | None
    execution_message: str
    pnl: PnLRecord | None


class DryRunHarness:
    """Ties strategy + executor + broker and tracks realized PnL.

    ``engine`` is the strategy (per-symbol), ``executor`` the execution layer,
    ``broker`` the SimBroker.  ``fee_rate`` is the fractional trading fee
    applied on the filled notional of the closing sell.
    """

    def __init__(
        self,
        strategy: object,
        executor: object,
        broker: object,
        *,
        fee_rate: float = 0.0,
        symbol: str = "0700.HK",
    ) -> None:
        if not isinstance(strategy, AccumulateStrategy):
            raise DryRunError("strategy must be an AccumulateStrategy")
        if not isinstance(executor, ExecutionEngine):
            raise DryRunError("executor must be an ExecutionEngine")
        if not isinstance(broker, SimBroker):
            raise DryRunError("broker must be a SimBroker")
        if type(fee_rate) not in (int, float) or isinstance(fee_rate, bool) or fee_rate < 0:
            raise DryRunError("fee_rate must be a non-negative number")
        if type(symbol) is not str or symbol == "":
            raise DryRunError("symbol must be a non-empty string")
        self._strategy = strategy
        self._executor = executor
        self._broker = broker
        try:
            self._driver = SimulationDriver(executor, broker)
        except SimulationDriverError as exc:
            raise DryRunError(str(exc)) from exc
        self._fee_rate = float(fee_rate)
        self._symbol = symbol
        self._seq = 0
        self._pnl: list = []
        self._open_lots: dict = {}  # t_lot_id -> entry price

    @property
    def realized_pnl(self) -> tuple:
        return tuple(self._pnl)

    def begin_day(self, daily_bars: object, *, trade_date: str) -> None:
        self._strategy.begin_day(daily_bars, trade_date=trade_date)

    def _next_key(self, side: str) -> str:
        self._seq += 1
        return f"TG_{self._symbol.replace('.', '')}_{side[0]}{self._seq:03d}"

    def on_bar(
        self,
        bar: object,
        *,
        broker_position: object,
        can_use_qty: object,
        strategic_extra: object,
        available_cash: object,
        now: object = None,
        fill_script: tuple = (),
    ) -> DryRunResult:
        """Process one 5m bar: strategy decision -> order -> fill -> lot/PnL.

        ``fill_script`` is passed to the executor for the order placed by this
        bar (the broker-side deterministic script, design §39).
        """
        if not isinstance(bar, Bar):
            raise DryRunError("bar must be a Bar")
        reserved_sell = self._executor.store.reserved_sell_qty(bar.symbol)
        decision = self._strategy.on_bar(
            bar,
            broker_position=broker_position,
            can_use_qty=can_use_qty,
            strategic_extra=strategic_extra,
            reserved_sell_qty=reserved_sell,
            available_cash=available_cash,
            now=now if now is not None else bar.time,
        )

        if decision.kind == DecisionKind.BUY_T:
            key = self._next_key("B")
            result = self._driver.send_buy(
                client_order_key=key,
                symbol=decision.symbol,
                qty=decision.qty,
                limit_price=decision.limit_price,
                order_remark=key,
                now=now if now is not None else bar.time,
                script=fill_script,
                expected_available_cash=float(available_cash),
                reserved_cash=decision.qty * decision.limit_price,
            )
            if result.status == OrderStatus.FILLED:
                # Record the lot at the ACTUAL fill price (design §24: the
                # ledger reflects real fills, not the intended limit).
                fill_price = result.fill_price if result.fill_price is not None else decision.limit_price
                self._strategy.record_buy_fill(
                    key, qty=decision.qty,
                    price=fill_price,
                    entry_time=now if now is not None else bar.time,
                )
                self._open_lots[key] = fill_price
            return DryRunResult(
                decision=decision,
                execution_status=result.status,
                execution_message=result.message,
                pnl=None,
            )

        if decision.kind == DecisionKind.SELL_T:
            key = self._next_key("S")
            result = self._driver.send_sell(
                client_order_key=key,
                symbol=decision.symbol,
                qty=decision.qty,
                limit_price=decision.limit_price,
                order_remark=key,
                now=now if now is not None else bar.time,
                script=fill_script,
                expected_available_qty=decision.qty,
            )
            pnl_record = None
            if result.status == OrderStatus.FILLED and decision.t_lot_id is not None:
                entry = self._open_lots.get(decision.t_lot_id)
                if entry is None:
                    raise DryRunError(
                        f"no open lot recorded for {decision.t_lot_id!r}"
                    )
                exit_price = result.fill_price if result.fill_price is not None else decision.limit_price
                self._strategy.record_sell_fill(
                    decision.t_lot_id, price=exit_price,
                    exit_time=now if now is not None else bar.time,
                )
                gross = (exit_price - entry) * decision.qty
                fees = exit_price * decision.qty * self._fee_rate
                pnl_record = PnLRecord(
                    t_lot_id=decision.t_lot_id, symbol=decision.symbol,
                    entry_price=entry, exit_price=exit_price,
                    qty=decision.qty, gross_pnl=round(gross, 4),
                    fees=round(fees, 4), net_pnl=round(gross - fees, 4),
                )
                self._pnl.append(pnl_record)
                del self._open_lots[decision.t_lot_id]
            return DryRunResult(
                decision=decision,
                execution_status=result.status,
                execution_message=result.message,
                pnl=pnl_record,
            )

        return DryRunResult(
            decision=decision, execution_status=None, execution_message="", pnl=None
        )
