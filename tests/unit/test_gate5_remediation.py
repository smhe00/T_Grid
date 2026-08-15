"""Gate 5 remediation tests — AUD-R1-001/002/007.

Covers:

* AUD-R1-001: explicit RAW/ADJUSTED market-data acquisition — the exact
  dividend_type is passed to the underlying call, bars carry the resolved
  basis, unknown modes fail closed.
* AUD-R1-002: settlement-aware total vs sellable position — a same-day T1
  shadow BUY is locked; it becomes sellable only after the next trading day;
  T0 symbols are sellable immediately; real broker can_use stays usable.
* AUD-R1-007: ExecutionEngine rejects untrusted capacity/quantity coercion
  with exact-type validation before any arithmetic.
"""

import os
import tempfile
import unittest

from tgrid.execution import ExecutionEngine, ExecutionError
from tgrid.execution.store import ExecutionStore
from tgrid.persistence import initialize
from tgrid.shadow.engine import ShadowEngine, ShadowInputError
from tgrid.shadow.marketdata import BasisBinding, fetch_bars, resolve_basis
from tgrid.shadow.settlement import (
    SETTLE_T0,
    SETTLE_T1,
    SettlementPolicy,
    SettlementTracker,
    compute_sellable,
)


def _temp_db_path():
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = handle.name
    handle.close()
    os.remove(path)
    return path


class _FakeFrame:
    def __init__(self, rows, index):
        self._rows = rows
        self._index = index

    def iterrows(self):
        for ts, row in zip(self._index, self._rows):
            yield ts, row

    def __len__(self):
        return len(self._rows)


class _FakeRow(dict):
    pass


class _FakeXtdata:
    """Records the exact arguments passed to get_market_data_ex."""

    def __init__(self, index=None):
        self.calls = []
        self._index = index or ["20260813093500", "20260813094000"]

    def get_market_data_ex(self, field_list, stock_list, period, **kwargs):
        self.calls.append({
            "fields": tuple(field_list),
            "stocks": tuple(stock_list),
            "period": period,
            **kwargs,
        })
        rows = [
            _FakeRow(open="10.0", high="10.5", low="9.9", close="10.2", volume="1000"),
            _FakeRow(open="10.2", high="10.8", low="10.1", close="10.6", volume="1200"),
        ]
        return {"510300.SH": _FakeFrame(rows, self._index)}


class TestAudR1001BasisBinding(unittest.TestCase):
    def test_resolve_basis_modes(self):
        self.assertEqual(resolve_basis("none"), "RAW")
        self.assertEqual(resolve_basis("front"), "ADJUSTED")

    def test_unknown_mode_fails_closed(self):
        with self.assertRaises(ShadowInputError):
            resolve_basis("back")
        with self.assertRaises(ShadowInputError):
            resolve_basis(None)
        with self.assertRaises(ShadowInputError):
            resolve_basis("")

    def test_basis_binding_validates(self):
        binding = BasisBinding(period="1d", dividend_type="front", price_basis="ADJUSTED")
        self.assertEqual(binding.price_basis, "ADJUSTED")
        with self.assertRaises(ShadowInputError):
            BasisBinding(period="1d", dividend_type="back", price_basis="RAW")
        with self.assertRaises(ShadowInputError):
            BasisBinding(period="1h", dividend_type="front", price_basis="ADJUSTED")

    def test_fetch_bars_passes_explicit_dividend_type(self):
        fake = _FakeXtdata()
        bars, binding = fetch_bars(
            fake, code="510300.SH", period="1d",
            start_time="20260801", end_time="20260814",
            dividend_type="front",
        )
        self.assertEqual(len(bars), 2)
        self.assertEqual(binding.dividend_type, "front")
        self.assertEqual(binding.price_basis, "ADJUSTED")
        # Every bar carries the ADJUSTED basis.
        for bar in bars:
            self.assertEqual(bar.price_basis, "ADJUSTED")
        # The underlying call received the exact explicit mode (no default).
        call = fake.calls[-1]
        self.assertEqual(call["dividend_type"], "front")

    def test_fetch_bars_raw_basis(self):
        fake = _FakeXtdata()
        bars, binding = fetch_bars(
            fake, code="510300.SH", period="5m",
            start_time="20260813", end_time="20260814",
            dividend_type="none",
        )
        self.assertEqual(binding.price_basis, "RAW")
        for bar in bars:
            self.assertEqual(bar.price_basis, "RAW")
        self.assertEqual(fake.calls[-1]["dividend_type"], "none")

    def test_fetch_bars_rejects_unknown_mode(self):
        fake = _FakeXtdata()
        with self.assertRaises(ShadowInputError):
            fetch_bars(
                fake, code="510300.SH", period="1d",
                start_time="20260801", end_time="20260814",
                dividend_type="back",
            )
        # No underlying call was made for the rejected mode.
        self.assertEqual(len(fake.calls), 0)

    def test_fetch_bars_daily_8digit_timestamp(self):
        # Daily (1d) xtdata rows use 8-digit date indexes (e.g. 20260105).
        fake = _FakeXtdata(index=["20260105", "20260106"])
        bars, binding = fetch_bars(
            fake, code="510300.SH", period="1d",
            start_time="20260101", end_time="20260110",
            dividend_type="front",
        )
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].time, "2026-01-05T15:00:00")
        self.assertEqual(bars[1].time, "2026-01-06T15:00:00")
        self.assertEqual(bars[0].kind, "DAILY")
        self.assertEqual(binding.price_basis, "ADJUSTED")

    def test_fetch_bars_unparseable_timestamp_fails_closed(self):
        fake = _FakeXtdata(index=["not-a-timestamp"])
        with self.assertRaises(ShadowInputError):
            fetch_bars(
                fake, code="510300.SH", period="1d",
                start_time="20260101", end_time="20260110",
                dividend_type="front",
            )


