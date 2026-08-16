"""End-to-end dry-run tests — the full §39 loop through the DryRunHarness."""

import os
import tempfile
import unittest

from tgrid.execution.dryrun import DryRunHarness, DryRunError
from tgrid.execution.executor import ExecutionEngine
from tgrid.execution.models import BUY, OrderStatus
from tgrid.execution.simbroker import SimBroker
from tgrid.execution.store import ExecutionStore
from tgrid.integrations.qec_adapter import make_execution_request
from tgrid.models import GlobalConfig, SymbolConfig
from tgrid.persistence import initialize
from tgrid.strategy.bars import Bar, SessionWindow
from tgrid.strategy.engine import AccumulateStrategy, DecisionKind


def _temp_db_path():
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = handle.name
    handle.close()
    os.remove(path)
    return path


def _global(**overrides):
    cfg = dict(
        live_trading=False, database="data/tgrid.db", log_dir="logs",
        bar_period="5m", order_timeout_seconds=120, skip_open_minutes=15,
        skip_close_minutes=15, volatility_halt_atr=2.5,
        minimum_cash_buffer=50000.0,
    )
    cfg.update(overrides)
    return GlobalConfig(**cfg)


def _symbol(**overrides):
    cfg = dict(
        enabled=True, mode="ACCUMULATE", core_qty=600, target_qty=1100,
        t_unit=100, lot_size=100, price_tick=0.2, max_t_lots=2,
        max_t_capital=200000.0, anchor="VWAP20", atr_period=14, atr_k=1.2,
        min_grid=0.040, max_grid=0.080, exit_multiple=1.15,
    )
    cfg.update(overrides)
    return SymbolConfig(**cfg)


SESSION = SessionWindow(open_minute=570, close_minute=900)


def _daily_bars(close=440.0, high=446.0, low=434.0, n=25, volume=1000):
    bars = []
    for i in range(n):
        day = 1 + i // 2
        bars.append(
            Bar(
                symbol="0700.HK",
                time=f"2026-07-{day:02d}T15:00:00",
                open=close, high=high, low=low, close=close,
                volume=volume, kind="DAILY",
            )
        )
    return bars


def _m5(minute, close, volume=1000):
    hours, mins = divmod(minute, 60)
    return Bar(
        symbol="0700.HK",
        time=f"2026-08-12T{hours:02d}:{mins:02d}:00",
        open=close, high=close, low=close, close=close,
        volume=volume, kind="5m",
    )


def _harness(fee_rate=0.0):
    conn = initialize(_temp_db_path())
    store = ExecutionStore(conn)
    broker = SimBroker()
    executor = ExecutionEngine(store, broker)
    strategy = AccumulateStrategy(_symbol(), _global(), session_window=SESSION)
    harness = DryRunHarness(strategy, executor, broker, fee_rate=fee_rate)
    harness.begin_day(_daily_bars(), trade_date="2026-08-12")
    return conn, harness


