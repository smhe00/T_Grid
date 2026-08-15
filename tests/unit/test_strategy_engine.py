"""Tests for tgrid.strategy.engine — ACCUMULATE engine + design §38 scenarios.

Covers the four mandatory design scenarios:

* Scenario A: 440 -> 420 -> 445  -> BUY T, SELL T, CORE unchanged
* Scenario B: 440 -> 420 -> 400  -> 2 T lots max, then stop
* Scenario C: 440 -> 400 gap     -> VOLATILITY_HALT
* Scenario D: T-lot exists + Core Floor insufficient -> SELL rejected
"""

import unittest

from tgrid.models import GlobalConfig, SymbolConfig
from tgrid.strategy.bars import Bar, SessionWindow
from tgrid.strategy.engine import AccumulateStrategy, DecisionKind, Reason
from tgrid.strategy.exceptions import StrategyInputError
from tgrid.strategy.halts import EventBlockRule


def _global(**overrides):
    cfg = dict(
        live_trading=False,
        database="data/tgrid.db",
        log_dir="logs",
        bar_period="5m",
        order_timeout_seconds=120,
        skip_open_minutes=15,
        skip_close_minutes=15,
        volatility_halt_atr=2.5,
        minimum_cash_buffer=50000.0,
    )
    cfg.update(overrides)
    return GlobalConfig(**cfg)


def _symbol(**overrides):
    cfg = dict(
        enabled=True,
        mode="ACCUMULATE",
        core_qty=600,
        target_qty=1100,
        t_unit=100,
        lot_size=100,
        price_tick=0.2,
        max_t_lots=2,
        max_t_capital=200000.0,
        anchor="VWAP20",
        atr_period=14,
        atr_k=1.2,
        min_grid=0.040,
        max_grid=0.080,
        exit_multiple=1.15,
    )
    cfg.update(overrides)
    return SymbolConfig(**cfg)


SESSION = SessionWindow(open_minute=570, close_minute=900)  # 09:30-15:00


def _daily_bars(close=440.0, high=446.0, low=434.0, n=25, volume=1000):
    """Synthetic daily bars; typical price == close, so VWAP20 == close."""
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


def _ctx(broker=600, **over):
    ctx = dict(
        broker_position=broker, can_use_qty=broker, strategic_extra=0,
        reserved_sell_qty=0, available_cash=500000.0,
    )
    ctx.update(over)
    return ctx


class TestScenarioA(unittest.TestCase):
    """440 -> 420 -> 445: buy below Buy_1, then exit at target; CORE untouched.

    Daily bars: TR=12 -> ATR%=2.73% -> G=4% (min_grid).
    Buy_1 = 440*0.96 = 422.4 >= 420 -> BUY.
    Exit = 420*(1+0.04*1.15) = 439.32 <= 445 -> SELL.
    Halt threshold 6.8% > 4.5% move at 420 -> no halt.
    """

    def setUp(self):
        self.engine = AccumulateStrategy(
            _symbol(), _global(), session_window=SESSION,
        )
        self.engine.begin_day(_daily_bars(), trade_date="2026-08-12")

    def test_no_action_above_buy_level(self):
        decision = self.engine.on_bar(_m5(600, 440.0), now="2026-08-12T10:00:00",
                                      **_ctx())
        self.assertEqual(decision.kind, DecisionKind.NO_ACTION)
        self.assertEqual(decision.reason, Reason.PRICE_ABOVE_BUY_LEVEL)

    def test_buy_at_dip(self):
        decision = self.engine.on_bar(_m5(600, 420.0), now="2026-08-12T10:00:00",
                                      **_ctx())
        self.assertEqual(decision.kind, DecisionKind.BUY_T)
        self.assertEqual(decision.qty, 100)
        self.assertLessEqual(decision.limit_price, 422.4)
        self.engine.record_buy_fill("T-001", qty=100, price=420.0,
                                    entry_time="2026-08-12T10:00:00")
        self.assertEqual(self.engine.open_lot_count(), 1)

    def test_sell_at_rebound_core_unchanged(self):
        self.engine.on_bar(_m5(600, 420.0), now="2026-08-12T10:00:00", **_ctx())
        self.engine.record_buy_fill("T-001", qty=100, price=420.0,
                                    entry_time="2026-08-12T10:00:00")
        decision = self.engine.on_bar(
            _m5(605, 445.0), now="2026-08-12T10:05:00",
            **_ctx(700),
        )
        self.assertEqual(decision.kind, DecisionKind.SELL_T)
        self.assertEqual(decision.t_lot_id, "T-001")
        self.assertEqual(decision.qty, 100)
        self.assertGreaterEqual(decision.limit_price, 439.32)
        self.engine.record_sell_fill("T-001", price=440.0,
                                     exit_time="2026-08-12T10:05:00")
        self.assertEqual(self.engine.open_lot_count(), 0)
        # Core is untouched: snapshot core always comes from SymbolConfig.
        self.assertEqual(self.engine.daily_basis.anchor, 440.0)


