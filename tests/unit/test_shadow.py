"""Tests for tgrid.shadow — Gate 5 Shadow mode (design §40).

Verifies: WOULD_BUY/WOULD_SELL records, signal log, shadow position
assumptions, reconciliation (shadow vs broker), daily report shape, and the
hard no-broker-send boundary.
"""

import unittest

from tgrid.models import GlobalConfig, SymbolConfig
from tgrid.shadow.engine import ShadowEngine, build_shadow_reports
from tgrid.shadow.engine import ShadowInputError
from tgrid.strategy.bars import Bar, SessionWindow
from tgrid.strategy.engine import AccumulateStrategy, DecisionKind


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


def _engine():
    strategy = AccumulateStrategy(_symbol(), _global(), session_window=SESSION)
    shadow = ShadowEngine(strategy, symbol="0700.HK")
    shadow.begin_day(_daily_bars(), trade_date="2026-08-12")
    return shadow


class TestShadowOrderGeneration(unittest.TestCase):
    def test_would_buy_recorded_not_sent(self):
        shadow = _engine()
        decision = shadow.on_bar(
            _m5(600, 420.0), now="2026-08-12T10:00:00",
            broker_position=600, can_use_qty=600, strategic_extra=0,
            available_cash=500000.0,
        )
        self.assertEqual(decision.kind, DecisionKind.BUY_T)
        self.assertEqual(len(shadow.shadow_orders), 1)
        order = shadow.shadow_orders[0]
        self.assertEqual(order.side, "WOULD_BUY")
        self.assertEqual(order.qty, 100)
        # Without an assumption model the shadow position stays unchanged.
        self.assertEqual(shadow.shadow_position, 0)

    def test_would_sell_recorded_with_fill_assumption(self):
        shadow = _engine()
        shadow.on_bar(
            _m5(600, 420.0), now="2026-08-12T10:00:00",
            broker_position=600, can_use_qty=600, strategic_extra=0,
            available_cash=500000.0, assume_fill_price=420.0,
        )
        self.assertEqual(shadow.shadow_position, 100)
        shadow.on_bar(
            _m5(605, 445.0), now="2026-08-12T10:05:00",
            broker_position=700, can_use_qty=700, strategic_extra=0,
            available_cash=500000.0, assume_fill_price=445.0,
        )
        sides = [o.side for o in shadow.shadow_orders]
        self.assertEqual(sides, ["WOULD_BUY", "WOULD_SELL"])
        self.assertEqual(shadow.shadow_position, 0)
        self.assertGreater(shadow.realized_t_pnl, 0.0)

    def test_signal_log_records_every_bar(self):
        shadow = _engine()
        shadow.on_bar(
            _m5(600, 440.0), now="2026-08-12T10:00:00",
            broker_position=600, can_use_qty=600, strategic_extra=0,
            available_cash=500000.0,
        )
        shadow.on_bar(
            _m5(605, 420.0), now="2026-08-12T10:05:00",
            broker_position=600, can_use_qty=600, strategic_extra=0,
            available_cash=500000.0,
        )
        self.assertEqual(len(shadow.signal_log), 2)
        self.assertEqual(shadow.signal_log[0].kind, DecisionKind.NO_ACTION)
        self.assertEqual(shadow.signal_log[1].kind, DecisionKind.BUY_T)

    def test_rejections_counted_as_violations(self):
        shadow = _engine()
        shadow.on_bar(
            _m5(600, 420.0), now="2026-08-12T10:00:00",
            broker_position=1050, can_use_qty=1050, strategic_extra=0,
            available_cash=500000.0,
        )
        self.assertEqual(shadow.daily_report("2026-08-12").violations, 1)


class TestReconciliation(unittest.TestCase):
    def test_exact_match(self):
        shadow = _engine()
        shadow.on_bar(
            _m5(600, 420.0), now="2026-08-12T10:00:00",
            broker_position=600, can_use_qty=600, strategic_extra=0,
            available_cash=500000.0, assume_fill_price=420.0,
        )
        row = shadow.reconcile(700)
        self.assertEqual(row.shadow_position, 100)
        self.assertEqual(row.broker_position, 700)
        self.assertEqual(row.delta, -600)
        self.assertFalse(row.reconciled)

    def test_mismatch_flagged(self):
        shadow = _engine()
        row = shadow.reconcile(700)
        self.assertEqual(row.delta, -700)
        self.assertFalse(row.reconciled)

    def test_invalid_position_rejected(self):
        shadow = _engine()
        with self.assertRaises(ShadowInputError):
            shadow.reconcile("700")


class TestDailyReportAndAssembler(unittest.TestCase):
    def test_daily_report_shape(self):
        shadow = _engine()
        shadow.on_bar(
            _m5(600, 420.0), now="2026-08-12T10:00:00",
            broker_position=600, can_use_qty=600, strategic_extra=0,
            available_cash=500000.0, assume_fill_price=420.0,
        )
        report = shadow.daily_report("2026-08-12")
        self.assertEqual(report.symbol, "0700.HK")
        self.assertEqual(report.open_t_lots, 1)
        self.assertEqual(report.open_t_qty, 100)
        self.assertEqual(report.shadow_orders, 1)
        self.assertGreater(report.anchor, 0.0)
        self.assertGreater(report.grid_g, 0.0)

    def test_build_shadow_reports(self):
        shadow = _engine()
        shadow.on_bar(
            _m5(600, 420.0), now="2026-08-12T10:00:00",
            broker_position=600, can_use_qty=600, strategic_extra=0,
            available_cash=500000.0,
        )
        reports = build_shadow_reports(
            shadow, trade_date="2026-08-12",
            broker_positions={"0700.HK": 600},
        )
        self.assertIn("shadow_orders", reports)
        self.assertIn("signal_log", reports)
        self.assertIn("reconciliation", reports)
        self.assertIn("daily_report", reports)
        self.assertEqual(len(reports["shadow_orders"]), 1)
        self.assertEqual(reports["shadow_orders"][0]["side"], "WOULD_BUY")

    def test_assembler_strict_types(self):
        with self.assertRaises(ShadowInputError):
            build_shadow_reports("not-engine", trade_date="d",
                                 broker_positions={})


class TestNoBrokerSurface(unittest.TestCase):
    def test_no_order_stock_in_shadow_source(self):
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[2] / "src" / "tgrid" / "shadow"
        )
        for path in source.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = None
                    if isinstance(func, ast.Attribute):
                        name = func.attr
                    elif isinstance(func, ast.Name):
                        name = func.id
                    self.assertNotIn(
                        name, {"order_stock", "cancel_order_stock", "cancel_order"},
                        f"forbidden broker call {name} in {path}",
                    )


if __name__ == "__main__":
    unittest.main()