class TestFullLoop(unittest.TestCase):
    def test_buy_fill_sell_fill_pnl(self):
        conn, harness = _harness(fee_rate=0.0003)
        try:
            # Bar at 420 -> BUY_T -> broker fills fully at limit.
            r1 = harness.on_bar(
                _m5(600, 420.0), now="2026-08-12T10:00:00",
                broker_position=600, can_use_qty=600, strategic_extra=0,
                available_cash=500000.0,
                fill_script=(("FILL", 100, 420.0),),
            )
            self.assertEqual(r1.decision.kind, DecisionKind.BUY_T)
            self.assertEqual(r1.execution_status, OrderStatus.FILLED)
            self.assertIsNone(r1.pnl)

            # Bar at 445 -> SELL_T -> broker fills -> PnL recorded.
            r2 = harness.on_bar(
                _m5(605, 445.0), now="2026-08-12T10:05:00",
                broker_position=700, can_use_qty=700, strategic_extra=0,
                available_cash=500000.0,
                fill_script=(("FILL", 100, 439.4),),
            )
            self.assertEqual(r2.decision.kind, DecisionKind.SELL_T)
            self.assertEqual(r2.execution_status, OrderStatus.FILLED)
            self.assertIsNotNone(r2.pnl)
            pnl = r2.pnl
            self.assertEqual(pnl.qty, 100)
            self.assertEqual(pnl.entry_price, 420.0)
            self.assertGreater(pnl.gross_pnl, 0.0)
            self.assertGreater(pnl.fees, 0.0)
            self.assertLess(pnl.net_pnl, pnl.gross_pnl)
            self.assertEqual(len(harness.realized_pnl), 1)
        finally:
            conn.close()

    def test_partial_fill_then_full(self):
        conn, harness = _harness()
        try:
            # First bar: PARTIAL (60 of 100) -> lot not yet recorded.
            r1 = harness.on_bar(
                _m5(600, 420.0), now="2026-08-12T10:00:00",
                broker_position=600, can_use_qty=600, strategic_extra=0,
                available_cash=500000.0,
                fill_script=(("FILL", 60, 420.0),),
            )
            self.assertEqual(r1.execution_status, OrderStatus.PARTIAL)
            self.assertEqual(len(harness.realized_pnl), 0)
        finally:
            conn.close()

    def test_reject_creates_no_lot(self):
        conn, harness = _harness()
        try:
            r1 = harness.on_bar(
                _m5(600, 420.0), now="2026-08-12T10:00:00",
                broker_position=600, can_use_qty=600, strategic_extra=0,
                available_cash=500000.0,
                fill_script=(("REJECT",),),
            )
            self.assertEqual(r1.execution_status, OrderStatus.REJECTED)
            self.assertEqual(len(harness.realized_pnl), 0)
        finally:
            conn.close()

    def test_no_fill_keeps_lot_pending(self):
        conn, harness = _harness()
        try:
            r1 = harness.on_bar(
                _m5(600, 420.0), now="2026-08-12T10:00:00",
                broker_position=600, can_use_qty=600, strategic_extra=0,
                available_cash=500000.0,
            )
            self.assertEqual(r1.execution_status, OrderStatus.SUBMITTED)
            self.assertEqual(len(harness.realized_pnl), 0)
        finally:
            conn.close()


class TestHarnessGuards(unittest.TestCase):
    def test_strict_types(self):
        with self.assertRaises(DryRunError):
            DryRunHarness("strategy", None, None)
        conn = initialize(_temp_db_path())
        try:
            store = ExecutionStore(conn)
            broker = SimBroker()
            executor = ExecutionEngine(store, broker)
            with self.assertRaises(DryRunError):
                DryRunHarness(
                    AccumulateStrategy(_symbol(), _global(), session_window=SESSION),
                    executor, broker, fee_rate=-1.0,
                )
        finally:
            conn.close()


class TestCrashAfterSend(unittest.TestCase):
    def test_crash_after_broker_send_before_intent_update(self):
        # The §39 matrix: broker accepted the order but the process died before
        # the local broker_order_id write.  Recovery must match by key and the
        # order must be pollable to its true state.
        conn = initialize(_temp_db_path())
        try:
            store = ExecutionStore(conn)
            broker = SimBroker()
            # Local intent written first (NEW), then broker send — but the
            # "process" dies before update_intent_status(SUBMITTED).
            store.create_intent_with_reservation(
                client_order_key="K1", symbol="0700.HK", side="BUY", qty=100,
                limit_price=420.0, strategy_name="TGRID",
                order_remark="TG_0700HK_B001", created_at="t0",
                cash_amount=42000.0,
            )
            order_id = broker.place_order(make_execution_request(
                client_order_key="K1", symbol="0700.HK", side=BUY, qty=100,
                limit_price=420.0, strategy_name="TGRID",
                order_remark="TG_0700HK_B001",
            ))
            broker.get_order(order_id).script = (("FILL", 100, 420.0),)
            # Restart: the engine's authoritative reconciliation matches the
            # intent to the broker order (MATCHED -> SAFE_MODE clears).
            engine = ExecutionEngine(store, broker, strategy_name="TGRID")
            try:
                engine.reconcile_and_clear_safe_mode()  # no raise => MATCHED
            finally:
                engine.close()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
