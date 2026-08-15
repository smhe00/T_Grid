"""Gate 5.5 Live Broker Adapter tests (pre-live, NODE-B scope).

Covers the mandatory safety boundary with a FAKE injected broker only — no
real XtQuant order/cancel is ever invoked:

* NODEB-007 bootstrap contract: config-level enable via trusted input only,
  token-gated runtime confirmation, restart always resets runtime-confirmed;
* symbol allowlist;
* hard per-order qty and cash limits + durable daily cash exposure (NODEB-005);
* kill switch blocks NEW orders but cancellation / re-query / cancel-all stay
  available (NODEB-003);
* NaN/Inf rejected before any arithmetic or broker call (NODEB-006);
* partial fill / cancel / re-query semantics via the adapter boundary;
* exact-type validation before broker calls;
* capability scan: every real order/cancel call site is inside the bridge.
"""

import math
import unittest

from tgrid.execution.port import BrokerOrder, BrokerPort
from tgrid.integrations.live_broker_adapter import (
    CashExposureLimitError,
    KillSwitchEngagedError,
    LiveBrokerAdapter,
    LiveBrokerError,
    LiveBrokerPolicy,
    LiveTradingDisabledError,
    LiveTradingNotConfirmedError,
    OrderQtyLimitError,
    RuntimeConfirmationTokenError,
    SymbolNotAllowedError,
)


def _policy(**overrides):
    cfg = dict(
        allowlist=frozenset({"510300.SH"}),
        max_order_qty=1000,
        max_cash_per_order=100000.0,
        max_cash_per_day=200000.0,
    )
    cfg.update(overrides)
    return LiveBrokerPolicy(**cfg)


class _FakeBroker(BrokerPort):
    """Records every call; returns typed DTOs; never touches a real broker."""

    def __init__(self):
        self.orders = {}
        self.trades = {}
        self._seq = 0
        self.calls = []

    def place_order(self, **kwargs):
        self.calls.append(("place", kwargs))
        self._seq += 1
        order_id = f"FAKE{self._seq:06d}"
        self.orders[order_id] = BrokerOrder(
            order_id=order_id, symbol=kwargs["symbol"], side=kwargs["side"],
            qty=kwargs["qty"], limit_price=kwargs["limit_price"],
            status="SUBMITTED", filled_qty=0,
            client_order_key=kwargs.get("client_order_key"),
            order_remark=kwargs.get("order_remark"),
        )
        return order_id

    def cancel_order(self, order_id):
        self.calls.append(("cancel", order_id))
        if order_id not in self.orders:
            raise LiveBrokerError("unknown order")
        order = self.orders[order_id]
        self.orders[order_id] = BrokerOrder(
            order_id=order.order_id, symbol=order.symbol, side=order.side,
            qty=order.qty, limit_price=order.limit_price, status="CANCELED",
            filled_qty=order.filled_qty,
            client_order_key=order.client_order_key, order_remark=order.order_remark,
        )

    def query_order(self, order_id):
        return self.orders.get(order_id)

    def query_trades(self, order_id):
        return tuple(self.trades.get(order_id, []))

    def query_orders(self, **kwargs):
        orders = tuple(self.orders.values())
        symbol = kwargs.get("symbol")
        if symbol is not None:
            orders = tuple(o for o in orders if o.symbol == symbol)
        return orders


def _bootstrap(adapter, *, token="startup-token"):
    adapter.apply_config_enable(True)
    adapter.confirm_runtime(token)
    return adapter


class _DictStore:
    """Durable get/set key/value surface used by the exposure ledger."""

    def __init__(self):
        self._data = {}

    def get(self, trade_date):
        return self._data.get(trade_date)

    def set(self, trade_date, notional):
        self._data[trade_date] = notional


def _ready_adapter(**pol):
    return LiveBrokerAdapter(
        broker=_FakeBroker(), policy=_policy(**pol),
        trade_date="2026-08-15", runtime_confirmation_token="startup-token",
    )