class TestScenarioB(unittest.TestCase):
    """440 -> 420 -> 400: two T lots max, then T_CAPACITY_FULL.

    Daily bars: TR=24.4 -> ATR%=5.55%.  atr_k=0.8 -> G=4.44%.
    Buy_1 = 440*0.9556 = 420.5 >= 420; Buy_2 = 440*0.9556^2 = 401.8 >= 400.
    Buy_3 = 440*0.9556^3 = 383.9 >= 380 -> but capacity full.
    Halt threshold = 2.5*5.55% = 13.9% > 13.6% move at 380 -> no halt,
    so T_CAPACITY_FULL is genuinely reachable.
    """

    def setUp(self):
        self.engine = AccumulateStrategy(
            _symbol(atr_k=0.8), _global(), session_window=SESSION,
        )
        self.engine.begin_day(
            _daily_bars(high=452.2, low=427.8), trade_date="2026-08-12",
        )

    def test_two_lots_then_capacity_full(self):
        d1 = self.engine.on_bar(_m5(600, 420.0), now="2026-08-12T10:00:00",
                                **_ctx(600))
        self.assertEqual(d1.kind, DecisionKind.BUY_T)
        self.engine.record_buy_fill("T-001", qty=100, price=420.0,
                                    entry_time="2026-08-12T10:00:00")
        d2 = self.engine.on_bar(_m5(605, 400.0), now="2026-08-12T10:05:00",
                                **_ctx(700))
        self.assertEqual(d2.kind, DecisionKind.BUY_T)
        self.engine.record_buy_fill("T-002", qty=100, price=400.0,
                                    entry_time="2026-08-12T10:05:00")
        self.assertEqual(self.engine.open_lot_count(), 2)
        d3 = self.engine.on_bar(_m5(610, 380.0), now="2026-08-12T10:10:00",
                                **_ctx(800))
        self.assertEqual(d3.kind, DecisionKind.BUY_REJECTED)
        self.assertEqual(d3.reason, Reason.T_CAPACITY_FULL)
        self.assertEqual(self.engine.open_lot_count(), 2)


class TestScenarioC(unittest.TestCase):
    """440 -> 400 gap: VOLATILITY_HALT, no new T-lot.

    Calm daily bars (TR=2 -> ATR%=0.45%): halt threshold 1.1% << 9.1% gap.
    """

    def setUp(self):
        self.engine = AccumulateStrategy(
            _symbol(), _global(), session_window=SESSION,
        )
        self.engine.begin_day(
            _daily_bars(high=441.0, low=439.0), trade_date="2026-08-12",
        )

    def test_gap_triggers_volatility_halt(self):
        decision = self.engine.on_bar(_m5(600, 400.0),
                                      now="2026-08-12T10:00:00", **_ctx())
        self.assertEqual(decision.kind, DecisionKind.HALTED)
        self.assertEqual(decision.reason, Reason.VOLATILITY_HALT)

    def test_halt_persists_for_the_day(self):
        self.engine.on_bar(_m5(600, 400.0), now="2026-08-12T10:00:00", **_ctx())
        decision = self.engine.on_bar(_m5(605, 420.0),
                                      now="2026-08-12T10:05:00", **_ctx())
        self.assertEqual(decision.kind, DecisionKind.HALTED)
        self.assertEqual(decision.reason, Reason.VOLATILITY_HALT)


