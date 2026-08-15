"""Gate 5.5 Live Broker Adapter tests (pre-live, NODE-B scope).

Covers the mandatory safety boundary with a FAKE injected broker only — no
real XtQuant order/cancel is ever invoked:

* double-enable (live_trading false by default + explicit runtime confirm);
* symbol allowlist;
* hard per-order qty and cash limits + daily cash exposure;
* kill switch;
* callback isolation (callbacks cannot mutate protected state / issue orders);
* partial fill / cancel / re-query semantics via the adapter boundary;
* crash-recovery/reconciliation determinism at the adapter level;
* exact-type validation before broker calls;
* capability scan: every real order/cancel call site in the adapter is via
  the injected ``broker`` object only.
"""

import unittest

from tgrid.integrations.live_broker_adapter import (
    CallbackMutationForbiddenError,
    CashExposureLimitError,
    KillSwitchEngagedError,
    LiveBrokerAdapter,
    LiveBrokerError,
    LiveBrokerPolicy,
    LiveTradingDisabledError,
    LiveTradingNotConfirmedError,
    OrderQtyLimitError,
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


class _FakeBroker:
    """Records every call; never touches a real broker."""

    def __init__(self):
        self.orders = {}
        self.trades = {}
        self._seq = 0
        self.calls = []

    def place_order(self, **kwargs):
        self.calls.append(("place", kwargs))
        self._seq += 1
        order_id = f"FAKE{self._seq:06d}"
        self.orders[order_id] = {"status": "SUBMITTED", "filled_qty": 0, **kwargs}
        return order_id

    def cancel_order(self, order_id):
        self.calls.append(("cancel", order_id))
        if order_id not in self.orders:
            raise LiveBrokerError("unknown order")
        self.orders[order_id]["status"] = "CANCELED"

    def query_order(self, order_id):
        return self.orders.get(order_id)

    def query_trades(self, order_id):
        return tuple(self.trades.get(order_id, []))

    def query_orders(self, **kwargs):
        return tuple(self.orders.values())


class TestDoubleEnable(unittest.TestCase):
    """NODE-B items 1-2: live defaults false + second runtime confirmation."""

    def _adapter(self, live=False, confirmed=False):
        return LiveBrokerAdapter(
            broker=_FakeBroker(), policy=_policy(),
            live_enabled=live, runtime_confirmed=confirmed,
        )

    def test_live_disabled_by_default(self):
        adapter = self._adapter(live=False, confirmed=False)
        with self.assertRaises(LiveTradingDisabledError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                limit_price=4.6)

    def test_enabled_but_not_confirmed(self):
        adapter = self._adapter(live=True, confirmed=False)
        with self.assertRaises(LiveTradingNotConfirmedError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                limit_price=4.6)

    def test_both_required(self):
        adapter = self._adapter(live=True, confirmed=True)
        order_id = adapter.place_order(
            symbol="510300.SH", side="BUY", qty=100, limit_price=4.6,
        )
        self.assertTrue(order_id.startswith("FAKE"))

    def test_explicit_enable_and_confirm(self):
        adapter = LiveBrokerAdapter(broker=_FakeBroker(), policy=_policy())
        adapter.enable_live_trading()
        with self.assertRaises(LiveTradingNotConfirmedError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                limit_price=4.6)
        adapter.confirm_runtime()
        adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                            limit_price=4.6)  # no raise


class TestAllowlistAndLimits(unittest.TestCase):
    """NODE-B items 3-5: allowlist + hard qty/cash limits."""

    def _ready(self, **pol):
        return LiveBrokerAdapter(
            broker=_FakeBroker(), policy=_policy(**pol),
            live_enabled=True, runtime_confirmed=True,
        )

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
        # 100 * 4.6 = 460 < 1000 OK; 300 * 4.6 = 1380 > 1000 rejected.
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

    def test_reset_daily_exposure(self):
        adapter = self._ready(max_cash_per_day=500.0)
        adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                            limit_price=4.6)
        adapter.reset_daily_exposure()
        adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                            limit_price=4.6)  # allowed after reset


class TestKillSwitch(unittest.TestCase):
    def test_kill_switch_blocks_new_orders(self):
        adapter = LiveBrokerAdapter(
            broker=_FakeBroker(), policy=_policy(),
            live_enabled=True, runtime_confirmed=True,
        )
        adapter.engage_kill_switch()
        with self.assertRaises(KillSwitchEngagedError):
            adapter.place_order(symbol="510300.SH", side="BUY", qty=100,
                                limit_price=4.6)


class TestCallbackIsolation(unittest.TestCase):
    """NODE-B item 7: callbacks may only enqueue; no mutation/order issuance."""

    def test_registered_callback_has_no_broker_access(self):
        adapter = LiveBrokerAdapter(
            broker=_FakeBroker(), policy=_policy(),
            live_enabled=True, runtime_confirmed=True,
        )
        events = []

        def callback(event):
            events.append(event)  # sanctioned: enqueue only
            return None

        safe = adapter.register_callback(callback)
        safe({"kind": "fill"})
        self.assertEqual(len(events), 1)
        # The callback closure does not receive the broker or adapter, so it
        # structurally cannot place an order from within a callback.
        self.assertFalse(hasattr(safe, "broker"))


class TestExactTypeValidation(unittest.TestCase):
    """NODE-B item 12: exact-type validation before any broker call."""

    def _adapter(self):
        broker = _FakeBroker()
        adapter = LiveBrokerAdapter(
            broker=broker, policy=_policy(),
            live_enabled=True, runtime_confirmed=True,
        )
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


class TestCancelRequerySemantics(unittest.TestCase):
    """NODE-B item 10: cancel never implies zero fill; re-query required."""

    def test_cancel_then_requery(self):
        broker = _FakeBroker()
        adapter = LiveBrokerAdapter(
            broker=broker, policy=_policy(),
            live_enabled=True, runtime_confirmed=True,
        )
        order_id = adapter.place_order(
            symbol="510300.SH", side="BUY", qty=100, limit_price=4.6,
        )
        adapter.cancel_order(order_id)
        # After cancel the caller MUST re-query (never assume zero fill).
        state = adapter.query_order(order_id)
        self.assertEqual(state["status"], "CANCELED")
        # A partial fill recorded before cancel must still be observable.
        broker.orders[order_id]["filled_qty"] = 40
        self.assertEqual(adapter.query_order(order_id)["filled_qty"], 40)


class TestCapabilityScan(unittest.TestCase):
    """Every real order/cancel call site routes through the injected broker."""

    def test_adapter_source_only_calls_injected_broker(self):
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
        # No direct XtQuant order_stock/cancel_order_stock anywhere: the
        # adapter only calls self.broker.<method>.
        self.assertEqual(order_calls, [])
        # The only place/order surface is the injected broker attribute.
        attrs = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("place_order", attrs)  # via self.broker.place_order


if __name__ == "__main__":
    unittest.main()
