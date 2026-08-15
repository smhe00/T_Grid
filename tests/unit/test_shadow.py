"""Tests for tgrid.shadow — Gate 5 Shadow mode (design §40).

Verifies: WOULD_BUY/WOULD_SELL records, signal log, shadow position
assumptions, reconciliation (shadow vs broker), daily report shape, and the
hard no-broker-send boundary.
"""

import unittest

from tgrid.models import GlobalConfig, SymbolConfig
from tgrid.shadow.engine import ShadowEngine, build_shadow_reports
from tgrid.shadow.engine import ShadowInputError
from tgrid.shadow.settlement import SETTLE_T1, SettlementPolicy
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


def _m5(minute, close, volume=1000, day="2026-08-12"):
    hours, mins = divmod(minute, 60)
    return Bar(
        symbol="0700.HK",
        time=f"{day}T{hours:02d}:{mins:02d}:00",
        open=close, high=close, low=close, close=close,
        volume=volume, kind="5m",
    )


def _engine(**engine_overrides):
    strategy = AccumulateStrategy(_symbol(), _global(), session_window=SESSION)
    shadow = ShadowEngine(
        strategy, symbol="0700.HK", core_qty=600, **engine_overrides,
    )
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
        # The caller passes the REAL broker position (600 = core); the engine
        # adds the shadow delta internally (effective view 700 = 600 + 100).
        shadow.on_bar(
            _m5(605, 445.0), now="2026-08-12T10:05:00",
            broker_position=600, can_use_qty=700, strategic_extra=0,
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
    """AUD-R1-003: real reconciliation is separate from shadow delta."""

    def test_real_reconcile_exact_match(self):
        shadow = _engine()
        row = shadow.reconcile(600, strategic_extra=0, open_t_lot_position=0)
        # core_qty=600 from the strategy config; broker 600 == local expected.
        self.assertEqual(row.broker_position, 600)
        self.assertEqual(row.local_expected_position, 600)
        self.assertEqual(row.delta, 0)
        self.assertTrue(row.reconciled)

    def test_real_reconcile_mismatch(self):
        shadow = _engine()
        row = shadow.reconcile(700)
        self.assertEqual(row.delta, 700 - 600)
        self.assertFalse(row.reconciled)

    def test_real_reconcile_with_open_t(self):
        shadow = _engine()
        row = shadow.reconcile(700, open_t_lot_position=100)
        # expected = core 600 + open_t 100 = 700 == broker 700
        self.assertTrue(row.reconciled)

    def test_shadow_delta_separate(self):
        shadow = _engine()
        shadow.on_bar(
            _m5(600, 420.0), now="2026-08-12T10:00:00",
            broker_position=600, can_use_qty=600, strategic_extra=0,
            available_cash=500000.0, assume_fill_price=420.0,
        )
        # Shadow bought 100 hypothetically; real broker still 600.
        delta = shadow.shadow_delta(real_position=600)
        self.assertEqual(delta.shadow_delta, 100)
        self.assertEqual(delta.effective_position, 700)
        self.assertEqual(delta.real_position, 600)
        # Real reconciliation is unaffected by the shadow buy.
        row = shadow.reconcile(600)
        self.assertTrue(row.reconciled)

    def test_invalid_position_rejected(self):
        shadow = _engine()
        with self.assertRaises(ShadowInputError):
            shadow.reconcile("700")
        with self.assertRaises(ShadowInputError):
            shadow.shadow_delta(real_position="600")


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
        self.assertIn("shadow_delta", reports)
        self.assertIn("daily_report", reports)
        self.assertEqual(len(reports["shadow_orders"]), 1)
        self.assertEqual(reports["shadow_orders"][0]["side"], "WOULD_BUY")
        # Real reconciliation reflects broker 600 vs local expected 600.
        self.assertTrue(reports["reconciliation"][0]["reconciled"])
        # Shadow delta is reported separately and equals 0 (no fill assumed).
        self.assertEqual(reports["shadow_delta"][0]["shadow_delta"], 0)

    def test_assembler_strict_types(self):
        with self.assertRaises(ShadowInputError):
            build_shadow_reports("not-engine", trade_date="d",
                                 broker_positions={})


class TestSettlementT1SameDay(unittest.TestCase):
    """AUD-R1-002: same-day shadow BUY under T1 cannot sell that day.

    Uses a core_qty=0 symbol with no initial holding, so the ONLY sellable
    quantity is the shadow purchase — which is locked until the next session.
    """

    def _shadow(self):
        strategy = AccumulateStrategy(
            _symbol(core_qty=0, target_qty=100000), _global(),
            session_window=SESSION,
        )
        policy = SettlementPolicy(symbol="0700.HK", rule=SETTLE_T1)
        shadow = ShadowEngine(
            strategy, symbol="0700.HK", settlement_policy=policy,
            core_qty=0,
        )
        shadow.begin_day(_daily_bars(), trade_date="2026-08-12")
        return shadow

    def test_same_day_rebound_cannot_sell(self):
        shadow = self._shadow()
        # Day 1: buy at the dip (fill at close).  Real broker can_use stays 0:
        # the same-day purchase is NOT sellable (T+1, AUD-R1-002).  Caller
        # passes the REAL broker position (0); the engine adds the shadow
        # delta internally.
        d1 = shadow.on_bar(
            _m5(600, 420.0), now="2026-08-12T10:00:00",
            broker_position=0, can_use_qty=0, strategic_extra=0,
            available_cash=500000.0, assume_fill_price=420.0,
            trade_date="2026-08-12",
        )
        self.assertEqual(d1.kind, DecisionKind.BUY_T)
        # Same day rebound: effective sellable = real 0 + released 0 = 0,
        # so the 100-share sell is rejected (INSUFFICIENT_AVAILABLE_VOLUME).
        d2 = shadow.on_bar(
            _m5(605, 445.0), now="2026-08-12T10:05:00",
            broker_position=0, can_use_qty=0, strategic_extra=0,
            available_cash=500000.0, assume_fill_price=445.0,
            trade_date="2026-08-12",
        )
        self.assertEqual(d2.kind, DecisionKind.SELL_REJECTED)
        self.assertEqual(d2.reason, "INSUFFICIENT_AVAILABLE_VOLUME")
        # Shadow delta exists but is hypothetical; no WOULD_SELL was emitted.
        sides = [o.side for o in shadow.shadow_orders]
        self.assertEqual(sides, ["WOULD_BUY"])

    def test_next_day_can_sell(self):
        shadow = self._shadow()
        shadow.on_bar(
            _m5(600, 420.0), now="2026-08-12T10:00:00",
            broker_position=0, can_use_qty=0, strategic_extra=0,
            available_cash=500000.0, assume_fill_price=420.0,
            trade_date="2026-08-12",
        )
        # Next trading day: the locked 100 is released; effective sellable =
        # 0 (real) + 100 (released) = 100, so the rebound may sell.  Feed a
        # realistic two-bar session (low open bar then rebound to target) so
        # the data-quality guard sees an ordered intraday sequence.
        shadow.begin_day(_daily_bars(), trade_date="2026-08-13")
        shadow.on_bar(
            _m5(600, 430.0, day="2026-08-13"), now="2026-08-13T10:00:00",
            broker_position=0, can_use_qty=0, strategic_extra=0,
            available_cash=500000.0, trade_date="2026-08-13",
        )
        d2 = shadow.on_bar(
            _m5(605, 445.0, day="2026-08-13"), now="2026-08-13T10:05:00",
            broker_position=0, can_use_qty=0, strategic_extra=0,
            available_cash=500000.0, assume_fill_price=445.0,
            trade_date="2026-08-13",
        )
        self.assertEqual(d2.kind, DecisionKind.SELL_T)
        sides = [o.side for o in shadow.shadow_orders]
        self.assertEqual(sides, ["WOULD_BUY", "WOULD_SELL"])


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
