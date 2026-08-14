"""Tests for the offline single quote-subscription lifecycle adapter (G1-T004).

All tests use fake clients only: nothing here imports or touches XtQuant, and
nothing subscribes, connects, or receives real market data.
"""

import ast
import contextlib
import io
import unittest
from pathlib import Path

from tgrid import (
    QuoteSubscriptionState,
    ReadOnlyQuoteSubscriptionAdapter,
)
from tgrid.risk.exceptions import (
    QuoteSubscriptionConfigError,
    QuoteSubscriptionError,
    QuoteSubscriptionLifecycleError,
    QuoteSubscriptionStartError,
    QuoteSubscriptionStopError,
    QuoteSubscriptionValidationError,
    TGridError,
)

_FORBIDDEN_NAMES = (
    "download_history_data",
    "query_stock_asset",
    "query_stock_positions",
    "query_stock_orders",
    "query_stock_trades",
    "connect",
    "order_stock",
    "order_stock_async",
    "cancel_order_stock",
    "cancel_order_stock_async",
    "cancel_order",
    "subscribe_quote",
    "unsubscribe_quote",
    "call",
    "forward",
)


class FakeClient:
    """Records calls; returns a configurable sequence id; stores callback identity."""

    def __init__(self):
        self.calls = []
        self.seq = 42
        self.saved_cb = None
        self.exceptions = {}
        self.unsub_result = None

    def set_exception(self, name, factory):
        self.exceptions[name] = factory

    def _record(self, name, *args):
        self.calls.append((name, args))
        if name in self.exceptions:
            raise self.exceptions[name]()
        return None

    def subscribe_quote(self, stock_code, period, start_time, end_time, count, callback):
        self.calls.append(("subscribe_quote", stock_code, period, start_time, end_time, count))
        self.saved_cb = callback
        if "subscribe_quote" in self.exceptions:
            raise self.exceptions["subscribe_quote"]()
        return self.seq

    def unsubscribe_quote(self, sequence_id):
        self.calls.append(("unsubscribe_quote", sequence_id))
        if "unsubscribe_quote" in self.exceptions:
            raise self.exceptions["unsubscribe_quote"]()
        return self.unsub_result


class DangerousClient(FakeClient):
    """Exposes download/query/connect/order/cancel the adapter must never reach."""

    def __init__(self):
        super().__init__()
        self.danger_calls = []

    def download_history_data(self, *a, **k):
        self.danger_calls.append(("download_history_data", a, k))

    def query_stock_asset(self, *a, **k):
        self.danger_calls.append(("query_stock_asset", a, k))

    def connect(self, *a, **k):
        self.danger_calls.append(("connect", a, k))

    def order_stock(self, *a, **k):
        self.danger_calls.append(("order_stock", a, k))

    def cancel_order_stock(self, *a, **k):
        self.danger_calls.append(("cancel_order_stock", a, k))


class _MissingAttr:
    def __get__(self, obj, objtype=None):
        raise AttributeError("missing")


class _SecretDescriptor:
    def __get__(self, obj, objtype=None):
        raise RuntimeError("CONSTRUCTOR_DESCRIPTOR_SECRET_XYZ")


class _DescriptorSecretClient(FakeClient):
    subscribe_quote = _SecretDescriptor()


def _client_variant(missing=(), non_callable=(), repr_secret=None):
    attrs = {}
    for name in missing:
        attrs[name] = _MissingAttr()
    for name in non_callable:
        attrs[name] = 12345
    if repr_secret is not None:
        attrs["__repr__"] = lambda self, _s=repr_secret: _s
    return type("PartialClient", (FakeClient,), attrs)()


def _adapter(client=None):
    return ReadOnlyQuoteSubscriptionAdapter(client or FakeClient())


def _unsub_call_count(client):
    """Count every unsubscribe_quote call regardless of the sequence id passed.

    REV-G1T004-001: counting only ("unsubscribe_quote", 42) can hide a bogus
    unsubscribe_quote(None) call after a failed subscribe.
    """
    return sum(1 for call in client.calls if call[0] == "unsubscribe_quote")


