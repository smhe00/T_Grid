"""Configuration loading and validation for TGrid.

The loader reads a YAML file from an *explicit* caller-supplied path and never
implicitly opens a local config.  Validation is fail-closed: missing fields,
unknown fields, wrong root shape, and out-of-range values all raise
:class:`tgrid.risk.exceptions.ConfigError` with a deterministic field path.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

import yaml

from tgrid.models import (
    ACCUMULATE_MODE,
    ALLOWED_ANCHORS,
    ANCHOR_EMA20,
    ANCHOR_VWAP20,
    BAR_PERIOD_5M,
    GlobalConfig,
    RootConfig,
    SymbolConfig,
)
from tgrid.risk.exceptions import ConfigError


class _StrictSafeLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of last-key-wins."""


def _construct_mapping_strict(loader: _StrictSafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    """Build a mapping while raising :class:`ConfigError` on any duplicate key.

    Mirrors ``yaml.SafeConstructor.construct_mapping`` but records every key and
    rejects a second occurrence, reporting the duplicate key name and its
    line/column so the failure is auditable.
    """
    if isinstance(node, yaml.MappingNode):
        loader.flatten_mapping(node)
    if not isinstance(node, yaml.MappingNode):
        raise ConfigError(
            f"expected a mapping node, found {node.id}", f"line {node.start_mark.line + 1}"
        )
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        # Explicitly verify the key is a hashable scalar (a list/dict/set key is
        # unhashable and would otherwise leak a raw TypeError from `mapping[key]`).
        try:
            hash(key)
        except TypeError:
            mark = key_node.start_mark
            location = f"line {mark.line + 1}, column {mark.column + 1}"
            raise ConfigError(
                f"invalid mapping key {key!r}: key must be a hashable scalar",
                location,
            ) from None
        if key in mapping:
            mark = key_node.start_mark
            location = f"line {mark.line + 1}, column {mark.column + 1}"
            raise ConfigError(f"duplicate key {key!r}", location)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_strict,
)

_GLOBAL_REQUIRED_FIELDS = (
    "database",
    "log_dir",
    "bar_period",
    "order_timeout_seconds",
    "skip_open_minutes",
    "skip_close_minutes",
    "volatility_halt_atr",
    "minimum_cash_buffer",
)

_GLOBAL_ALLOWED_FIELDS = ("live_trading",) + _GLOBAL_REQUIRED_FIELDS

_SYMBOL_REQUIRED_FIELDS = (
    "enabled",
    "mode",
    "core_qty",
    "target_qty",
    "t_unit",
    "lot_size",
    "price_tick",
    "max_t_lots",
    "max_t_capital",
    "anchor",
    "atr_period",
    "atr_k",
    "min_grid",
    "max_grid",
    "exit_multiple",
)