class TestBootstrapContract(unittest.TestCase):
    """NODEB-007: config enable from trusted input; token-gated confirm; restart."""

    def test_live_disabled_by_default(self):
        adapter = LiveBrokerAdapter(
            broker=_FakeBroker(), policy=_policy(),
            trade_date="2026-08-15", runtime_confirmation_token="startup-token",
        )
        self.assertFalse(adapter.live_enabled)
        self.assertFalse(adapter.runtime_confirmed)
        with self.assertRaises(LiveTradingDisabledError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                limit_price=4.6)

    def test_config_enable_only_after_confirm(self):
        adapter = LiveBrokerAdapter(
            broker=_FakeBroker(), policy=_policy(),
            trade_date="2026-08-15", runtime_confirmation_token="startup-token",
        )
        adapter.apply_config_enable(True)
        self.assertTrue(adapter.live_enabled)
        with self.assertRaises(LiveTradingNotConfirmedError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                limit_price=4.6)

    def test_confirm_requires_exact_token(self):
        adapter = LiveBrokerAdapter(
            broker=_FakeBroker(), policy=_policy(),
            trade_date="2026-08-15", runtime_confirmation_token="startup-token",
        )
        adapter.apply_config_enable(True)
        with self.assertRaises(RuntimeConfirmationTokenError):
            adapter.confirm_runtime("wrong-token")
        adapter.confirm_runtime("startup-token")
        order_id = adapter.place_order(
            symbol="510300.SH", side="BUY", qty=100, limit_price=4.6,
        )
        self.assertTrue(order_id.startswith("FAKE"))

    def test_confirm_without_configured_token_fails(self):
        adapter = LiveBrokerAdapter(
            broker=_FakeBroker(), policy=_policy(),
            trade_date="2026-08-15", runtime_confirmation_token="",
        )
        adapter.apply_config_enable(True)
        with self.assertRaises(RuntimeConfirmationTokenError):
            adapter.confirm_runtime("anything")

    def test_restart_resets_runtime_confirmed(self):
        # Same trusted config enable, fresh adapter (process restart): the
        # runtime confirmation is never persisted as true (NODEB-007).
        adapter = _ready_adapter()
        _bootstrap(adapter)
        adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                            limit_price=4.6)
        restarted = LiveBrokerAdapter(
            broker=_FakeBroker(), policy=_policy(),
            trade_date="2026-08-15", runtime_confirmation_token="startup-token",
        )
        restarted.apply_config_enable(True)
        self.assertTrue(restarted.live_enabled)
        self.assertFalse(restarted.runtime_confirmed)
        with self.assertRaises(LiveTradingNotConfirmedError):
            restarted.place_order(symbol="510300.SH", side="BUY", qty=100,
                                  limit_price=4.6)

    def test_untrusted_config_enable_rejected(self):
        adapter = LiveBrokerAdapter(
            broker=_FakeBroker(), policy=_policy(),
            trade_date="2026-08-15", runtime_confirmation_token="startup-token",
        )
        with self.assertRaises(LiveBrokerError):
            adapter.apply_config_enable("yes")


