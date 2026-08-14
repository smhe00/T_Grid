"""Tests for the offline immutable Core Position Guard (G2-T001).

All tests use pure synthetic data; nothing here imports XtQuant, touches a
database, or accesses any account/market.
"""

import ast
import unittest
from pathlib import Path

from tgrid import (
    CorePositionGuard,
    PositionInvariantError,
    PositionSnapshot,
    SymbolConfig,
    TGridError,
    snapshot_from_symbol_config,
)
from tgrid.risk.exceptions import (
    CoreFloorViolation,
    InsufficientAvailableVolume,
    RiskError,
    SellReservationConflict,
)


def _snap(
    *,
    broker=700,
    core=600,
    strategic=0,
    open_t=100,
    can_use=700,
    reserved=0,
    symbol="600000.SH",
):
    return PositionSnapshot(
        symbol=symbol,
        broker_position=broker,
        core_position=core,
        strategic_extra=strategic,
        open_t_lot_position=open_t,
        can_use_qty=can_use,
        reserved_sell_qty=reserved,
    )


class _EvilInt(int):
    """An int subclass whose custom conversions must never be invoked."""

    def __str__(self):
        raise RuntimeError("EVIL_STR_SECRET")

    def __repr__(self):
        raise RuntimeError("EVIL_REPR_SECRET")

    def __int__(self):
        raise RuntimeError("EVIL_INT_SECRET")


class _EvilStr(str):
    def __str__(self):
        raise RuntimeError("EVIL_SYMBOL_STR_SECRET")


class TestValidDecomposition(unittest.TestCase):
    def test_legal_broker_700_core_600(self):
        s = _snap()
        self.assertEqual(s.broker_position, 700)
        self.assertEqual(s.core_position, 600)
        self.assertEqual(s.strategic_extra, 0)
        self.assertEqual(s.open_t_lot_position, 100)
        self.assertEqual(s.can_use_qty, 700)
        self.assertEqual(s.reserved_sell_qty, 0)

    def test_zero_core(self):
        s = _snap(core=0, broker=100, open_t=100)
        self.assertEqual(s.available_headroom(), 100)

    def test_zero_t_lots(self):
        s = _snap(open_t=0, broker=600)
        self.assertEqual(s.open_t_lot_position, 0)
        self.assertEqual(s.available_headroom(), 0)

    def test_strategic_extra_nonzero(self):
        s = _snap(strategic=50, broker=750, open_t=100)
        self.assertEqual(s.strategic_extra, 50)

    def test_headroom_formula(self):
        self.assertEqual(_snap().available_headroom(), 100)
        self.assertEqual(_snap(broker=650, open_t=50).available_headroom(), 50)


class TestAvailableTQty(unittest.TestCase):
    def test_can_use_binding(self):
        s = _snap(can_use=50)
        self.assertEqual(s.available_t_qty, 50)

    def test_headroom_binding(self):
        s = _snap(can_use=700, broker=650, open_t=50)
        self.assertEqual(s.available_t_qty, 50)

    def test_reservation_reduces(self):
        s = _snap(can_use=700, reserved=40)
        self.assertEqual(s.available_t_qty, 60)

    def test_exactly_all_reserved(self):
        s = _snap(can_use=700, reserved=100)
        self.assertEqual(s.available_t_qty, 0)

    def test_reservation_cannot_exceed_capacity(self):
        with self.assertRaises(PositionInvariantError):
            _snap(can_use=700, reserved=101)
        with self.assertRaises(PositionInvariantError):
            _snap(can_use=50, reserved=60)

    def test_min_of_can_use_and_headroom(self):
        s = _snap(can_use=30, broker=650, open_t=50)
        self.assertEqual(s.available_t_qty, 30)


class TestFrozen(unittest.TestCase):
    def test_fields_immutable(self):
        s = _snap()
        for attr in (
            "broker_position",
            "core_position",
            "strategic_extra",
            "open_t_lot_position",
            "can_use_qty",
            "reserved_sell_qty",
        ):
            with self.assertRaises(Exception):
                setattr(s, attr, 999)
        self.assertEqual(s.broker_position, 700)
        self.assertEqual(s.core_position, 600)

    def test_symbol_immutable(self):
        s = _snap()
        with self.assertRaises(Exception):
            s.symbol = "OTHER"
        self.assertEqual(s.symbol, "600000.SH")