def _cb(x=None):
    return lambda evt: None


def _subscribed(client=None):
    adapter = _adapter(client)
    adapter.subscribe("600000.SH", _cb())
    return adapter


class TestConstructorValidation(unittest.TestCase):
    def test_none_client_rejected(self):
        with self.assertRaises(QuoteSubscriptionConfigError):
            ReadOnlyQuoteSubscriptionAdapter(None)

    def test_error_is_tgrid_subclass(self):
        with self.assertRaises(TGridError):
            ReadOnlyQuoteSubscriptionAdapter(None)

    def test_missing_method_rejected(self):
        for name in ("subscribe_quote", "unsubscribe_quote"):
            client = _client_variant(missing=(name,))
            with self.assertRaises(QuoteSubscriptionConfigError) as cm:
                ReadOnlyQuoteSubscriptionAdapter(client)
            self.assertIn(name, str(cm.exception))
            self.assertIsNone(cm.exception.__cause__)
            self.assertIsNone(cm.exception.__context__)

    def test_non_callable_method_rejected(self):
        for name in ("subscribe_quote", "unsubscribe_quote"):
            client = _client_variant(non_callable=(name,))
            with self.assertRaises(QuoteSubscriptionConfigError) as cm:
                ReadOnlyQuoteSubscriptionAdapter(client)
            self.assertIn(name, str(cm.exception))

    def test_error_has_type_name_no_client_repr(self):
        client = _client_variant(missing=("unsubscribe_quote",), repr_secret="REPR_SECRET_XYZ")
        with self.assertRaises(QuoteSubscriptionConfigError) as cm:
            ReadOnlyQuoteSubscriptionAdapter(client)
        self.assertIn("PartialClient", str(cm.exception))
        self.assertIn("unsubscribe_quote", str(cm.exception))
        self.assertNotIn("REPR_SECRET_XYZ", str(cm.exception))

    def test_valid_client_accepted(self):
        a = _adapter()
        self.assertIs(a.state, QuoteSubscriptionState.NEW)
        self.assertIsNone(a.sequence_id)
        self.assertIsNone(a.failure_type)

    def test_constructor_descriptor_secret_not_leaked(self):
        client = _DescriptorSecretClient()
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(QuoteSubscriptionConfigError) as cm:
                ReadOnlyQuoteSubscriptionAdapter(client)
        exc = cm.exception
        self.assertIn("subscribe_quote", str(exc))
        self.assertIn("_DescriptorSecretClient", str(exc))
        self.assertIsNone(exc.__cause__)
        self.assertIsNone(exc.__context__)
        for text in (str(exc), out.getvalue(), err.getvalue()):
            self.assertNotIn("CONSTRUCTOR_DESCRIPTOR_SECRET_XYZ", text)