def _require_mapping(value: Any, path: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise ConfigError(f"expected a mapping, got {type(value).__name__}", path)
    return value


def _reject_unknown(raw: Mapping, allowed: Mapping, path: str) -> None:
    extra = sorted(str(k) for k in raw if k not in allowed)
    if extra:
        raise ConfigError(f"unknown field(s): {', '.join(extra)}", path)


def _require_present(raw: Mapping, required: tuple, path: str) -> None:
    missing = sorted(str(k) for k in required if k not in raw)
    if missing:
        raise ConfigError(f"missing required field(s): {', '.join(missing)}", path)


def _require_str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("expected a non-empty string", path)
    return value


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError("expected a boolean", path)
    return value


def _require_int(value: Any, path: str) -> int:
    # ``type() is int`` rejects bool (which subclasses int) and float.
    if type(value) is not int:
        raise ConfigError(f"expected an integer, got {type(value).__name__}", path)
    return value


def _require_float(value: Any, path: str) -> float:
    # Accept int or float literals, but reject bool and non-finite values.
    if isinstance(value, bool):
        raise ConfigError("expected a number, got bool", path)
    if isinstance(value, int):
        value = float(value)
    if not isinstance(value, float):
        raise ConfigError(f"expected a number, got {type(value).__name__}", path)
    if not math.isfinite(value):
        raise ConfigError("must be a finite number", path)
    return value


def _require_positive_int(value: Any, path: str) -> int:
    result = _require_int(value, path)
    if result <= 0:
        raise ConfigError("must be > 0", path)
    return result


def _require_non_negative_int(value: Any, path: str) -> int:
    result = _require_int(value, path)
    if result < 0:
        raise ConfigError("must be >= 0", path)
    return result


def _require_positive_float(value: Any, path: str) -> float:
    result = _require_float(value, path)
    if result <= 0:
        raise ConfigError("must be > 0", path)
    return result


def _require_non_negative_float(value: Any, path: str) -> float:
    result = _require_float(value, path)
    if result < 0:
        raise ConfigError("must be >= 0", path)
    return result


def _parse_global(raw: Mapping) -> GlobalConfig:
    path = "global"
    _reject_unknown(raw, _GLOBAL_ALLOWED_FIELDS, path)
    _require_present(raw, _GLOBAL_REQUIRED_FIELDS, path)

    live_trading = _require_bool(raw.get("live_trading", False), f"{path}.live_trading")
    database = _require_str(raw["database"], f"{path}.database")
    log_dir = _require_str(raw["log_dir"], f"{path}.log_dir")
    bar_period = _require_str(raw["bar_period"], f"{path}.bar_period")
    if bar_period != BAR_PERIOD_5M:
        raise ConfigError(
            f"unsupported bar_period {bar_period!r}; only {BAR_PERIOD_5M!r} is allowed",
            f"{path}.bar_period",
        )

    order_timeout_seconds = _require_positive_int(
        raw["order_timeout_seconds"], f"{path}.order_timeout_seconds"
    )
    skip_open_minutes = _require_non_negative_int(
        raw["skip_open_minutes"], f"{path}.skip_open_minutes"
    )
    skip_close_minutes = _require_non_negative_int(
        raw["skip_close_minutes"], f"{path}.skip_close_minutes"
    )
    volatility_halt_atr = _require_positive_float(
        raw["volatility_halt_atr"], f"{path}.volatility_halt_atr"
    )
    # minimum_cash_buffer may legitimately be zero (no buffer).
    minimum_cash_buffer = _require_non_negative_float(
        raw["minimum_cash_buffer"], f"{path}.minimum_cash_buffer"
    )

    return GlobalConfig(
        live_trading=live_trading,
        database=database,
        log_dir=log_dir,
        bar_period=bar_period,
        order_timeout_seconds=order_timeout_seconds,
        skip_open_minutes=skip_open_minutes,
        skip_close_minutes=skip_close_minutes,
        volatility_halt_atr=volatility_halt_atr,
        minimum_cash_buffer=minimum_cash_buffer,
    )


def _parse_symbol(symbol: str, raw: Any) -> SymbolConfig:
    path = f"symbols.{symbol}"
    _require_mapping(raw, path)
    _reject_unknown(raw, _SYMBOL_REQUIRED_FIELDS, path)
    _require_present(raw, _SYMBOL_REQUIRED_FIELDS, path)

    enabled = _require_bool(raw["enabled"], f"{path}.enabled")

    mode = _require_str(raw["mode"], f"{path}.mode")
    if mode != ACCUMULATE_MODE:
        raise ConfigError(
            f"unsupported mode {mode!r}; only {ACCUMULATE_MODE!r} is allowed", f"{path}.mode"
        )

    core_qty = _require_non_negative_int(raw["core_qty"], f"{path}.core_qty")
    target_qty = _require_non_negative_int(raw["target_qty"], f"{path}.target_qty")
    if target_qty < core_qty:
        raise ConfigError(
            f"target_qty ({target_qty}) must be >= core_qty ({core_qty})", f"{path}.target_qty"
        )

    t_unit = _require_positive_int(raw["t_unit"], f"{path}.t_unit")
    lot_size = _require_positive_int(raw["lot_size"], f"{path}.lot_size")
    if t_unit % lot_size != 0:
        raise ConfigError(
            f"t_unit ({t_unit}) must be a multiple of lot_size ({lot_size})", f"{path}.t_unit"
        )

    price_tick = _require_positive_float(raw["price_tick"], f"{path}.price_tick")
    max_t_lots = _require_positive_int(raw["max_t_lots"], f"{path}.max_t_lots")
    if max_t_lots < 1:
        raise ConfigError("must be >= 1", f"{path}.max_t_lots")
    max_t_capital = _require_positive_float(raw["max_t_capital"], f"{path}.max_t_capital")

    anchor = _require_str(raw["anchor"], f"{path}.anchor")
    if anchor not in ALLOWED_ANCHORS:
        allowed = sorted(ALLOWED_ANCHORS)
        raise ConfigError(
            f"unsupported anchor {anchor!r}; allowed values: {allowed}", f"{path}.anchor"
        )
    atr_period = _require_positive_int(raw["atr_period"], f"{path}.atr_period")
    atr_k = _require_positive_float(raw["atr_k"], f"{path}.atr_k")
    min_grid = _require_positive_float(raw["min_grid"], f"{path}.min_grid")
    max_grid = _require_positive_float(raw["max_grid"], f"{path}.max_grid")
    if max_grid < min_grid:
        raise ConfigError(
            f"max_grid ({max_grid}) must be >= min_grid ({min_grid})", f"{path}.max_grid"
        )
    exit_multiple = _require_positive_float(raw["exit_multiple"], f"{path}.exit_multiple")

    return SymbolConfig(
        enabled=enabled,
        mode=mode,
        core_qty=core_qty,
        target_qty=target_qty,
        t_unit=t_unit,
        lot_size=lot_size,
        price_tick=price_tick,
        max_t_lots=max_t_lots,
        max_t_capital=max_t_capital,
        anchor=anchor,
        atr_period=atr_period,
        atr_k=atr_k,
        min_grid=min_grid,
        max_grid=max_grid,
        exit_multiple=exit_multiple,
    )


def parse_config(data: Any) -> RootConfig:
    """Validate an already-deserialized mapping and return a :class:`RootConfig`.

    ``data`` must be a mapping with exactly the top-level ``global`` and
    ``symbols`` sections.
    """
    path = "<root>"
    root = _require_mapping(data, path)
    _reject_unknown(root, ("global", "symbols"), path)
    _require_present(root, ("global", "symbols"), path)

    global_raw = _require_mapping(root["global"], "global")
    symbols_raw = _require_mapping(root["symbols"], "symbols")

    global_config = _parse_global(global_raw)
    symbols = {}
    for symbol, symbol_raw in symbols_raw.items():
        symbol_key = _require_str(symbol, "symbols")
        symbols[symbol_key] = _parse_symbol(symbol_key, symbol_raw)

    return RootConfig(global_config=global_config, symbols=symbols)


def load_config(path: str) -> RootConfig:
    """Load, parse, and validate a TGrid configuration from ``path``.

    ``path`` must be supplied explicitly by the caller; no default or implicit
    local config file is ever read.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=_StrictSafeLoader)
    except OSError as exc:
        raise ConfigError(f"cannot read config file: {exc}", str(path)) from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML: {exc}", str(path)) from exc

    return parse_config(data)