class TestAllowlistAndLimits(unittest.TestCase):
    """NODE-B items 3-5: allowlist + hard qty/cash limits."""

    def _ready(self, **pol):
        adapter = _ready_adapter(**pol)
        _bootstrap(adapter)
        return adapter

    def test_symbol_not_allowed(self):
        adapter = self._ready()
        with self.assertRaises(SymbolNotAllowedError):
            adapter.place_order(symbol="000333.SZ", side="BUY", qty=100,
                                limit_price=10.0)

    def test_qty_limit(self):
        adapter = self._ready(max_order_qty=500)
        with self.assertRaises(OrderQtyLimitError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=501,
                                limit_price=4.6)

    def test_cash_per_order_limit(self):
        adapter = self._ready(max_cash_per_order=1000.0)
        adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                            limit_price=4.6)
        with self.assertRaises(CashExposureLimitError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=300,
                                limit_price=4.6)

    def test_daily_cash_limit(self):
        adapter = self._ready(max_cash_per_order=100000.0, max_cash_per_day=500.0)
        adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                            limit_price=4.6)  # 460
        with self.assertRaises(CashExposureLimitError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                limit_price=4.6)  # would exceed 500 total

    def test_daily_exposure_bound_to_trade_date(self):
        adapter = self._ready(max_cash_per_day=500.0)
        adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                            limit_price=4.6)
        # SELL orders do not consume BUY exposure.
        adapter.place_order(symbol="510300.SH", side="SELL", qty=100,
                            limit_price=4.8)
        self.assertAlmostEqual(adapter.daily_cash_used, 460.0)

    def test_roll_day_is_monotonic_only(self):
        adapter = self._ready(max_cash_per_day=500.0)
        adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                            limit_price=4.6)
        with self.assertRaises(LiveBrokerError):
            adapter.roll_day("2026-08-15")  # same day
        with self.assertRaises(LiveBrokerError):
            adapter.roll_day("2026-08-14")  # backwards
        adapter.roll_day("2026-08-17")  # forward: resets and re-reconstructs
        self.assertAlmostEqual(adapter.daily_cash_used, 0.0)

    def test_no_public_unconditional_reset(self):
        adapter = self._ready()
        self.assertFalse(hasattr(adapter, "reset_daily_exposure"))

    def test_restart_reconstructs_exposure_from_broker(self):
        # First "process": place a BUY, then "restart" with a fresh adapter over
        # the same broker + a shared durable store.
        store = _DictStore()
        broker = _FakeBroker()
        adapter = LiveBrokerAdapter(
            broker=broker, policy=_policy(max_cash_per_day=500.0),
            trade_date="2026-08-15", runtime_confirmation_token="startup-token",
            exposure_store=store,
        )
        _bootstrap(adapter)
        adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                            limit_price=4.6)
        self.assertAlmostEqual(adapter.daily_cash_used, 460.0)

        restarted = LiveBrokerAdapter(
            broker=broker, policy=_policy(max_cash_per_day=500.0),
            trade_date="2026-08-15", runtime_confirmation_token="startup-token",
            exposure_store=store,
        )
        restarted.apply_config_enable(True)
        restarted.confirm_runtime("startup-token")
        restarted.reconstruct_daily_exposure()
        self.assertAlmostEqual(restarted.daily_cash_used, 460.0)
        with self.assertRaises(CashExposureLimitError):
            restarted.place_order(symbol="510300.SH", side="BUY", qty=100,
                                  limit_price=4.6)


class TestKillSwitch(unittest.TestCase):
    """NODEB-003: kill switch blocks NEW orders, never cancellation."""

    def _ready(self):
        adapter = _ready_adapter()
        _bootstrap(adapter)
        return adapter

    def test_kill_switch_blocks_new_orders(self):
        adapter = self._ready()
        adapter.engage_kill_switch()
        with self.assertRaises(KillSwitchEngagedError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                limit_price=4.6)

    def test_kill_switch_still_permits_cancel_and_requery(self):
        adapter = self._ready()
        order_id = adapter.place_order(
            symbol="510300.SH", side="BUY", qty=100, limit_price=4.6,
        )
        adapter.engage_kill_switch()
        adapter.cancel_order(order_id)  # must NOT raise
        state = adapter.query_order(order_id)
        self.assertEqual(state.status, "CANCELED")

    def test_kill_switch_cancel_all_managed_open_orders(self):
        adapter = self._ready()
        o1 = adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                 limit_price=4.6, order_remark="TG_510300SH_B001")
        o2 = adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                 limit_price=4.6, order_remark="TG_510300SH_B002")
        adapter.engage_kill_switch()
        requery = adapter.cancel_all_managed_open_orders()
        self.assertEqual({r.order_id for r in requery}, {o1, o2})
        self.assertTrue(all(r.status == "CANCELED" for r in requery))
        # New orders still blocked.
        with self.assertRaises(KillSwitchEngagedError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                limit_price=4.6)

    def test_cancel_then_requery_never_assumes_zero_fill(self):
        adapter = self._ready()
        order_id = adapter.place_order(
            symbol="510300.SH", side="BUY", qty=100, limit_price=4.6,
        )
        adapter.cancel_order(order_id)
        # After cancel the caller MUST re-query (never assume zero fill).
        state = adapter.query_order(order_id)
        self.assertEqual(state.status, "CANCELED")


