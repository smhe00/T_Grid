"""Tests for tgrid.config: success paths and fail-closed failure injection."""

import os
import tempfile
import unittest
from pathlib import Path

from tgrid import (
    ConfigError,
    GlobalConfig,
    RootConfig,
    SymbolConfig,
    load_config,
    parse_config,
)

EXAMPLE_CONFIG = Path(__file__).resolve().parents[2] / "config" / "config.example.yaml"


def _valid_global(**overrides):
    cfg = {
        "live_trading": False,
        "database": "data/tgrid.db",
        "log_dir": "logs",
        "bar_period": "5m",
        "order_timeout_seconds": 120,
        "skip_open_minutes": 15,
        "skip_close_minutes": 15,
        "volatility_halt_atr": 2.5,
        "minimum_cash_buffer": 50000.0,
    }
    cfg.update(overrides)
    return cfg


def _valid_symbol(**overrides):
    cfg = {
        "enabled": True,
        "mode": "ACCUMULATE",
        "core_qty": 600,
        "target_qty": 1100,
        "t_unit": 100,
        "lot_size": 100,
        "price_tick": 0.2,
        "max_t_lots": 2,
        "max_t_capital": 200000.0,
        "anchor": "VWAP20",
        "atr_period": 14,
        "atr_k": 1.20,
        "min_grid": 0.040,
        "max_grid": 0.080,
        "exit_multiple": 1.15,
    }
    cfg.update(overrides)
    return cfg


def _valid_root(**overrides):
    cfg = {
        "global": _valid_global(),
        "symbols": {"0700.HK": _valid_symbol()},
    }
    cfg.update(overrides)
    return cfg


def _load_yaml_string(content):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cfg.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return load_config(path)


def _valid_yaml_text():
    return (
        "global:\n"
        "  live_trading: false\n"
        "  database: data/tgrid.db\n"
        "  log_dir: logs\n"
        "  bar_period: 5m\n"
        "  order_timeout_seconds: 120\n"
        "  skip_open_minutes: 15\n"
        "  skip_close_minutes: 15\n"
        "  volatility_halt_atr: 2.5\n"
        "  minimum_cash_buffer: 0.0\n"
        "symbols:\n"
        "  0700.HK:\n"
        "    enabled: true\n"
        "    mode: ACCUMULATE\n"
        "    core_qty: 600\n"
        "    target_qty: 1100\n"
        "    t_unit: 100\n"
        "    lot_size: 100\n"
        "    price_tick: 0.2\n"
        "    max_t_lots: 2\n"
        "    max_t_capital: 200000.0\n"
        "    anchor: VWAP20\n"
        "    atr_period: 14\n"
        "    atr_k: 1.20\n"
        "    min_grid: 0.040\n"
        "    max_grid: 0.080\n"
        "    exit_multiple: 1.15\n"
    )


class TestLoadConfig(unittest.TestCase):
    def test_load_example_config_success(self):
        cfg = load_config(str(EXAMPLE_CONFIG))
        self.assertIsInstance(cfg, RootConfig)
        self.assertIsInstance(cfg.global_config, GlobalConfig)
        self.assertIn("0700.HK", cfg.symbols)
        self.assertIn("000333.SZ", cfg.symbols)
        self.assertIsInstance(cfg.symbols["0700.HK"], SymbolConfig)

    def test_load_returns_typed_values(self):
        cfg = parse_config(_valid_root())
        self.assertIs(cfg.global_config.live_trading, False)
        self.assertEqual(cfg.global_config.order_timeout_seconds, 120)
        self.assertEqual(cfg.symbols["0700.HK"].core_qty, 600)
        self.assertEqual(cfg.symbols["0700.HK"].mode, "ACCUMULATE")

    def test_default_live_trading_false(self):
        root = _valid_root()
        del root["global"]["live_trading"]
        cfg = parse_config(root)
        self.assertIs(cfg.global_config.live_trading, False)

    def test_live_trading_true_is_explicit(self):
        root = _valid_root()
        root["global"] = _valid_global(live_trading=True)
        cfg = parse_config(root)
        self.assertIs(cfg.global_config.live_trading, True)

    def test_lot_size_and_price_tick_not_hardcoded(self):
        # Two symbols with different lot sizes / ticks parse independently.
        root = _valid_root()
        root["symbols"] = {
            "0700.HK": _valid_symbol(lot_size=100, price_tick=0.2),
            "000001.SZ": _valid_symbol(lot_size=1, price_tick=0.001, t_unit=5),
        }
        cfg = parse_config(root)
        self.assertEqual(cfg.symbols["0700.HK"].price_tick, 0.2)
        self.assertEqual(cfg.symbols["000001.SZ"].price_tick, 0.001)
        self.assertEqual(cfg.symbols["000001.SZ"].lot_size, 1)