class TestQuantityValidation(unittest.TestCase):
    def test_negative_rejected(self):
        with self.assertRaises(PositionInvariantError):
            _snap(broker=-1)
        with self.assertRaises(PositionInvariantError):
            _snap(core=-1)
        with self.assertRaises(PositionInvariantError):
            _snap(strategic=-1)
        with self.assertRaises(PositionInvariantError):
            _snap(open_t=-1)
        with self.assertRaises(PositionInvariantError):
            _snap(can_use=-1)
        with self.assertRaises(PositionInvariantError):
            _snap(reserved=-1)

    def test_bool_rejected(self):
        with self.assertRaises(PositionInvariantError):
            _snap(broker=True)
        with self.assertRaises(PositionInvariantError):
            _snap(core=True)
        with self.assertRaises(PositionInvariantError):
            _snap(reserved=True)

    def test_float_rejected(self):
        with self.assertRaises(PositionInvariantError):
            _snap(broker=700.0)
        with self.assertRaises(PositionInvariantError):
            _snap(can_use=50.0)

    def test_string_rejected(self):
        with self.assertRaises(PositionInvariantError):
            _snap(broker="700")
        with self.assertRaises(PositionInvariantError):
            _snap(open_t="100")

    def test_int_subclass_rejected_without_custom_methods(self):
        # Failure injection: a malicious int subclass must be rejected without
        # invoking its custom __str__/__repr__/__int__.
        with self.assertRaises(PositionInvariantError) as cm:
            _snap(broker=_EvilInt(700))
        self.assertNotIn("EVIL", str(cm.exception))


class TestSymbolValidation(unittest.TestCase):
    def test_empty_symbol_rejected(self):
        with self.assertRaises(PositionInvariantError):
            _snap(symbol="")
        with self.assertRaises(PositionInvariantError):
            _snap(symbol="   ")

    def test_non_string_rejected(self):
        for bad in (None, 5, True, b"600000.SH"):
            with self.assertRaises(PositionInvariantError):
                _snap(symbol=bad)

    def test_str_subclass_rejected_without_custom_str(self):
        with self.assertRaises(PositionInvariantError) as cm:
            _snap(symbol=_EvilStr("600000.SH"))
        self.assertNotIn("EVIL", str(cm.exception))


class TestDecomposition(unittest.TestCase):
    def test_broker_over_sum_fails(self):
        with self.assertRaises(PositionInvariantError):
            _snap(broker=701)

    def test_broker_under_sum_fails(self):
        with self.assertRaises(PositionInvariantError):
            _snap(broker=699)

    def test_broker_below_core_is_core_floor(self):
        # INV-005: broker below the floor is the highest-priority signal, and it
        # must win over the decomposition mismatch.
        with self.assertRaises(CoreFloorViolation):
            _snap(broker=500, core=600, open_t=100)

    def test_failure_does_not_modify_anything(self):
        # Construction failure leaves no partial state observable; and a valid
        # snapshot is never mutated by a later failed validation.
        s = _snap()
        with self.assertRaises(CoreFloorViolation):
            CorePositionGuard.validate_t_sell(s, 200)
        self.assertEqual(s.broker_position, 700)
        self.assertEqual(s.core_position, 600)