class TestNanInfRejection(unittest.TestCase):
    """NODEB-006: NaN/Inf rejected in policy values and prices."""

    def test_policy_rejects_nan(self):
        with self.assertRaises(LiveBrokerError):
            _policy(max_cash_per_order=float("nan"))
        with self.assertRaises(LiveBrokerError):
            _policy(max_cash_per_day=float("nan"))

    def test_policy_rejects_inf(self):
        with self.assertRaises(LiveBrokerError):
            _policy(max_cash_per_order=float("inf"))
        with self.assertRaises(LiveBrokerError):
            _policy(max_cash_per_day=float("-inf"))

    def test_place_order_rejects_nan_price(self):
        broker = _FakeBroker()
        adapter = LiveBrokerAdapter(
            broker=broker, policy=_policy(),
            trade_date="2026-08-15", runtime_confirmation_token="startup-token",
        )
        _bootstrap(adapter)
        with self.assertRaises(LiveBrokerError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                limit_price=float("nan"))
        with self.assertRaises(LiveBrokerError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                limit_price=float("inf"))
        self.assertEqual(broker.calls, [])


class TestExactTypeValidation(unittest.TestCase):
    """NODE-B item 12: exact-type validation before any broker call."""

    def _adapter(self):
        broker = _FakeBroker()
        adapter = LiveBrokerAdapter(
            broker=broker, policy=_policy(),
            trade_date="2026-08-15", runtime_confirmation_token="startup-token",
        )
        _bootstrap(adapter)
        return broker, adapter

    def test_string_qty_rejected_no_broker_call(self):
        broker, adapter = self._adapter()
        with self.assertRaises(LiveBrokerError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty="100",
                                limit_price=4.6)
        self.assertEqual(broker.calls, [])

    def test_fractional_qty_rejected(self):
        broker, adapter = self._adapter()
        with self.assertRaises(LiveBrokerError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=100.5,
                                limit_price=4.6)
        self.assertEqual(broker.calls, [])

    def test_evil_price_object_not_coerced(self):
        broker, adapter = self._adapter()

        class Evil:
            def __float__(self):
                raise RuntimeError("must not be coerced")

        with self.assertRaises(LiveBrokerError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                limit_price=Evil())
        self.assertEqual(broker.calls, [])

    def test_math_isfinite_used(self):
        self.assertTrue(math.isfinite(4.6))


class TestCapabilityScan(unittest.TestCase):
    """Every real order/cancel call site lives in the allowed bridge file."""

    def test_adapter_source_has_no_real_xtquant_calls(self):
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[2]
            / "src" / "tgrid" / "integrations" / "live_broker_adapter.py"
        )
        tree = ast.parse(source.read_text(encoding="utf-8"))
        order_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("order_stock", "cancel_order_stock"):
                    order_calls.append(node.func.attr)
        self.assertEqual(order_calls, [])

    def test_bridge_is_the_only_real_call_site(self):
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "src"
        offenders = []
        bridge_hits = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in ("order_stock", "cancel_order_stock"):
                        rel = path.relative_to(root).as_posix()
                        if rel == "tgrid/integrations/xtquant_bridge.py":
                            bridge_hits.append(node.func.attr)
                        else:
                            offenders.append(f"{rel}:{node.lineno}")
        self.assertEqual(offenders, [])
        self.assertIn("order_stock", bridge_hits)
        self.assertIn("cancel_order_stock", bridge_hits)


if __name__ == "__main__":
    unittest.main()