class TestModeValidation(unittest.TestCase):
    def test_neutral_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(mode="NEUTRAL")}))

    def test_distribute_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(mode="DISTRIBUTE")}))

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(mode="FLIP")}))


class TestIntegerStrictness(unittest.TestCase):
    def test_t_unit_not_multiple_of_lot_size_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(t_unit=150, lot_size=100)}))

    def test_bool_as_int_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(t_unit=True)}))

    def test_float_as_int_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(core_qty=600.0)}))

    def test_negative_core_qty_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(core_qty=-1)}))

    def test_max_t_lots_less_than_one_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(max_t_lots=0)}))


class TestNumericBounds(unittest.TestCase):
    def test_zero_price_tick_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(price_tick=0.0)}))

    def test_negative_price_tick_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(price_tick=-0.01)}))

    def test_nan_price_tick_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(price_tick=float("nan"))}))

    def test_infinity_price_tick_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(price_tick=float("inf"))}))

    def test_target_less_than_core_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(core_qty=600, target_qty=500)}))

    def test_max_grid_less_than_min_grid_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(min_grid=0.08, max_grid=0.04)}))


class TestStructuralValidation(unittest.TestCase):
    def test_unknown_global_field_rejected(self):
        root = _valid_root()
        root["global"] = _valid_global(bogus_key=1)
        with self.assertRaises(ConfigError):
            parse_config(root)

    def test_unknown_symbol_field_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(bogus_key=1)}))

    def test_unknown_root_field_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(bogus=1))

    def test_missing_symbol_field_rejected(self):
        sym = _valid_symbol()
        del sym["core_qty"]
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": sym}))

    def test_missing_symbols_section_rejected(self):
        root = _valid_root()
        del root["symbols"]
        with self.assertRaises(ConfigError):
            parse_config(root)

    def test_root_not_mapping_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(["global", "symbols"])
        with self.assertRaises(ConfigError):
            parse_config("not-a-mapping")

    def test_symbols_not_mapping_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols=["0700.HK"]))

    def test_error_includes_field_path(self):
        with self.assertRaises(ConfigError) as ctx:
            parse_config(_valid_root(symbols={"X": _valid_symbol(t_unit=True)}))
        self.assertIn("t_unit", str(ctx.exception))