class TestValidateTSell(unittest.TestCase):
    def test_valid_sell_passes(self):
        CorePositionGuard.validate_t_sell(_snap(), 90)
        CorePositionGuard.validate_t_sell(_snap(), 100)
        CorePositionGuard.validate_t_sell(_snap(can_use=100), 100)

    def test_zero_and_negative_sell_rejected(self):
        with self.assertRaises(PositionInvariantError):
            CorePositionGuard.validate_t_sell(_snap(), 0)
        with self.assertRaises(PositionInvariantError):
            CorePositionGuard.validate_t_sell(_snap(), -1)

    def test_sell_qty_types_rejected(self):
        for bad in (True, 1.5, "5", None, _EvilInt(5)):
            with self.assertRaises(PositionInvariantError) as cm:
                CorePositionGuard.validate_t_sell(_snap(), bad)
            self.assertNotIn("EVIL", str(cm.exception))

    def test_wrong_snapshot_type_rejected(self):
        with self.assertRaises(PositionInvariantError):
            CorePositionGuard.validate_t_sell(object(), 10)

    def test_core_floor_violation(self):
        # sell > headroom (broker - core) triggers CoreFloor first.
        with self.assertRaises(CoreFloorViolation):
            CorePositionGuard.validate_t_sell(_snap(), 101)

    def test_insufficient_available_volume(self):
        # large headroom but small can_use -> InsufficientAvailableVolume.
        with self.assertRaises(InsufficientAvailableVolume):
            CorePositionGuard.validate_t_sell(_snap(can_use=50), 60)

    def test_sell_reservation_conflict(self):
        # large headroom and can_use, but reserved reduces available.
        with self.assertRaises(SellReservationConflict):
            CorePositionGuard.validate_t_sell(_snap(reserved=40), 61)

    def test_exactly_available_passes(self):
        CorePositionGuard.validate_t_sell(_snap(can_use=50), 50)
        CorePositionGuard.validate_t_sell(_snap(reserved=40), 60)

    def test_one_over_available_fails(self):
        with self.assertRaises(InsufficientAvailableVolume):
            CorePositionGuard.validate_t_sell(_snap(can_use=50), 51)
        with self.assertRaises(SellReservationConflict):
            CorePositionGuard.validate_t_sell(_snap(reserved=40), 61)

    def test_priority_core_floor_wins(self):
        # Simultaneously violates all three: sell > headroom (and therefore also
        # > can_use and > available).  Core Floor must win.
        s = _snap(can_use=50, reserved=40)  # headroom 100, can_use 50, avail 10
        with self.assertRaises(CoreFloorViolation):
            CorePositionGuard.validate_t_sell(s, 101)

    def test_priority_available_wins_over_reservation(self):
        # sell 51 > can_use 50 (checked before reservation) -> Insufficient
        # Available Volume must win even though 51 > avail 10 as well.
        s = _snap(can_use=50, reserved=40)  # avail = 10, can_use = 50
        with self.assertRaises(InsufficientAvailableVolume):
            CorePositionGuard.validate_t_sell(s, 51)

    def test_priority_reservation_last(self):
        # Violates only reservation (avail 10, sell 11 <= can_use 700) ->
        # SellReservationConflict.
        s = _snap(can_use=700, reserved=40)
        with self.assertRaises(SellReservationConflict):
            CorePositionGuard.validate_t_sell(s, 61)

    def test_error_types_are_distinct(self):
        self.assertTrue(issubclass(CoreFloorViolation, RiskError))
        self.assertTrue(issubclass(InsufficientAvailableVolume, RiskError))
        self.assertTrue(issubclass(SellReservationConflict, RiskError))
        self.assertTrue(issubclass(PositionInvariantError, RiskError))
        self.assertIsNot(CoreFloorViolation, InsufficientAvailableVolume)
        self.assertIsNot(InsufficientAvailableVolume, SellReservationConflict)


class TestStrategicIsolation(unittest.TestCase):
    """REV-G2T001-001: T module may only sell open T-lot shares (design §17, INV-008)."""

    def test_strategic_only_zero_t_no_sell_allowed(self):
        # broker=700/core=600/strategic=100/open_t=0: available_t_qty must be 0
        # and ANY positive sell must be rejected (CoreFloorViolation).
        s = _snap(strategic=100, open_t=0, broker=700)
        self.assertEqual(s.available_t_qty, 0)
        with self.assertRaises(CoreFloorViolation):
            CorePositionGuard.validate_t_sell(s, 1)
        with self.assertRaises(CoreFloorViolation):
            CorePositionGuard.validate_t_sell(s, 100)

    def test_mixed_strategic_plus_t_limits_to_open_t(self):
        # broker=800/core=600/strategic=100/open_t=100: available_t_qty=100,
        # only up to 100 sellable; 200 must be rejected.
        s = _snap(strategic=100, open_t=100, broker=800)
        self.assertEqual(s.available_t_qty, 100)
        CorePositionGuard.validate_t_sell(s, 100)
        with self.assertRaises(CoreFloorViolation):
            CorePositionGuard.validate_t_sell(s, 101)
        with self.assertRaises(CoreFloorViolation):
            CorePositionGuard.validate_t_sell(s, 200)

    def test_reserved_mixed_strategy(self):
        # broker=800/core=600/strategic=100/open_t=100/can_use=800/reserved=40:
        # available_t_qty = min(800,100)-40 = 60.
        s = _snap(strategic=100, open_t=100, broker=800, can_use=800, reserved=40)
        self.assertEqual(s.available_t_qty, 60)
        CorePositionGuard.validate_t_sell(s, 60)
        with self.assertRaises(SellReservationConflict):
            CorePositionGuard.validate_t_sell(s, 61)
        with self.assertRaises(CoreFloorViolation):
            CorePositionGuard.validate_t_sell(s, 101)

    def test_strategic_never_reclassified_or_modified(self):
        s = _snap(strategic=100, open_t=100, broker=800)
        before = (s.strategic_extra, s.core_position, s.open_t_lot_position)
        with self.assertRaises(CoreFloorViolation):
            CorePositionGuard.validate_t_sell(s, 101)
        self.assertEqual(
            (s.strategic_extra, s.core_position, s.open_t_lot_position), before
        )