class TestAudR1002Settlement(unittest.TestCase):
    def test_t1_policy_validation(self):
        policy = SettlementPolicy(symbol="510300.SH", rule=SETTLE_T1)
        self.assertFalse(policy.same_day_sellable())
        with self.assertRaises(ShadowInputError):
            SettlementPolicy(symbol="510300.SH", rule="T2")
        with self.assertRaises(ShadowInputError):
            SettlementPolicy(symbol="", rule=SETTLE_T1)

    def test_t1_same_day_buy_locked(self):
        policy = SettlementPolicy(symbol="510300.SH", rule=SETTLE_T1)
        tracker = SettlementTracker(policy)
        tracker.record_buy(100, trade_date="2026-08-13")
        # Not sellable the same day.
        self.assertEqual(tracker.sellable_from_released("2026-08-13"), 0)
        self.assertEqual(tracker.total_locked(), 100)
        # After the next trading day, the locked buy is released.
        tracker.advance_trading_day("2026-08-13", "2026-08-14")
        self.assertEqual(tracker.sellable_from_released("2026-08-14"), 100)
        self.assertEqual(tracker.total_locked(), 0)

    def test_t0_same_day_sellable(self):
        policy = SettlementPolicy(symbol="0700.HK", rule=SETTLE_T0)
        tracker = SettlementTracker(policy)
        tracker.record_buy(100, trade_date="2026-08-13")
        self.assertEqual(tracker.sellable_from_released("2026-08-13"), 100)

    def test_compute_sellable_combines_real_and_released(self):
        self.assertEqual(
            compute_sellable(real_can_use=500, shadow_released=100, total_locked=0),
            600,
        )
        with self.assertRaises(ShadowInputError):
            compute_sellable(real_can_use="500", shadow_released=0, total_locked=0)

    def test_sell_consumes_released_only(self):
        policy = SettlementPolicy(symbol="510300.SH", rule=SETTLE_T1)
        tracker = SettlementTracker(policy)
        tracker.record_buy(100, trade_date="2026-08-13")
        tracker.advance_trading_day("2026-08-13", "2026-08-14")
        tracker.record_sell(40, trade_date="2026-08-14")
        self.assertEqual(tracker.sellable_from_released("2026-08-14"), 60)
        # Selling beyond the released shadow portion is capped at the shadow
        # portion; the remainder is supplied by real broker can_use, so no
        # error is raised and the shadow book never goes negative.
        tracker.record_sell(100, trade_date="2026-08-14")
        self.assertEqual(tracker.sellable_from_released("2026-08-14"), 0)


class TestAudR1007ExecutorCoercion(unittest.TestCase):
    def _engine(self):
        conn = initialize(_temp_db_path())
        store = ExecutionStore(conn)
        from tgrid.execution.simbroker import SimBroker

        return conn, ExecutionEngine(store, SimBroker())

    def test_buy_rejects_untrusted_capacity_object(self):
        conn, engine = self._engine()
        try:
            class EvilNumber:
                def __float__(self):
                    raise RuntimeError("must not be coerced")

            with self.assertRaises(ExecutionError):
                engine.send_buy(
                    client_order_key="K1", symbol="510300.SH", qty=100,
                    limit_price=4.6, order_remark="TG_510300SH_B001", now="t0",
                    expected_available_cash=EvilNumber(), reserved_cash=460.0,
                )
        finally:
            conn.close()

    def test_buy_rejects_string_capacity(self):
        conn, engine = self._engine()
        try:
            with self.assertRaises(ExecutionError):
                engine.send_buy(
                    client_order_key="K1", symbol="510300.SH", qty=100,
                    limit_price=4.6, order_remark="TG_510300SH_B001", now="t0",
                    expected_available_cash="1000", reserved_cash=460.0,
                )
        finally:
            conn.close()

    def test_sell_rejects_fractional_capacity(self):
        conn, engine = self._engine()
        try:
            with self.assertRaises(ExecutionError):
                engine.send_sell(
                    client_order_key="K1", symbol="510300.SH", qty=100,
                    limit_price=4.6, order_remark="TG_510300SH_S001", now="t0",
                    expected_available_qty=1000.5,
                )
        finally:
            conn.close()

    def test_valid_plain_values_still_work(self):
        conn, engine = self._engine()
        try:
            result = engine.send_buy(
                client_order_key="K1", symbol="510300.SH", qty=100,
                limit_price=4.6, order_remark="TG_510300SH_B001", now="t0",
                expected_available_cash=100000.0, reserved_cash=460.0,
            )
            self.assertEqual(result.status, "SUBMITTED")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