class TestFailureInjection(unittest.TestCase):
    def test_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "does_not_exist.yaml")
            with self.assertRaises(ConfigError):
                load_config(missing)

    def test_yaml_syntax_corrupt(self):
        with self.assertRaises(ConfigError):
            _load_yaml_string("symbols: [unclosed\n")

    def test_root_not_mapping_via_file(self):
        with self.assertRaises(ConfigError):
            _load_yaml_string("- global\n- symbols\n")

    def test_unknown_key_via_file(self):
        content = (
            "global:\n  live_trading: false\n  database: data/tgrid.db\n"
            "  log_dir: logs\n  bar_period: 5m\n  order_timeout_seconds: 120\n"
            "  skip_open_minutes: 15\n  skip_close_minutes: 15\n"
            "  volatility_halt_atr: 2.5\n  minimum_cash_buffer: 0.0\n  bogus: 1\n"
            "symbols:\n  0700.HK:\n"
        )
        # The bogus key triggers before symbols parsing completes.
        with self.assertRaises(ConfigError):
            _load_yaml_string(content)

    def test_t_unit_true_via_file(self):
        content = (
            "global:\n  live_trading: false\n  database: data/tgrid.db\n"
            "  log_dir: logs\n  bar_period: 5m\n  order_timeout_seconds: 120\n"
            "  skip_open_minutes: 15\n  skip_close_minutes: 15\n"
            "  volatility_halt_atr: 2.5\n  minimum_cash_buffer: 0.0\n"
            "symbols:\n  0700.HK:\n"
            "    enabled: true\n    mode: ACCUMULATE\n    core_qty: 600\n"
            "    target_qty: 1100\n    t_unit: true\n    lot_size: 100\n"
            "    price_tick: 0.2\n    max_t_lots: 2\n    max_t_capital: 200000.0\n"
            "    anchor: VWAP20\n    atr_period: 14\n    atr_k: 1.20\n"
            "    min_grid: 0.040\n    max_grid: 0.080\n    exit_multiple: 1.15\n"
        )
        with self.assertRaises(ConfigError):
            _load_yaml_string(content)

    def test_price_tick_nan_via_file(self):
        content = (
            "global:\n  live_trading: false\n  database: data/tgrid.db\n"
            "  log_dir: logs\n  bar_period: 5m\n  order_timeout_seconds: 120\n"
            "  skip_open_minutes: 15\n  skip_close_minutes: 15\n"
            "  volatility_halt_atr: 2.5\n  minimum_cash_buffer: 0.0\n"
            "symbols:\n  0700.HK:\n"
            "    enabled: true\n    mode: ACCUMULATE\n    core_qty: 600\n"
            "    target_qty: 1100\n    t_unit: 100\n    lot_size: 100\n"
            "    price_tick: .nan\n    max_t_lots: 2\n    max_t_capital: 200000.0\n"
            "    anchor: VWAP20\n    atr_period: 14\n    atr_k: 1.20\n"
            "    min_grid: 0.040\n    max_grid: 0.080\n    exit_multiple: 1.15\n"
        )
        with self.assertRaises(ConfigError):
            _load_yaml_string(content)

    def test_invalid_mode_via_file(self):
        content = (
            "global:\n  live_trading: false\n  database: data/tgrid.db\n"
            "  log_dir: logs\n  bar_period: 5m\n  order_timeout_seconds: 120\n"
            "  skip_open_minutes: 15\n  skip_close_minutes: 15\n"
            "  volatility_halt_atr: 2.5\n  minimum_cash_buffer: 0.0\n"
            "symbols:\n  0700.HK:\n"
            "    enabled: true\n    mode: NEUTRAL\n    core_qty: 600\n"
            "    target_qty: 1100\n    t_unit: 100\n    lot_size: 100\n"
            "    price_tick: 0.2\n    max_t_lots: 2\n    max_t_capital: 200000.0\n"
            "    anchor: VWAP20\n    atr_period: 14\n    atr_k: 1.20\n"
            "    min_grid: 0.040\n    max_grid: 0.080\n    exit_multiple: 1.15\n"
        )
        with self.assertRaises(ConfigError):
            _load_yaml_string(content)


