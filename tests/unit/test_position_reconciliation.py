"""Tests for the offline position reconciliation decision engine (G2-T006).

All tests are pure offline; nothing connects to QMT, SQLite, filesystem, or
network.
"""

import ast
import dataclasses
import unittest
from pathlib import Path

from tgrid.models import SymbolConfig
from tgrid.position import (
    RECONCILED,
    REASON_BROKER_POSITION_MISMATCH,
    REASON_CORE_FLOOR_BREACH,
    REASON_MATCH,
    SAFE_MODE,
    PositionReconciliationResult,
    reconcile_position,
)
from tgrid.risk.exceptions import PositionInvariantError


def _symbol_config(core_qty=600, **overrides):
    data = dict(
        enabled=True,
        mode="ACCUMULATE",
        core_qty=core_qty,
        target_qty=1100,
        t_unit=100,
        lot_size=100,
        price_tick=0.2,
        max_t_lots=2,
        max_t_capital=200000.0,
        anchor="VWAP20",
        atr_period=14,
        atr_k=1.2,
        min_grid=0.04,
        max_grid=0.08,
        exit_multiple=1.15,
    )
    data.update(overrides)
    return SymbolConfig(**data)


def _reconcile(cfg=None, **kwargs):
    kw = dict(
        symbol="600000.SH",
        broker_position=600,
        strategic_extra=0,
        open_t_lot_position=0,
    )
    kw.update(kwargs)
    return reconcile_position(cfg if cfg is not None else _symbol_config(), **kw)


class TestHappyPath(unittest.TestCase):
    def test_zero_only_exact_match(self):
        result = _reconcile(broker_position=600)
        self.assertEqual(result.decision, RECONCILED)
        self.assertEqual(result.reason, REASON_MATCH)
        self.assertEqual(result.local_expected_position, 600)
        self.assertEqual(result.delta, 0)
        self.assertEqual(result.core_qty, 600)
        self.assertEqual(result.strategic_extra, 0)
        self.assertEqual(result.open_t_lot_position, 0)

    def test_core_plus_strategic_match(self):
        result = _reconcile(broker_position=700, strategic_extra=100)
        self.assertEqual(result.decision, RECONCILED)
        self.assertEqual(result.reason, REASON_MATCH)
        self.assertEqual(result.local_expected_position, 700)
        self.assertEqual(result.delta, 0)

    def test_core_plus_t_match(self):
        result = _reconcile(broker_position=700, open_t_lot_position=100)
        self.assertEqual(result.decision, RECONCILED)
        self.assertEqual(result.local_expected_position, 700)
        self.assertEqual(result.delta, 0)

    def test_mixed_match(self):
        result = _reconcile(
            broker_position=800, strategic_extra=100, open_t_lot_position=100
        )
        self.assertEqual(result.decision, RECONCILED)
        self.assertEqual(result.reason, REASON_MATCH)
        self.assertEqual(result.local_expected_position, 800)
        self.assertEqual(result.delta, 0)
        self.assertEqual(result.symbol, "600000.SH")

    def test_result_is_frozen_dataclass(self):
        result = _reconcile()
        self.assertIsInstance(result, PositionReconciliationResult)
        self.assertTrue(dataclasses.is_dataclass(result))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.decision = SAFE_MODE


class TestMismatch(unittest.TestCase):
    def test_positive_delta_mismatch(self):
        result = _reconcile(broker_position=700)
        self.assertEqual(result.decision, SAFE_MODE)
        self.assertEqual(result.reason, REASON_BROKER_POSITION_MISMATCH)
        self.assertEqual(result.delta, 100)
        self.assertEqual(result.local_expected_position, 600)

    def test_negative_delta_mismatch(self):
        result = _reconcile(broker_position=600, strategic_extra=100)
        self.assertEqual(result.decision, SAFE_MODE)
        self.assertEqual(result.reason, REASON_BROKER_POSITION_MISMATCH)
        self.assertEqual(result.delta, -100)
        self.assertEqual(result.local_expected_position, 700)

    def test_delta_equal_to_t_unit_not_reclassified(self):
        # A +100 delta equals the configured t_unit but must never be inferred
        # as an auto T-Lot: still SAFE_MODE / mismatch.
        result = _reconcile(broker_position=700)
        self.assertEqual(result.decision, SAFE_MODE)
        self.assertEqual(result.reason, REASON_BROKER_POSITION_MISMATCH)
        self.assertEqual(result.delta, 100)

    def test_large_delta_mismatch(self):
        result = _reconcile(broker_position=60000)
        self.assertEqual(result.decision, SAFE_MODE)
        self.assertEqual(result.reason, REASON_BROKER_POSITION_MISMATCH)
        self.assertEqual(result.delta, 59400)

    def test_core_floor_breach_priority(self):
        # broker < core wins even when a mismatch reason would also apply.
        result = _reconcile(broker_position=500, open_t_lot_position=100)
        self.assertEqual(result.decision, SAFE_MODE)
        self.assertEqual(result.reason, REASON_CORE_FLOOR_BREACH)
        self.assertEqual(result.local_expected_position, 700)
        self.assertEqual(result.delta, -200)

    def test_core_floor_breach_one_below(self):
        result = _reconcile(broker_position=599)
        self.assertEqual(result.decision, SAFE_MODE)
        self.assertEqual(result.reason, REASON_CORE_FLOOR_BREACH)

    def test_zero_delta_with_zero_components_matches(self):
        result = _reconcile(_symbol_config(core_qty=0), broker_position=0)
        self.assertEqual(result.decision, RECONCILED)
        self.assertEqual(result.reason, REASON_MATCH)
        self.assertEqual(result.delta, 0)


