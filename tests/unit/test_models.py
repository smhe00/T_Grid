"""Tests for tgrid.models and tgrid.risk.exceptions."""

import ast
import dataclasses
import unittest
from pathlib import Path

from tgrid import (
    ACCUMULATE_MODE,
    CashReservationConflict,
    ConfigError,
    CoreFloorViolation,
    GlobalConfig,
    InsufficientAvailableVolume,
    RiskError,
    RootConfig,
    SellReservationConflict,
    SymbolConfig,
    TGridError,
)


def _make_global() -> GlobalConfig:
    return GlobalConfig(
        live_trading=False,
        database="data/tgrid.db",
        log_dir="logs",
        bar_period="5m",
        order_timeout_seconds=120,
        skip_open_minutes=15,
        skip_close_minutes=15,
        volatility_halt_atr=2.5,
        minimum_cash_buffer=0.0,
    )


def _make_symbol() -> SymbolConfig:
    return SymbolConfig(
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
        atr_k=1.20,
        min_grid=0.040,
        max_grid=0.080,
        exit_multiple=1.15,
    )


class TestModels(unittest.TestCase):
    def test_accumulate_mode_constant(self):
        self.assertEqual(ACCUMULATE_MODE, "ACCUMULATE")

    def test_models_are_frozen(self):
        global_cfg = _make_global()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            global_cfg.live_trading = True
        symbol = _make_symbol()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            symbol.core_qty = 0

    def test_root_config_shape(self):
        root = RootConfig(global_config=_make_global(), symbols={"0700.HK": _make_symbol()})
        self.assertIs(root.global_config.live_trading, False)
        self.assertEqual(root.symbols["0700.HK"].mode, "ACCUMULATE")


class TestSymbolsReadOnly(unittest.TestCase):
    """REV-G0-002: a validated RootConfig must expose a read-only symbol map."""

    def _root(self):
        return RootConfig(global_config=_make_global(), symbols={"0700.HK": _make_symbol()})

    def test_symbols_clear_raises(self):
        root = self._root()
        # mappingproxy exposes no `clear` mutator at all.
        with self.assertRaises(AttributeError):
            root.symbols.clear()
        # Original contents are untouched after the failed mutation.
        self.assertIn("0700.HK", root.symbols)
        self.assertEqual(root.symbols["0700.HK"].core_qty, 600)

    def test_symbols_pop_raises(self):
        root = self._root()
        with self.assertRaises(AttributeError):
            root.symbols.pop("0700.HK")
        self.assertIn("0700.HK", root.symbols)

    def test_symbols_item_assignment_raises(self):
        root = self._root()
        with self.assertRaises(TypeError):
            root.symbols["0700.HK"] = _make_symbol()
        self.assertEqual(root.symbols["0700.HK"].core_qty, 600)

    def test_symbols_update_raises(self):
        root = self._root()
        with self.assertRaises(AttributeError):
            root.symbols.update({"X": _make_symbol()})
        self.assertNotIn("X", root.symbols)

    def test_symbols_attribute_reassignment_raises(self):
        root = self._root()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            root.symbols = {}

    def test_underlying_original_dict_is_not_aliased(self):
        # A caller-supplied dict must not let the caller mutate through it.
        original = {"0700.HK": _make_symbol()}
        root = RootConfig(global_config=_make_global(), symbols=original)
        original["0700.HK"] = dataclasses.replace(_make_symbol(), core_qty=999)
        # The validated config kept a private copy, unaffected by the caller.
        self.assertEqual(root.symbols["0700.HK"].core_qty, 600)


class TestRiskExceptions(unittest.TestCase):
    def test_hierarchy(self):
        self.assertTrue(issubclass(ConfigError, TGridError))
        self.assertTrue(issubclass(RiskError, TGridError))
        for exc in (
            CoreFloorViolation,
            InsufficientAvailableVolume,
            SellReservationConflict,
            CashReservationConflict,
        ):
            self.assertTrue(issubclass(exc, RiskError))

    def test_each_exception_is_distinctly_catchable(self):
        with self.assertRaises(CoreFloorViolation):
            raise CoreFloorViolation("would breach core floor")
        with self.assertRaises(InsufficientAvailableVolume):
            raise InsufficientAvailableVolume("not enough available volume")
        with self.assertRaises(SellReservationConflict):
            raise SellReservationConflict("sell reservation conflict")
        with self.assertRaises(CashReservationConflict):
            raise CashReservationConflict("cash reservation conflict")

    def test_config_error_carries_field_path(self):
        exc = ConfigError("must be > 0", "symbols.0700.HK.price_tick")
        self.assertEqual(exc.field_path, "symbols.0700.HK.price_tick")
        self.assertIn("price_tick", str(exc))


class TestNoAssertSafety(unittest.TestCase):
    """INV-011: safety enforcement must not rely on Python ``assert``."""

    SOURCE_FILES = [
        "src/tgrid/config.py",
        "src/tgrid/models.py",
        "src/tgrid/risk/exceptions.py",
    ]

    def test_no_assert_statement_in_safety_paths(self):
        # REV-G0-005: use AST rather than line-prefix matching so that
        # ``assert(...)``, multiline asserts, etc. are all detected.
        project_root = Path(__file__).resolve().parents[2]
        for rel in self.SOURCE_FILES:
            source = (project_root / rel).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel)
            asserts = [
                (node.lineno, node.col_offset) for node in ast.walk(tree) if isinstance(node, ast.Assert)
            ]
            self.assertEqual([], asserts, f"assert statement(s) found in {rel}: {asserts}")


if __name__ == "__main__":
    unittest.main()