class TestSubscribe(unittest.TestCase):
    def test_success_returns_and_saves_sequence_id(self):
        client = FakeClient()
        adapter = _adapter(client)
        cb = _cb()
        seq = adapter.subscribe("600000.SH", cb)
        self.assertEqual(seq, 42)
        self.assertEqual(client.calls, [("subscribe_quote", "600000.SH", "tick", "", "", 0)])
        self.assertIs(client.saved_cb, cb)
        self.assertIs(adapter.state, QuoteSubscriptionState.ACTIVE)
        self.assertEqual(adapter.sequence_id, 42)

    def test_six_args_passed_verbatim(self):
        client = FakeClient()
        adapter = _adapter(client)
        cb = _cb()
        adapter.subscribe("600000.SH", cb, period="1m", start_time="093000",
                          end_time="150000", count=100)
        self.assertEqual(
            client.calls,
            [("subscribe_quote", "600000.SH", "1m", "093000", "150000", 100)],
        )

    def test_zero_sequence_id_accepted(self):
        client = FakeClient()
        client.seq = 0
        adapter = _adapter(client)
        self.assertEqual(adapter.subscribe("600000.SH", _cb()), 0)
        self.assertIs(adapter.state, QuoteSubscriptionState.ACTIVE)
        self.assertEqual(adapter.sequence_id, 0)

    def test_negative_sequence_id_fails_closed(self):
        client = FakeClient()
        client.seq = -1
        adapter = _adapter(client)
        with self.assertRaises(QuoteSubscriptionStartError):
            adapter.subscribe("600000.SH", _cb())
        self.assertIs(adapter.state, QuoteSubscriptionState.FAILED)
        self.assertEqual(adapter.failure_type, "int")

    def test_invalid_return_types_fail_closed(self):
        for bad, label in ((True, "bool"), (None, "NoneType"), (3.5, "float"), ("1", "str")):
            client = FakeClient()
            client.seq = bad
            adapter = _adapter(client)
            with self.assertRaises(QuoteSubscriptionStartError):
                adapter.subscribe("600000.SH", _cb())
            self.assertIs(adapter.state, QuoteSubscriptionState.FAILED)
            self.assertEqual(adapter.failure_type, label)

    def test_repeat_subscribe_rejected(self):
        adapter = _subscribed()
        with self.assertRaises(QuoteSubscriptionLifecycleError):
            adapter.subscribe("600000.SH", _cb())
        # underlying subscribe_quote still called exactly once

    def test_subscribe_after_stop_rejected(self):
        adapter = _subscribed()
        adapter.stop()
        with self.assertRaises(QuoteSubscriptionLifecycleError):
            adapter.subscribe("600000.SH", _cb())

    def test_subscribe_after_failed_rejected(self):
        client = FakeClient()
        client.seq = -1
        adapter = _adapter(client)
        with self.assertRaises(QuoteSubscriptionStartError):
            adapter.subscribe("600000.SH", _cb())
        with self.assertRaises(QuoteSubscriptionLifecycleError):
            adapter.subscribe("600000.SH", _cb())


class TestValidation(unittest.TestCase):
    def test_invalid_stock_code(self):
        adapter = _adapter()
        for bad in ("", None, 5, True):
            with self.assertRaises(QuoteSubscriptionValidationError) as cm:
                adapter.subscribe(bad, _cb())
            self.assertIn("stock_code", str(cm.exception))
        self.assertIs(adapter.state, QuoteSubscriptionState.NEW)

    def test_invalid_period(self):
        adapter = _adapter()
        for bad in ("", None, 5):
            with self.assertRaises(QuoteSubscriptionValidationError) as cm:
                adapter.subscribe("600000.SH", _cb(), period=bad)
            self.assertIn("period", str(cm.exception))

    def test_invalid_callback(self):
        adapter = _adapter()
        for bad in (None, "not-callable", 42, object()):
            with self.assertRaises(QuoteSubscriptionValidationError) as cm:
                adapter.subscribe("600000.SH", bad)
            self.assertIn("callback", str(cm.exception))

    def test_invalid_times(self):
        adapter = _adapter()
        for kwargs in ({"start_time": 20260801}, {"end_time": None}):
            name = next(iter(kwargs))
            with self.assertRaises(QuoteSubscriptionValidationError) as cm:
                adapter.subscribe("600000.SH", _cb(), **kwargs)
            self.assertIn(name, str(cm.exception))

    def test_invalid_count(self):
        adapter = _adapter()
        for bad in (-1, True, 1.5, "5", None):
            with self.assertRaises(QuoteSubscriptionValidationError) as cm:
                adapter.subscribe("600000.SH", _cb(), count=bad)
            self.assertIn("count", str(cm.exception))
        # 0 and positive ints accepted
        adapter2 = _adapter()
        adapter2.subscribe("600000.SH", _cb(), count=0)
        adapter3 = _adapter()
        adapter3.subscribe("600000.SH", _cb(), count=100)

    def test_validation_failure_calls_nothing(self):
        client = FakeClient()
        adapter = _adapter(client)
        with self.assertRaises(QuoteSubscriptionValidationError):
            adapter.subscribe("", _cb())
        self.assertEqual(client.calls, [])

    def test_validation_error_has_no_illegal_value(self):
        adapter = _adapter()
        with self.assertRaises(QuoteSubscriptionValidationError) as cm:
            adapter.subscribe("SECRET_SYMBOL_XYZ", None)
        self.assertNotIn("SECRET_SYMBOL_XYZ", str(cm.exception))