class TestValidation(unittest.TestCase):
    def test_negative_quantities_rejected(self):
        for kwargs in (
            {"broker_position": -1},
            {"strategic_extra": -1},
            {"open_t_lot_position": -1},
        ):
            with self.assertRaises(PositionInvariantError):
                _reconcile(**kwargs)
        with self.assertRaises(PositionInvariantError):
            _reconcile(_symbol_config(core_qty=-1))

    def test_non_int_quantities_rejected(self):
        class IntSub(int):
            pass

        for bad in (True, 1.5, "100", b"100", [100], {"q": 100}, IntSub(100)):
            for field in ("broker_position", "strategic_extra", "open_t_lot_position"):
                with self.assertRaises(
                    PositionInvariantError, msg=f"{field}={bad!r}"
                ):
                    _reconcile(**{field: bad})

    def test_bad_symbol_rejected(self):
        class StrSub(str):
            pass

        for bad in (None, "", "   ", 123, ["600000.SH"], StrSub("600000.SH")):
            with self.assertRaises(PositionInvariantError, msg=f"symbol={bad!r}"):
                _reconcile(symbol=bad)

    def test_fake_and_subclass_symbol_config_rejected(self):
        class FakeConfig:
            core_qty = 600

        class SymbolConfigSub(SymbolConfig):
            pass

        subclass = SymbolConfigSub(
            enabled=True, mode="ACCUMULATE", core_qty=600, target_qty=1100,
            t_unit=100, lot_size=100, price_tick=0.2, max_t_lots=2,
            max_t_capital=200000.0, anchor="VWAP20", atr_period=14, atr_k=1.2,
            min_grid=0.04, max_grid=0.08, exit_multiple=1.15,
        )
        for bad in (FakeConfig(), subclass, None, "config"):
            with self.assertRaises(PositionInvariantError):
                reconcile_position(
                    bad,
                    symbol="600000.SH",
                    broker_position=600,
                    strategic_extra=0,
                    open_t_lot_position=0,
                )

    def test_malicious_quantity_dunder_not_called(self):
        class EvilInt:
            def __int__(self):
                raise RuntimeError("EVIL_INT_SECRET")

            def __index__(self):
                raise RuntimeError("EVIL_INDEX_SECRET")

            def __eq__(self, other):
                raise RuntimeError("EVIL_EQ_SECRET")

        with self.assertRaises(PositionInvariantError) as ctx:
            _reconcile(broker_position=EvilInt())
        self.assertNotIn("EVIL_INT_SECRET", str(ctx.exception))
        self.assertNotIn("EVIL_INDEX_SECRET", str(ctx.exception))
        self.assertNotIn("EVIL_EQ_SECRET", str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertIsNone(ctx.exception.__context__)

    def test_malicious_symbol_dunder_not_called(self):
        class EvilStr:
            def __str__(self):
                raise RuntimeError("EVIL_STR_SECRET")

            def __eq__(self, other):
                raise RuntimeError("EVIL_STR_EQ_SECRET")

        with self.assertRaises(PositionInvariantError) as ctx:
            _reconcile(symbol=EvilStr())
        self.assertNotIn("EVIL_STR_SECRET", str(ctx.exception))
        self.assertNotIn("EVIL_STR_EQ_SECRET", str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertIsNone(ctx.exception.__context__)


class TestNoMutation(unittest.TestCase):
    def test_input_components_unchanged_and_result_data_only(self):
        cfg = _symbol_config(core_qty=600)
        result = _reconcile(
            cfg, broker_position=800, strategic_extra=100, open_t_lot_position=100
        )
        # The result carries the exact validated components; nothing mutated.
        self.assertEqual(
            (result.core_qty, result.strategic_extra, result.open_t_lot_position),
            (600, 100, 100),
        )
        self.assertEqual(cfg.core_qty, 600)
        # The result is frozen data-only: mutation attempt fails.
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.decision = SAFE_MODE


class TestForbiddenCapabilityScan(unittest.TestCase):
    def test_no_forbidden_capability_or_assert(self):
        from tgrid.position import reconciliation as mod

        src = Path(mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(mod.__file__))
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, ast.Assert)], [])
        for token in (
            "sqlite3", "xtquant", "order_stock", "cancel_order",
            "download_history_data", "subscribe_quote", "unsubscribe_quote",
            "socket", "requests.", "urllib", "os.",
        ):
            self.assertNotIn(token, src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(alias.name.split(".")[0], "xtquant")
            elif isinstance(node, ast.ImportFrom):
                self.assertNotEqual((node.module or "").split(".")[0], "xtquant")
            if isinstance(node, ast.Call):
                func = node.func
                name = (
                    func.attr
                    if isinstance(func, ast.Attribute)
                    else (func.id if isinstance(func, ast.Name) else None)
                )
                self.assertNotIn(
                    name,
                    {
                        "order_stock", "cancel_order", "download_history_data",
                        "subscribe_quote", "unsubscribe_quote",
                    },
                )


if __name__ == "__main__":
    unittest.main()