def _make_symbol_config(core_qty=600, **overrides):
    base = dict(
        enabled=True,
        mode="ACCUMULATE",
        core_qty=core_qty,
        target_qty=800,
        t_unit=100,
        lot_size=100,
        price_tick=0.01,
        max_t_lots=1,
        max_t_capital=100000.0,
        anchor="VWAP20",
        atr_period=20,
        atr_k=2.0,
        min_grid=0.5,
        max_grid=2.0,
        exit_multiple=1.0,
    )
    base.update(overrides)
    return SymbolConfig(**base)


class TestSymbolConfigBinding(unittest.TestCase):
    """REV-G2T001-002: core comes only from SymbolConfig.core_qty."""

    def test_core_taken_from_config(self):
        cfg = _make_symbol_config(core_qty=650)
        s = snapshot_from_symbol_config(
            cfg,
            symbol="600000.SH",
            broker_position=800,
            strategic_extra=0,
            open_t_lot_position=150,
            can_use_qty=800,
            reserved_sell_qty=0,
        )
        self.assertEqual(s.core_position, 650)
        self.assertEqual(s.open_t_lot_position, 150)
        self.assertEqual(s.available_t_qty, 150)

    def test_no_second_core_input(self):
        # The factory signature has no core argument: caller cannot create drift.
        import inspect

        sig = inspect.signature(snapshot_from_symbol_config)
        self.assertNotIn("core_position", sig.parameters)
        self.assertNotIn("core", sig.parameters)

    def test_wrong_config_type_rejected(self):
        with self.assertRaises(PositionInvariantError):
            snapshot_from_symbol_config(
                object(),
                symbol="s",
                broker_position=100,
                strategic_extra=0,
                open_t_lot_position=100,
                can_use_qty=100,
                reserved_sell_qty=0,
            )

    def test_config_stays_frozen(self):
        cfg = _make_symbol_config(core_qty=600)
        snapshot_from_symbol_config(
            cfg,
            symbol="s",
            broker_position=700,
            strategic_extra=0,
            open_t_lot_position=100,
            can_use_qty=700,
            reserved_sell_qty=0,
        )
        with self.assertRaises(Exception):
            cfg.core_qty = 999
        self.assertEqual(cfg.core_qty, 600)

    def test_config_core_zero_is_plain_int_validated(self):
        with self.assertRaises(PositionInvariantError):
            snapshot_from_symbol_config(
                _make_symbol_config(core_qty=True),
                symbol="s",
                broker_position=700,
                strategic_extra=0,
                open_t_lot_position=100,
                can_use_qty=700,
                reserved_sell_qty=0,
            )


class TestProductionModuleSafety(unittest.TestCase):
    def test_position_source_is_clean(self):
        src = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "tgrid"
            / "position"
            / "manager.py"
        )
        text = src.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(src))
        forbidden_calls = ("order_stock", "cancel_order", "download_", "subscribe_quote", "unsubscribe_quote")
        for node in ast.walk(tree):
            self.assertNotIsInstance(node, ast.Assert)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(alias.name, "xtquant")
                    self.assertFalse(alias.name.startswith("xtquant."))
            if isinstance(node, ast.ImportFrom):
                self.assertFalse(
                    node.module
                    and (node.module == "xtquant" or node.module.startswith("xtquant."))
                )
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else (node.func.attr if isinstance(node.func, ast.Attribute) else None)
                if name:
                    self.assertFalse(any(k in name for k in forbidden_calls), msg=name)


if __name__ == "__main__":
    unittest.main()