class TestStop(unittest.TestCase):
    def test_stop_from_new_no_underlying_call(self):
        client = FakeClient()
        adapter = _adapter(client)
        adapter.stop()
        self.assertIs(adapter.state, QuoteSubscriptionState.STOPPED)
        self.assertEqual(client.calls, [])

    def test_stop_from_active_unsubscribes_once(self):
        client = FakeClient()
        adapter = _subscribed(client)
        adapter.stop()
        self.assertEqual(client.calls, [
            ("subscribe_quote", "600000.SH", "tick", "", "", 0),
            ("unsubscribe_quote", 42),
        ])
        self.assertIs(adapter.state, QuoteSubscriptionState.STOPPED)

    def test_stop_is_idempotent(self):
        client = FakeClient()
        adapter = _subscribed(client)
        adapter.stop()
        adapter.stop()
        adapter.stop()
        self.assertEqual(_unsub_call_count(client), 1)

    def test_sequence_id_zero_passed_exactly_once(self):
        client = FakeClient()
        client.seq = 0
        adapter = _adapter(client)
        adapter.subscribe("600000.SH", _cb())
        adapter.stop()
        self.assertEqual(client.calls, [
            ("subscribe_quote", "600000.SH", "tick", "", "", 0),
            ("unsubscribe_quote", 0),
        ])
        self.assertEqual(_unsub_call_count(client), 1)
        self.assertIs(adapter.state, QuoteSubscriptionState.STOPPED)

    def test_sequence_id_positive_passed_exactly_once(self):
        client = FakeClient()
        client.seq = 7
        adapter = _adapter(client)
        adapter.subscribe("600000.SH", _cb())
        adapter.stop()
        self.assertEqual(client.calls[-1], ("unsubscribe_quote", 7))
        self.assertEqual(_unsub_call_count(client), 1)

    def test_unsubscribe_none_result_is_success(self):
        client = FakeClient()
        client.unsub_result = None
        adapter = _subscribed(client)
        adapter.stop()
        self.assertIs(adapter.state, QuoteSubscriptionState.STOPPED)

    def test_unsubscribe_any_return_is_success(self):
        for bad in (0, 1, "", {}, "n/a"):
            client = FakeClient()
            client.unsub_result = bad
            adapter = _subscribed(client)
            adapter.stop()
            self.assertIs(adapter.state, QuoteSubscriptionState.STOPPED)