class TestScenarioD(unittest.TestCase):
    """T-lot exists + Core Floor insufficient -> SELL rejected."""

    def setUp(self):
        self.engine = AccumulateStrategy(
            _symbol(), _global(), session_window=SESSION,
        )
        self.engine.begin_day(_daily_bars(), trade_date="2026-08-12")
        self.engine.on_bar(_m5(600, 420.0), now="2026-08-12T10:00:00", **_ctx())
        self.engine.record_buy_fill("T-001", qty=100, price=420.0,
                                    entry_time="2026-08-12T10:00:00")

    def test_core_floor_breach_rejects_sell(self):
        decision = self.engine.on_bar(
            _m5(605, 445.0), now="2026-08-12T10:05:00",
            **_ctx(500),
        )
        self.assertEqual(decision.kind, DecisionKind.SELL_REJECTED)
        self.assertEqual(decision.reason, Reason.CORE_FLOOR)
        self.assertEqual(self.engine.open_lot_count(), 1)

    def test_insufficient_available_volume_rejects_sell(self):
        decision = self.engine.on_bar(
            _m5(605, 445.0), now="2026-08-12T10:05:00",
            **_ctx(700, can_use_qty=50),
        )
        self.assertEqual(decision.kind, DecisionKind.SELL_REJECTED)
        self.assertEqual(decision.reason, Reason.INSUFFICIENT_AVAILABLE_VOLUME)

    def test_sell_reservation_conflict_rejects_sell(self):
        decision = self.engine.on_bar(
            _m5(605, 445.0), now="2026-08-12T10:05:00",
            **_ctx(700, reserved_sell_qty=100),
        )
        self.assertEqual(decision.kind, DecisionKind.SELL_REJECTED)
        self.assertEqual(decision.reason, Reason.SELL_RESERVATION_CONFLICT)

    def test_position_invariant_rejects_sell(self):
        decision = self.engine.on_bar(
            _m5(605, 445.0), now="2026-08-12T10:05:00",
            **_ctx(650),
        )
        self.assertEqual(decision.kind, DecisionKind.SELL_REJECTED)
        self.assertEqual(decision.reason, Reason.POSITION_INVARIANT)


