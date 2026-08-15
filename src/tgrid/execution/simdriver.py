"""Simulation-only execution driver (NODEB-001).

The deterministic §39 script mechanics (``SimBroker.get_order`` /
``tick_order`` / per-order ``script``) are owned EXCLUSIVELY by this driver so
:class:`~tgrid.execution.executor.ExecutionEngine` stays broker-type agnostic.
The driver mirrors the historical engine behaviour for the offline dry run:

* ``send_buy/send_sell(..., script=...)`` — send through the engine (SUBMITTED),
  attach the script to the broker order, tick through it, then fold the final
  broker state back into the intent via ``engine.poll_order``;
* ``poll_order`` — advance exactly one deterministic step, then poll;
* ``timeout_order/cancel_order`` — delegate to the engine (cancel -> re-query).

Production/pre-live execution must NOT use this driver; it requires a
:class:`SimBroker` and only ever runs offline.
"""

from __future__ import annotations

from dataclasses import replace

from tgrid.execution.executor import ExecutionEngine, ExecutionResult
from tgrid.execution.simbroker import SimBroker


class SimulationDriverError(Exception):
    """Base class for simulation driver failures."""


class SimulationDriver:
    """Wraps an ExecutionEngine + SimBroker and applies deterministic scripts."""

    def __init__(self, engine: object, broker: object) -> None:
        if not isinstance(engine, ExecutionEngine):
            raise SimulationDriverError("engine must be an ExecutionEngine")
        if not isinstance(broker, SimBroker):
            raise SimulationDriverError(
                "simulation driver requires a SimBroker (offline only)"
            )
        self._engine = engine
        self._broker = broker

    @property
    def engine(self) -> ExecutionEngine:
        return self._engine

    # ------------------------------------------------------------- actions

    def send_buy(
        self,
        *,
        client_order_key: str,
        symbol: str,
        qty: int,
        limit_price: float,
        order_remark: str,
        now: str,
        script: tuple = (),
        expected_available_cash: float,
        reserved_cash: float,
    ) -> ExecutionResult:
        result = self._engine.send_buy(
            client_order_key=client_order_key, symbol=symbol, qty=qty,
            limit_price=limit_price, order_remark=order_remark, now=now,
            expected_available_cash=expected_available_cash,
            reserved_cash=reserved_cash,
        )
        return self._fold_script(result, script, now=now)

    def send_sell(
        self,
        *,
        client_order_key: str,
        symbol: str,
        qty: int,
        limit_price: float,
        order_remark: str,
        now: str,
        script: tuple = (),
        expected_available_qty: int,
    ) -> ExecutionResult:
        result = self._engine.send_sell(
            client_order_key=client_order_key, symbol=symbol, qty=qty,
            limit_price=limit_price, order_remark=order_remark, now=now,
            expected_available_qty=expected_available_qty,
        )
        return self._fold_script(result, script, now=now)

    def _fold_script(self, result: ExecutionResult, script: tuple, *, now: str) -> ExecutionResult:
        """Attach the script to the broker order, tick it, then fold the state."""
        if not script:
            return result
        if result.broker_order_id is None:
            return result
        order = self._broker.get_order(result.broker_order_id)
        order.script = tuple(script)
        for _ in script:
            self._broker.tick_order(result.broker_order_id)
        folded = self._engine.poll_order(result.client_order_key, now=now)
        if folded.fill_price is None and result.broker_order_id is not None:
            trades = self._broker.query_trades(result.broker_order_id)
            if trades:
                folded = replace(folded, fill_price=float(trades[-1].price))
        return folded

    # -------------------------------------------------------------- poll

    def poll_order(self, client_order_key: str, *, now: str) -> ExecutionResult:
        """Advance exactly one deterministic step, then poll the engine."""
        intent = self._engine.store.get_intent(client_order_key)
        if intent.broker_order_id is not None:
            self._broker.tick_order(intent.broker_order_id)
        return self._engine.poll_order(client_order_key, now=now)

    def timeout_order(self, client_order_key: str, *, now: str) -> ExecutionResult:
        return self._engine.timeout_order(client_order_key, now=now)

    def cancel_order(self, client_order_key: str, *, now: str) -> ExecutionResult:
        return self._engine.cancel_order(client_order_key, now=now)