class TestDuplicateKeys(unittest.TestCase):
    def test_duplicate_live_trading_rejected(self):
        content = _valid_yaml_text().replace(
            "  live_trading: false\n", "  live_trading: false\n  live_trading: true\n"
        )
        with self.assertRaises(ConfigError) as ctx:
            _load_yaml_string(content)
        self.assertIn("duplicate", str(ctx.exception))
        self.assertIn("live_trading", str(ctx.exception))

    def test_duplicate_core_qty_rejected(self):
        content = _valid_yaml_text().replace(
            "    core_qty: 600\n", "    core_qty: 600\n    core_qty: 0\n"
        )
        with self.assertRaises(ConfigError) as ctx:
            _load_yaml_string(content)
        self.assertIn("duplicate", str(ctx.exception))
        self.assertIn("core_qty", str(ctx.exception))

    def test_duplicate_symbol_rejected(self):
        content = _valid_yaml_text() + (
            "  0700.HK:\n"
            "    enabled: false\n"
            "    mode: ACCUMULATE\n"
            "    core_qty: 0\n"
            "    target_qty: 0\n"
            "    t_unit: 100\n"
            "    lot_size: 100\n"
            "    price_tick: 0.2\n"
            "    max_t_lots: 2\n"
            "    max_t_capital: 200000.0\n"
            "    anchor: VWAP20\n"
            "    atr_period: 14\n"
            "    atr_k: 1.20\n"
            "    min_grid: 0.040\n"
            "    max_grid: 0.080\n"
            "    exit_multiple: 1.15\n"
        )
        with self.assertRaises(ConfigError) as ctx:
            _load_yaml_string(content)
        self.assertIn("duplicate", str(ctx.exception))
        self.assertIn("0700.HK", str(ctx.exception))

    def test_duplicate_key_error_includes_location(self):
        content = _valid_yaml_text().replace(
            "  live_trading: false\n", "  live_trading: false\n  live_trading: true\n"
        )
        with self.assertRaises(ConfigError) as ctx:
            _load_yaml_string(content)
        self.assertIn("line", str(ctx.exception))

    def test_duplicate_root_global_rejected(self):
        # REV-G0-007: root-level duplicate `global` section.
        content = _valid_yaml_text().replace(
            "global:\n", "global:\n  live_trading: false\nglobal:\n", 1
        )
        with self.assertRaises(ConfigError) as ctx:
            _load_yaml_string(content)
        self.assertIn("duplicate", str(ctx.exception))
        self.assertIn("global", str(ctx.exception))
        self.assertIn("line", str(ctx.exception))

    def test_unhashable_sequence_key_rejected(self):
        # REV-G0-006: a list used as a mapping key must fail closed as ConfigError.
        content = (
            "? [a, b]\n"
            ": value\n"
            "global:\n"
            "  live_trading: false\n"
        )
        with self.assertRaises(ConfigError) as ctx:
            _load_yaml_string(content)
        self.assertIn("line", str(ctx.exception))
        self.assertIn("key", str(ctx.exception).lower())

    def test_unhashable_key_does_not_leak_type_error(self):
        content = "? [a, b]\n: value\n"
        with self.assertRaises(ConfigError):
            _load_yaml_string(content)


class TestEnumValidation(unittest.TestCase):
    def test_bar_period_tick_rejected(self):
        root = _valid_root()
        root["global"] = _valid_global(bar_period="tick")
        with self.assertRaises(ConfigError):
            parse_config(root)

    def test_bar_period_1m_rejected(self):
        root = _valid_root()
        root["global"] = _valid_global(bar_period="1m")
        with self.assertRaises(ConfigError):
            parse_config(root)

    def test_bar_period_5m_accepted(self):
        root = _valid_root()
        root["global"] = _valid_global(bar_period="5m")
        cfg = parse_config(root)
        self.assertEqual(cfg.global_config.bar_period, "5m")

    def test_anchor_unsupported_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config(_valid_root(symbols={"X": _valid_symbol(anchor="UNSUPPORTED")}))

    def test_anchor_vwap20_accepted(self):
        cfg = parse_config(_valid_root(symbols={"X": _valid_symbol(anchor="VWAP20")}))
        self.assertEqual(cfg.symbols["X"].anchor, "VWAP20")

    def test_anchor_ema20_accepted(self):
        cfg = parse_config(_valid_root(symbols={"X": _valid_symbol(anchor="EMA20")}))
        self.assertEqual(cfg.symbols["X"].anchor, "EMA20")

    def test_anchor_error_includes_allowed_values(self):
        with self.assertRaises(ConfigError) as ctx:
            parse_config(_valid_root(symbols={"X": _valid_symbol(anchor="UNSUPPORTED")}))
        self.assertIn("VWAP20", str(ctx.exception))
        self.assertIn("EMA20", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