class TestEngineGates(unittest.TestCase):
    def setUp(self):
        self.engine = AccumulateStrategy(
            _symbol(), _global(), session_window=SESSION,
        )
        self.engine.begin_day(_daily_bars(), trade_date="2026-08-12")

    def test_no_basis_halts(self):
        engine = AccumulateStrategy(_symbol(), _global(), session_window=SESSION)
        decision = engine.on_bar(_m5(600, 420.0), now="2026-08-12T10:00:00",
                                 **_ctx())
        self.assertEqual(decision.kind, DecisionKind.HALTED)
        self.assertEqual(decision.reason, Reason.NO_BASIS)

    def test_disabled_symbol_rejected(self):
        engine = AccumulateStrategy(
            _symbol(enabled=False), _global(), session_window=SESSION,
        )
        engine.begin_day(_daily_bars(), trade_date="2026-08-12")
        decision = engine.on_bar(_m5(600, 420.0), now="2026-08-12T10:00:00",
                                 **_ctx())
        self.assertEqual(decision.kind, DecisionKind.BUY_REJECTED)
        self.assertEqual(decision.reason, Reason.NOT_ENABLED)

    def test_pending_order_blocks_duplicate(self):
        d1 = self.engine.on_bar(_m5(600, 420.0), now="2026-08-12T10:00:00",
                                **_ctx())
        self.assertEqual(d1.kind, DecisionKind.BUY_T)
        self.engine.mark_buy_pending()
        d2 = self.engine.on_bar(_m5(605, 415.0), now="2026-08-12T10:05:00",
                                **_ctx())
        self.assertEqual(d2.kind, DecisionKind.NO_ACTION)
        self.assertEqual(d2.reason, Reason.PENDING_ORDER)

    def test_target_ceiling_blocks_buy(self):
        decision = self.engine.on_bar(
            _m5(600, 420.0), now="2026-08-12T10:00:00",
            **_ctx(1050),
        )
        self.assertEqual(decision.kind, DecisionKind.BUY_REJECTED)
        self.assertEqual(decision.reason, Reason.TARGET_CEILING)

    def test_insufficient_cash_blocks_buy(self):
        decision = self.engine.on_bar(
            _m5(600, 420.0), now="2026-08-12T10:00:00",
            **_ctx(600, available_cash=60000.0),
        )
        # 100*420 = 42000 > 60000-50000 = 10000 -> rejected
        self.assertEqual(decision.kind, DecisionKind.BUY_REJECTED)
        self.assertEqual(decision.reason, Reason.INSUFFICIENT_CASH)

    def test_time_window_blocks_buy_near_open(self):
        decision = self.engine.on_bar(
            _m5(580, 420.0), now="2026-08-12T09:40:00", **_ctx())
        self.assertEqual(decision.kind, DecisionKind.BUY_REJECTED)
        self.assertEqual(decision.reason, Reason.TIME_WINDOW)

    def test_time_window_blocks_buy_near_close(self):
        decision = self.engine.on_bar(
            _m5(890, 420.0), now="2026-08-12T14:50:00", **_ctx())
        self.assertEqual(decision.kind, DecisionKind.BUY_REJECTED)
        self.assertEqual(decision.reason, Reason.TIME_WINDOW)

    def test_data_quality_halt(self):
        decision = self.engine.on_bar(
            _m5(600, 420.0, volume=0), now="2026-08-12T10:00:00", **_ctx())
        self.assertEqual(decision.kind, DecisionKind.HALTED)
        self.assertEqual(decision.reason, Reason.DATA_HALT)

    def test_event_block_halt(self):
        rule = EventBlockRule(events={"0700.HK": ("2026-08-12",)})
        decision = self.engine.on_bar(
            _m5(600, 420.0), now="2026-08-12T10:00:00",
            event_rule=rule, **_ctx())
        self.assertEqual(decision.kind, DecisionKind.HALTED)
        self.assertEqual(decision.reason, Reason.EVENT_BLOCK)

    def test_lifo_picks_newest_lot(self):
        self.engine.on_bar(_m5(600, 420.0), now="2026-08-12T10:00:00", **_ctx())
        self.engine.record_buy_fill("T-001", qty=100, price=420.0,
                                    entry_time="2026-08-12T10:00:00")
        self.engine.on_bar(_m5(605, 400.0), now="2026-08-12T10:05:00",
                           **_ctx(700))
        self.engine.record_buy_fill("T-002", qty=100, price=400.0,
                                    entry_time="2026-08-12T10:05:00")
        # T-002 target = 400*(1+0.04*1.15) = 418.4; T-001 target = 439.32.
        # At 425 only T-002 qualifies -> LIFO picks T-002.
        decision = self.engine.on_bar(
            _m5(610, 425.0), now="2026-08-12T10:10:00", **_ctx(800))
        self.assertEqual(decision.kind, DecisionKind.SELL_T)
        self.assertEqual(decision.t_lot_id, "T-002")

    def test_record_sell_fill_enforces_lifo(self):
        self.engine.on_bar(_m5(600, 420.0), now="2026-08-12T10:00:00", **_ctx())
        self.engine.record_buy_fill("T-001", qty=100, price=420.0,
                                    entry_time="2026-08-12T10:00:00")
        self.engine.on_bar(_m5(605, 400.0), now="2026-08-12T10:05:00",
                           **_ctx(700))
        self.engine.record_buy_fill("T-002", qty=100, price=400.0,
                                    entry_time="2026-08-12T10:05:00")
        # T-001 is not the newest open lot -> LIFO refuses to close it.
        with self.assertRaises(StrategyInputError):
            self.engine.record_sell_fill("T-001", price=440.0,
                                         exit_time="2026-08-12T10:05:00")
        self.assertEqual(self.engine.open_lot_count(), 2)

    def test_strict_constructor_types(self):
        with self.assertRaises(StrategyInputError):
            AccumulateStrategy("not-config", _global(), session_window=SESSION)
        with self.assertRaises(StrategyInputError):
            AccumulateStrategy(_symbol(), _global(), session_window="09:30")

    def test_open_lots_snapshot_frozen(self):
        self.engine.on_bar(_m5(600, 420.0), now="2026-08-12T10:00:00", **_ctx())
        self.engine.record_buy_fill("T-001", qty=100, price=420.0,
                                    entry_time="2026-08-12T10:00:00")
        lots = self.engine.open_t_lots()
        self.assertEqual(len(lots), 1)
        with self.assertRaises(Exception):
            lots[0].qty = 999  # frozen

    def test_begin_day_requires_daily_bars(self):
        with self.assertRaises(StrategyInputError):
            self.engine.begin_day([], trade_date="2026-08-12")
        with self.assertRaises(StrategyInputError):
            self.engine.begin_day([1, 2, 3], trade_date="2026-08-12")


if __name__ == "__main__":
    unittest.main()