class TestFailures(unittest.TestCase):
    def _assert_safe_graph(self, exc, secret):
        self.assertIsNone(exc.__cause__)
        self.assertIsNone(exc.__context__)
        self.assertNotIn(secret, str(exc))
        seen = set()
        stack = [exc]
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            self.assertNotIn(secret, str(node))
            for attr in ("__cause__", "__context__"):
                child = getattr(node, attr, None)
                if child is not None:
                    self.assertNotIn(secret, str(child))
                    stack.append(child)

    def test_subscribe_exception_safe(self):
        client = FakeClient()
        client.set_exception("subscribe_quote", lambda: RuntimeError("SUBSCRIBE_SECRET_XYZ"))
        adapter = _adapter(client)
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(QuoteSubscriptionStartError) as cm:
                adapter.subscribe("600000.SH", _cb())
        self.assertEqual(str(cm.exception), "subscribe_quote failed: RuntimeError")
        self._assert_safe_graph(cm.exception, "SUBSCRIBE_SECRET_XYZ")
        self.assertNotIn("SUBSCRIBE_SECRET_XYZ", out.getvalue())
        self.assertNotIn("SUBSCRIBE_SECRET_XYZ", err.getvalue())
        self.assertIs(adapter.state, QuoteSubscriptionState.FAILED)
        self.assertEqual(adapter.failure_type, "RuntimeError")

    def test_unsubscribe_exception_safe_and_no_retry(self):
        client = FakeClient()
        client.set_exception("unsubscribe_quote", lambda: RuntimeError("UNSUBSCRIBE_SECRET_XYZ"))
        adapter = _subscribed(client)
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(QuoteSubscriptionStopError) as cm:
                adapter.stop()
        self.assertEqual(str(cm.exception), "unsubscribe_quote failed: RuntimeError")
        self._assert_safe_graph(cm.exception, "UNSUBSCRIBE_SECRET_XYZ")
        self.assertNotIn("UNSUBSCRIBE_SECRET_XYZ", out.getvalue())
        self.assertNotIn("UNSUBSCRIBE_SECRET_XYZ", err.getvalue())
        self.assertIs(adapter.state, QuoteSubscriptionState.FAILED)
        self.assertEqual(adapter.failure_type, "RuntimeError")
        # cleanup considered attempted; a second stop does not retry.
        adapter.stop()
        self.assertEqual(_unsub_call_count(client), 1)

    def test_failed_after_subscribe_cleanup_once(self):
        client = FakeClient()
        client.set_exception("unsubscribe_quote", lambda: RuntimeError())
        adapter = _subscribed(client)
        with self.assertRaises(QuoteSubscriptionStopError):
            adapter.stop()
        # state FAILED, but a second stop must not retry the unsubscribe.
        adapter.stop()
        self.assertEqual(_unsub_call_count(client), 1)
        self.assertIs(adapter.state, QuoteSubscriptionState.FAILED)

    def test_stop_after_invalid_return_does_not_unsubscribe(self):
        # REV-G1T004-001: a failed subscribe never produced a valid sequence id,
        # so stop() must not call unsubscribe_quote(None).
        client = FakeClient()
        client.seq = -1
        adapter = _adapter(client)
        with self.assertRaises(QuoteSubscriptionStartError):
            adapter.subscribe("600000.SH", _cb())
        adapter.stop()
        adapter.stop()
        self.assertEqual(_unsub_call_count(client), 0)
        self.assertIs(adapter.state, QuoteSubscriptionState.FAILED)
        self.assertIsNone(adapter.sequence_id)

    def test_stop_after_subscribe_exception_does_not_unsubscribe(self):
        client = FakeClient()
        client.set_exception("subscribe_quote", lambda: RuntimeError())
        adapter = _adapter(client)
        with self.assertRaises(QuoteSubscriptionStartError):
            adapter.subscribe("600000.SH", _cb())
        adapter.stop()
        self.assertEqual(_unsub_call_count(client), 0)
        self.assertIs(adapter.state, QuoteSubscriptionState.FAILED)

    def test_raise_if_failed_reports_type_only(self):
        client = FakeClient()
        client.set_exception("subscribe_quote", lambda: RuntimeError("SECRET_XYZ"))
        adapter = _adapter(client)
        with self.assertRaises(QuoteSubscriptionStartError):
            adapter.subscribe("600000.SH", _cb())
        with self.assertRaises(QuoteSubscriptionError) as cm:
            adapter.raise_if_failed()
        self.assertIn("RuntimeError", str(cm.exception))
        self.assertNotIn("SECRET_XYZ", str(cm.exception))

    def test_raise_if_failed_noop_when_not_failed(self):
        adapter = _subscribed()
        adapter.raise_if_failed()
        adapter.stop()
        adapter.raise_if_failed()


class TestBaseExceptionPropagation(unittest.TestCase):
    def test_keyboard_interrupt_during_subscribe_propagates(self):
        client = FakeClient()
        client.set_exception("subscribe_quote", lambda: KeyboardInterrupt("INT_SECRET_XYZ"))
        adapter = _adapter(client)
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(KeyboardInterrupt):
                adapter.subscribe("600000.SH", _cb())
        self.assertIs(adapter.state, QuoteSubscriptionState.FAILED)
        self.assertEqual(adapter.failure_type, "KeyboardInterrupt")
        self.assertNotIn("INT_SECRET_XYZ", out.getvalue())
        self.assertNotIn("INT_SECRET_XYZ", err.getvalue())
        # subscribe never succeeded -> no cleanup (REV-G1T004-001)
        adapter.stop()
        self.assertEqual(_unsub_call_count(client), 0)

    def test_keyboard_interrupt_during_subscribe_no_cleanup(self):
        client = FakeClient()
        client.set_exception("subscribe_quote", lambda: KeyboardInterrupt())
        adapter = _adapter(client)
        with self.assertRaises(KeyboardInterrupt):
            adapter.subscribe("600000.SH", _cb())
        self.assertIs(adapter.state, QuoteSubscriptionState.FAILED)
        adapter.stop()
        self.assertEqual(_unsub_call_count(client), 0)

    def test_keyboard_interrupt_during_stop_propagates_once(self):
        client = FakeClient()
        client.set_exception("unsubscribe_quote", lambda: KeyboardInterrupt())
        adapter = _subscribed(client)
        with self.assertRaises(KeyboardInterrupt):
            adapter.stop()
        self.assertIs(adapter.state, QuoteSubscriptionState.FAILED)
        self.assertEqual(adapter.failure_type, "KeyboardInterrupt")
        adapter.stop()  # cleanup attempted once; no second underlying call
        self.assertEqual(_unsub_call_count(client), 1)

    def test_system_exit_during_subscribe_propagates(self):
        client = FakeClient()
        client.set_exception("subscribe_quote", lambda: SystemExit(3))
        adapter = _adapter(client)
        with self.assertRaises(SystemExit):
            adapter.subscribe("600000.SH", _cb())
        self.assertIs(adapter.state, QuoteSubscriptionState.FAILED)
        self.assertEqual(adapter.failure_type, "SystemExit")


class TestSecurityBoundary(unittest.TestCase):
    def test_adapter_has_no_dangerous_api(self):
        adapter = _adapter(DangerousClient())
        for name in _FORBIDDEN_NAMES + ("raw_client", "client"):
            self.assertFalse(hasattr(adapter, name), msg=f"adapter must not expose {name}")
        for name in ("download_history_data", "query_stock_asset", "connect",
                     "order_stock", "cancel_order_stock", "call", "forward",
                     "subscribe_quote", "unsubscribe_quote"):
            with self.assertRaises(AttributeError):
                getattr(adapter, name)

    def test_normal_use_leaves_danger_count_zero(self):
        client = DangerousClient()
        adapter = _adapter(client)
        adapter.subscribe("600000.SH", _cb())
        adapter.stop()
        self.assertEqual(client.danger_calls, [])

    def test_injected_client_not_reachable_publicly(self):
        client = DangerousClient()
        adapter = _adapter(client)
        self.assertNotIn("client", vars(adapter))
        self.assertNotIn("raw_client", vars(adapter))

    def test_frozen_methods_after_construction(self):
        client = DangerousClient()
        adapter = _adapter(client)

        def evil_subscribe(*a, **k):
            client.danger_calls.append(("evil_subscribe", a, k))
            return 999

        client.subscribe_quote = evil_subscribe
        seq = adapter.subscribe("600000.SH", _cb())
        self.assertEqual(seq, 42)  # frozen original returned
        self.assertEqual(client.danger_calls, [])

    def test_replaced_stop_uses_frozen_callable(self):
        client = DangerousClient()
        adapter = _subscribed(client)

        def evil_unsubscribe(seq):
            client.danger_calls.append(("evil_unsubscribe", seq))

        client.unsubscribe_quote = evil_unsubscribe
        adapter.stop()
        self.assertEqual(_unsub_call_count(client), 1)
        self.assertEqual(client.danger_calls, [])


class TestProductionModuleSafety(unittest.TestCase):
    def test_adapter_source_is_clean(self):
        src = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "tgrid"
            / "adapters"
            / "quote_subscription_readonly.py"
        )
        text = src.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(src))
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
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                self.assertNotIn(name, _FORBIDDEN_NAMES)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
                args = node.args
                self.assertTrue(
                    len(args) < 2 or (isinstance(args[1], ast.Constant) and isinstance(args[1].value, str)),
                    msg="dynamic getattr name in production source",
                )


if __name__ == "__main__":
    unittest.main()
