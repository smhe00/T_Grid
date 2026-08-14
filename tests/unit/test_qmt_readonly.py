"""Tests for the offline read-only QMT Trader adapter (G1-T002).

All tests use fake clients only: nothing here imports or touches XtQuant, and
nothing connects to QMT or reads real accounts/market data.
"""

import ast
import contextlib
import io
import threading
import unittest
from pathlib import Path

from tgrid import (
    ReadOnlyTraderAdapter,
    ReadOnlyTraderState,
)
from tgrid.risk.exceptions import (
    QmtAdapterConfigError,
    QmtAdapterLifecycleError,
    QmtConnectionError,
    QmtQueryError,
    QmtReadOnlyError,
    TGridError,
)

_METHODS = (
    "start",
    "connect",
    "subscribe",
    "query_stock_asset",
    "query_stock_positions",
    "query_stock_orders",
    "query_stock_trades",
    "stop",
)

_FORBIDDEN_NAMES = (
    "order_stock",
    "order_stock_async",
    "cancel_order_stock",
    "cancel_order_stock_async",
    "cancel_order_stock_sysid",
    "cancel_order_stock_sysid_async",
    "cancel_order",
)


class FakeClient:
    """Records calls and returns configurable results / raises configured exceptions."""

    def __init__(self):
        self.calls = []
        self.results = {
            "start": None,
            "connect": 0,
            "subscribe": 0,
            "query_stock_asset": ("asset", 100),
            "query_stock_positions": (("pos",),),
            "query_stock_orders": (("ord",),),
            "query_stock_trades": (("trade",),),
            "stop": None,
        }
        self.exceptions = {}

    def set_result(self, name, value):
        self.results[name] = value

    def set_exception(self, name, factory):
        self.exceptions[name] = factory

    def _record(self, name, *args):
        self.calls.append((name, args))
        if name in self.exceptions:
            raise self.exceptions[name]()
        return self.results[name]

    def start(self):
        return self._record("start")

    def connect(self):
        return self._record("connect")

    def subscribe(self, account):
        return self._record("subscribe", account)

    def query_stock_asset(self, account):
        return self._record("query_stock_asset", account)

    def query_stock_positions(self, account):
        return self._record("query_stock_positions", account)

    def query_stock_orders(self, account, cancelable_only):
        return self._record("query_stock_orders", account, cancelable_only)

    def query_stock_trades(self, account):
        return self._record("query_stock_trades", account)

    def stop(self):
        return self._record("stop")


class DangerousClient(FakeClient):
    """Exposes a full order/cancel surface the adapter must never reach."""

    def __init__(self):
        super().__init__()
        self.danger_calls = []

    def order_stock(self, *args, **kwargs):
        self.danger_calls.append(("order_stock", args, kwargs))

    def cancel_order_stock(self, *args, **kwargs):
        self.danger_calls.append(("cancel_order_stock", args, kwargs))


class _MissingAttr:
    """Class attribute that behaves as if the attribute does not exist."""

    def __get__(self, obj, objtype=None):
        raise AttributeError("missing")


class _SecretDescriptor:
    """A raising descriptor whose secret must never surface at construction."""

    def __get__(self, obj, objtype=None):
        raise RuntimeError("CONSTRUCTOR_DESCRIPTOR_SECRET_XYZ")


class _DescriptorSecretClient(FakeClient):
    connect = _SecretDescriptor()


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
    return ReadOnlyTraderAdapter(client or FakeClient())


def _started(client=None):
    adapter = _adapter(client)
    adapter.start()
    return adapter


def _connected(client=None):
    adapter = _started(client)
    adapter.connect()
    return adapter


class TestConstructorValidation(unittest.TestCase):
    def test_none_client_rejected(self):
        with self.assertRaises(QmtAdapterConfigError):
            ReadOnlyTraderAdapter(None)

    def test_error_is_tgrid_subclass(self):
        with self.assertRaises(TGridError):
            ReadOnlyTraderAdapter(None)

    def test_missing_method_rejected(self):
        for name in _METHODS:
            client = _client_variant(missing=(name,))
            with self.assertRaises(QmtAdapterConfigError) as cm:
                ReadOnlyTraderAdapter(client)
            self.assertIn(name, str(cm.exception))

    def test_non_callable_method_rejected(self):
        for name in _METHODS:
            client = _client_variant(non_callable=(name,))
            with self.assertRaises(QmtAdapterConfigError) as cm:
                ReadOnlyTraderAdapter(client)
            self.assertIn(name, str(cm.exception))

    def test_multiple_missing_methods_reported(self):
        client = _client_variant(missing=("start", "stop"))
        with self.assertRaises(QmtAdapterConfigError) as cm:
            ReadOnlyTraderAdapter(client)
        self.assertIn("start", str(cm.exception))
        self.assertIn("stop", str(cm.exception))

    def test_error_has_type_name_no_client_repr(self):
        client = _client_variant(missing=("stop",), repr_secret="REPR_SECRET_XYZ")
        with self.assertRaises(QmtAdapterConfigError) as cm:
            ReadOnlyTraderAdapter(client)
        self.assertIn("PartialClient", str(cm.exception))
        self.assertIn("stop", str(cm.exception))
        self.assertNotIn("REPR_SECRET_XYZ", str(cm.exception))

    def test_valid_client_accepted(self):
        adapter = _adapter(FakeClient())
        self.assertIs(adapter.state, ReadOnlyTraderState.NEW)

    def test_constructor_descriptor_secret_not_leaked(self):
        # REV-G1T002-002: a raising descriptor during attribute resolution is a
        # configuration failure; the original exception must not surface in
        # text, cause or context.
        client = _DescriptorSecretClient()
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(QmtAdapterConfigError) as cm:
                ReadOnlyTraderAdapter(client)
        exc = cm.exception
        self.assertIn("connect", str(exc))
        self.assertIn("_DescriptorSecretClient", str(exc))
        self.assertIsNone(exc.__cause__)
        self.assertIsNone(exc.__context__)
        self.assertNotIn("CONSTRUCTOR_DESCRIPTOR_SECRET_XYZ", str(exc))
        self.assertNotIn("CONSTRUCTOR_DESCRIPTOR_SECRET_XYZ", out.getvalue())
        self.assertNotIn("CONSTRUCTOR_DESCRIPTOR_SECRET_XYZ", err.getvalue())

    def test_constructor_missing_attribute_name_reported(self):
        client = _client_variant(missing=("stop",))
        with self.assertRaises(QmtAdapterConfigError) as cm:
            ReadOnlyTraderAdapter(client)
        self.assertIn("stop", str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)
        self.assertIsNone(cm.exception.__context__)


class TestLifecycle(unittest.TestCase):
    def test_initial_state_new(self):
        self.assertIs(_adapter().state, ReadOnlyTraderState.NEW)

    def test_happy_path_full_lifecycle(self):
        client = FakeClient()
        adapter = ReadOnlyTraderAdapter(client)
        adapter.start()
        self.assertIs(adapter.state, ReadOnlyTraderState.STARTED)
        self.assertEqual(client.calls.count(("start", ())), 1)
        adapter.connect()
        self.assertIs(adapter.state, ReadOnlyTraderState.CONNECTED)
        self.assertEqual(client.calls.count(("connect", ())), 1)
        adapter.subscribe("acc")
        self.assertEqual(client.calls[-1], ("subscribe", ("acc",)))
        self.assertIs(adapter.state, ReadOnlyTraderState.CONNECTED)
        adapter.stop()
        self.assertIs(adapter.state, ReadOnlyTraderState.STOPPED)
        self.assertEqual(client.calls.count(("stop", ())), 1)

    def test_start_is_idempotent(self):
        client = FakeClient()
        adapter = ReadOnlyTraderAdapter(client)
        adapter.start()
        adapter.start()
        adapter.start()
        self.assertEqual(client.calls.count(("start", ())), 1)
        self.assertIs(adapter.state, ReadOnlyTraderState.STARTED)

    def test_start_idempotent_after_connect(self):
        client = FakeClient()
        adapter = ReadOnlyTraderAdapter(client)
        adapter.start()
        adapter.connect()
        adapter.start()
        self.assertEqual(client.calls.count(("start", ())), 1)
        self.assertIs(adapter.state, ReadOnlyTraderState.CONNECTED)

    def test_restart_after_stop_rejected(self):
        client = FakeClient()
        adapter = ReadOnlyTraderAdapter(client)
        adapter.start()
        adapter.stop()
        with self.assertRaises(QmtAdapterLifecycleError):
            adapter.start()
        self.assertEqual(client.calls.count(("start", ())), 1)

    def test_restart_after_failed_rejected(self):
        client = FakeClient()
        client.set_exception("connect", lambda: RuntimeError())
        adapter = _started(client)
        with self.assertRaises(QmtConnectionError):
            adapter.connect()
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        with self.assertRaises(QmtAdapterLifecycleError):
            adapter.start()

    def test_connect_requires_started(self):
        client = FakeClient()
        adapter = ReadOnlyTraderAdapter(client)
        with self.assertRaises(QmtAdapterLifecycleError):
            adapter.connect()
        self.assertEqual(client.calls, [])
        self.assertIs(adapter.state, ReadOnlyTraderState.NEW)

    def test_connect_twice_rejected(self):
        adapter = _connected()
        with self.assertRaises(QmtAdapterLifecycleError):
            adapter.connect()

    def test_subscribe_requires_connected(self):
        client = FakeClient()
        adapter = _started(client)
        with self.assertRaises(QmtAdapterLifecycleError):
            adapter.subscribe("acc")
        self.assertNotIn(("subscribe", ("acc",)), client.calls)

    def test_query_requires_connected(self):
        client = FakeClient()
        adapter = _started(client)
        for call in (
            lambda: adapter.query_asset("acc"),
            lambda: adapter.query_positions("acc"),
            lambda: adapter.query_orders("acc"),
            lambda: adapter.query_trades("acc"),
        ):
            with self.assertRaises(QmtAdapterLifecycleError):
                call()
        self.assertEqual(client.calls, [("start", ())])

    def test_stop_from_new_no_underlying_call(self):
        client = FakeClient()
        adapter = ReadOnlyTraderAdapter(client)
        adapter.stop()
        self.assertIs(adapter.state, ReadOnlyTraderState.STOPPED)
        self.assertEqual(client.calls, [])

    def test_stop_is_idempotent(self):
        client = FakeClient()
        adapter = _connected(client)
        adapter.stop()
        adapter.stop()
        adapter.stop()
        self.assertEqual(client.calls.count(("stop", ())), 1)
        self.assertIs(adapter.state, ReadOnlyTraderState.STOPPED)

    def test_stop_after_failed_cleans_up_once_and_stays_failed(self):
        client = FakeClient()
        client.set_exception("query_stock_asset", lambda: RuntimeError())
        adapter = _connected(client)
        with self.assertRaises(QmtQueryError):
            adapter.query_asset("acc")
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(client.calls.count(("stop", ())), 0)
        adapter.stop()
        self.assertEqual(client.calls.count(("stop", ())), 1)
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        adapter.stop()
        self.assertEqual(client.calls.count(("stop", ())), 1)

    def test_stop_after_start_failed_no_cleanup(self):
        client = FakeClient()
        client.set_exception("start", lambda: RuntimeError())
        adapter = ReadOnlyTraderAdapter(client)
        with self.assertRaises(QmtAdapterLifecycleError):
            adapter.start()
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        adapter.stop()
        self.assertEqual(client.calls.count(("stop", ())), 0)
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)


class TestMethodMapping(unittest.TestCase):
    def test_queries_map_to_exact_client_methods(self):
        client = FakeClient()
        adapter = _connected(client)
        asset = adapter.query_asset("acc1")
        self.assertEqual(client.calls[-1], ("query_stock_asset", ("acc1",)))
        self.assertIs(asset, client.results["query_stock_asset"])
        positions = adapter.query_positions("acc1")
        self.assertEqual(client.calls[-1], ("query_stock_positions", ("acc1",)))
        self.assertIs(positions, client.results["query_stock_positions"])
        trades = adapter.query_trades("acc1")
        self.assertEqual(client.calls[-1], ("query_stock_trades", ("acc1",)))
        self.assertIs(trades, client.results["query_stock_trades"])

    def test_query_orders_passes_cancelable_only(self):
        client = FakeClient()
        adapter = _connected(client)
        orders_false = adapter.query_orders("acc1")
        self.assertEqual(client.calls[-1], ("query_stock_orders", ("acc1", False)))
        self.assertIs(orders_false, client.results["query_stock_orders"])
        orders_true = adapter.query_orders("acc1", cancelable_only=True)
        self.assertEqual(client.calls[-1], ("query_stock_orders", ("acc1", True)))
        self.assertIs(orders_true, client.results["query_stock_orders"])

    def test_subscribe_passes_account(self):
        client = FakeClient()
        adapter = _connected(client)
        adapter.subscribe("acc9")
        self.assertEqual(client.calls[-1], ("subscribe", ("acc9",)))

    def test_no_hidden_side_effects_in_query_order(self):
        client = FakeClient()
        adapter = _connected(client)
        adapter.query_asset("a")
        adapter.query_positions("a")
        adapter.query_orders("a")
        adapter.query_trades("a")
        expected = [
            ("query_stock_asset", ("a",)),
            ("query_stock_positions", ("a",)),
            ("query_stock_orders", ("a", False)),
            ("query_stock_trades", ("a",)),
        ]
        # [0] is start(), [1] is connect() from the connected setup.
        self.assertEqual(client.calls[2:], expected)


class TestConnectSubscribeResultValidation(unittest.TestCase):
    def test_connect_nonzero_rejected(self):
        client = FakeClient()
        client.set_result("connect", 1)
        adapter = _started(client)
        with self.assertRaises(QmtConnectionError) as cm:
            adapter.connect()
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(adapter.failure_type, "1")
        self.assertIn("non-zero", str(cm.exception))

    def test_connect_bool_rejected(self):
        client = FakeClient()
        client.set_result("connect", True)
        adapter = _started(client)
        with self.assertRaises(QmtConnectionError):
            adapter.connect()
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(adapter.failure_type, "bool")

    def test_connect_none_rejected(self):
        client = FakeClient()
        client.set_result("connect", None)
        adapter = _started(client)
        with self.assertRaises(QmtConnectionError):
            adapter.connect()
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(adapter.failure_type, "NoneType")

    def test_connect_float_rejected(self):
        client = FakeClient()
        client.set_result("connect", 0.0)
        adapter = _started(client)
        with self.assertRaises(QmtConnectionError):
            adapter.connect()
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(adapter.failure_type, "float")

    def test_connect_string_rejected(self):
        client = FakeClient()
        client.set_result("connect", "0")
        adapter = _started(client)
        with self.assertRaises(QmtConnectionError):
            adapter.connect()
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(adapter.failure_type, "str")

    def test_subscribe_nonzero_rejected(self):
        client = FakeClient()
        client.set_result("subscribe", 1)
        adapter = _connected(client)
        with self.assertRaises(QmtConnectionError):
            adapter.subscribe("acc")
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(adapter.failure_type, "1")

    def test_subscribe_bool_rejected(self):
        client = FakeClient()
        client.set_result("subscribe", True)
        adapter = _connected(client)
        with self.assertRaises(QmtConnectionError):
            adapter.subscribe("acc")
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(adapter.failure_type, "bool")


class TestQueryFailure(unittest.TestCase):
    def test_query_none_fails_closed(self):
        client = FakeClient()
        client.set_result("query_stock_asset", None)
        adapter = _connected(client)
        with self.assertRaises(QmtQueryError) as cm:
            adapter.query_asset("acc")
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(adapter.failure_type, "None result")
        self.assertIn("query_asset", str(cm.exception))

    def test_query_exception_fails_closed(self):
        client = FakeClient()
        client.set_exception("query_stock_positions", lambda: ValueError())
        adapter = _connected(client)
        with self.assertRaises(QmtQueryError):
            adapter.query_positions("acc")
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(adapter.failure_type, "ValueError")

    def test_query_orders_exception_fails_closed(self):
        client = FakeClient()
        client.set_exception("query_stock_orders", lambda: OSError())
        adapter = _connected(client)
        with self.assertRaises(QmtQueryError):
            adapter.query_orders("acc")
        self.assertEqual(adapter.failure_type, "OSError")

    def test_invalid_cancelable_only_rejected(self):
        adapter = _connected()
        for bad in (1, "yes", None, 0.5, object()):
            with self.assertRaises(QmtQueryError):
                adapter.query_orders("acc", cancelable_only=bad)
        # caller error: must not mark the adapter FAILED
        self.assertIs(adapter.state, ReadOnlyTraderState.CONNECTED)
        self.assertIsNone(adapter.failure_type)


class TestFailureInjectionSecret(unittest.TestCase):
    def _assert_safe_exception_graph(self, exc, secret):
        """Prove no original exception survives anywhere in the public graph.

        REV-G1T002-001 requires not only clean text but also ``__cause__ is
        None`` and ``__context__ is None``; walk the whole chain recursively so
        no original object can be reached through any attribute.
        """
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

    def test_query_secret_not_leaked(self):
        client = FakeClient()
        client.set_exception(
            "query_stock_asset", lambda: RuntimeError("QUERY_SECRET_XYZ")
        )
        adapter = _connected(client)
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(QmtQueryError) as cm:
                adapter.query_asset("acc")
        exc = cm.exception
        self.assertEqual(str(exc), "query_asset failed: RuntimeError")
        self._assert_safe_exception_graph(exc, "QUERY_SECRET_XYZ")
        for where, text in (
            ("stdout", out.getvalue()),
            ("stderr", err.getvalue()),
        ):
            self.assertNotIn("QUERY_SECRET_XYZ", text, msg=f"secret leaked to {where}")
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(adapter.failure_type, "RuntimeError")

    def test_connect_secret_not_leaked(self):
        client = FakeClient()
        client.set_exception("connect", lambda: RuntimeError("CONNECT_SECRET_XYZ"))
        adapter = _started(client)
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(QmtConnectionError) as cm:
                adapter.connect()
        exc = cm.exception
        self.assertEqual(str(exc), "connect failed: RuntimeError")
        self._assert_safe_exception_graph(exc, "CONNECT_SECRET_XYZ")
        self.assertNotIn("CONNECT_SECRET_XYZ", out.getvalue())
        self.assertNotIn("CONNECT_SECRET_XYZ", err.getvalue())
        self.assertEqual(adapter.failure_type, "RuntimeError")

    def test_start_secret_not_leaked(self):
        client = FakeClient()
        client.set_exception("start", lambda: RuntimeError("START_SECRET_XYZ"))
        adapter = ReadOnlyTraderAdapter(client)
        with self.assertRaises(QmtAdapterLifecycleError) as cm:
            adapter.start()
        self.assertEqual(str(cm.exception), "start failed: RuntimeError")
        self._assert_safe_exception_graph(cm.exception, "START_SECRET_XYZ")
        self.assertEqual(adapter.failure_type, "RuntimeError")

    def test_subscribe_secret_not_leaked(self):
        client = FakeClient()
        client.set_exception("subscribe", lambda: RuntimeError("SUBSCRIBE_SECRET_XYZ"))
        adapter = _connected(client)
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(QmtConnectionError) as cm:
                adapter.subscribe("acc")
        self.assertEqual(str(cm.exception), "subscribe failed: RuntimeError")
        self._assert_safe_exception_graph(cm.exception, "SUBSCRIBE_SECRET_XYZ")
        self.assertNotIn("SUBSCRIBE_SECRET_XYZ", out.getvalue())
        self.assertNotIn("SUBSCRIBE_SECRET_XYZ", err.getvalue())
        self.assertEqual(adapter.failure_type, "RuntimeError")

    def test_stop_secret_not_leaked(self):
        client = FakeClient()
        adapter = _connected(client)
        client.set_exception("stop", lambda: RuntimeError("STOP_SECRET_XYZ"))
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(QmtAdapterLifecycleError) as cm:
                adapter.stop()
        self.assertEqual(str(cm.exception), "stop failed: RuntimeError")
        self._assert_safe_exception_graph(cm.exception, "STOP_SECRET_XYZ")
        self.assertNotIn("STOP_SECRET_XYZ", out.getvalue())
        self.assertNotIn("STOP_SECRET_XYZ", err.getvalue())
        self.assertEqual(adapter.failure_type, "RuntimeError")

    def test_raise_if_failed_reports_type_only(self):
        client = FakeClient()
        client.set_exception("connect", lambda: RuntimeError("CONNECT_SECRET_XYZ"))
        adapter = _started(client)
        with self.assertRaises(QmtConnectionError):
            adapter.connect()
        with self.assertRaises(QmtReadOnlyError) as cm:
            adapter.raise_if_failed()
        self.assertIn("RuntimeError", str(cm.exception))
        self.assertNotIn("CONNECT_SECRET_XYZ", str(cm.exception))

    def test_raise_if_failed_noop_when_not_failed(self):
        adapter = _connected()
        adapter.raise_if_failed()  # must not raise
        adapter.start()  # still idempotent

    def test_failure_type_initial_none(self):
        adapter = _connected()
        self.assertIsNone(adapter.failure_type)


class TestBaseExceptionPropagation(unittest.TestCase):
    def test_keyboard_interrupt_during_start_propagates(self):
        client = FakeClient()
        client.set_exception("start", lambda: KeyboardInterrupt())
        adapter = ReadOnlyTraderAdapter(client)
        with self.assertRaises(KeyboardInterrupt):
            adapter.start()
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(adapter.failure_type, "KeyboardInterrupt")
        # start never succeeded -> no cleanup needed
        adapter.stop()
        self.assertEqual(client.calls.count(("stop", ())), 0)

    def test_keyboard_interrupt_during_connect_propagates_and_cleans_once(self):
        client = FakeClient()
        client.set_exception("connect", lambda: KeyboardInterrupt())
        adapter = _started(client)
        with self.assertRaises(KeyboardInterrupt):
            adapter.connect()
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(adapter.failure_type, "KeyboardInterrupt")
        adapter.stop()
        self.assertEqual(client.calls.count(("stop", ())), 1)
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        adapter.stop()
        self.assertEqual(client.calls.count(("stop", ())), 1)

    def test_keyboard_interrupt_during_query_propagates_and_cleans_once(self):
        client = FakeClient()
        client.set_exception("query_stock_asset", lambda: KeyboardInterrupt())
        adapter = _connected(client)
        with self.assertRaises(KeyboardInterrupt):
            adapter.query_asset("acc")
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(adapter.failure_type, "KeyboardInterrupt")
        adapter.stop()
        self.assertEqual(client.calls.count(("stop", ())), 1)

    def test_system_exit_during_subscribe_propagates(self):
        client = FakeClient()
        client.set_exception("subscribe", lambda: SystemExit(3))
        adapter = _connected(client)
        with self.assertRaises(SystemExit):
            adapter.subscribe("acc")
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(adapter.failure_type, "SystemExit")

    def test_generator_exit_during_stop_propagates_at_most_once(self):
        client = FakeClient()
        adapter = _connected(client)
        client.set_exception("stop", lambda: GeneratorExit())
        with self.assertRaises(GeneratorExit):
            adapter.stop()
        self.assertIs(adapter.state, ReadOnlyTraderState.FAILED)
        self.assertEqual(adapter.failure_type, "GeneratorExit")
        adapter.stop()  # idempotent: no second underlying attempt
        self.assertEqual(client.calls.count(("stop", ())), 1)

    def test_keyboard_interrupt_during_connect_secret_not_in_output(self):
        client = FakeClient()
        client.set_exception("connect", lambda: KeyboardInterrupt("INT_SECRET_XYZ"))
        adapter = _started(client)
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(KeyboardInterrupt):
                adapter.connect()
        self.assertNotIn("INT_SECRET_XYZ", out.getvalue())
        self.assertNotIn("INT_SECRET_XYZ", err.getvalue())
        self.assertEqual(adapter.failure_type, "KeyboardInterrupt")


class TestSecurityBoundary(unittest.TestCase):
    def test_adapter_has_no_order_or_cancel_api(self):
        client = DangerousClient()
        adapter = ReadOnlyTraderAdapter(client)
        for name in (
            "order_stock",
            "order_stock_async",
            "cancel_order_stock",
            "cancel_order_stock_async",
            "cancel_order",
            "call",
            "forward",
            "raw_client",
            "client",
        ):
            self.assertFalse(
                hasattr(adapter, name), msg=f"adapter must not expose {name}"
            )
        with self.assertRaises(AttributeError):
            adapter.order_stock
        with self.assertRaises(AttributeError):
            getattr(adapter, "cancel_order_stock")
        with self.assertRaises(AttributeError):
            adapter.call("order_stock", account="x")

    def test_full_lifecycle_leaves_danger_count_zero(self):
        client = DangerousClient()
        adapter = _connected(client)
        adapter.query_asset("acc")
        adapter.query_orders("acc", cancelable_only=True)
        adapter.subscribe("acc")
        adapter.stop()
        self.assertEqual(client.danger_calls, [])

    def test_injected_client_not_reachable_publicly(self):
        client = DangerousClient()
        adapter = ReadOnlyTraderAdapter(client)
        self.assertNotIn("client", vars(adapter))
        self.assertNotIn("raw_client", vars(adapter))

    def test_no_generic_getattr_forwarding(self):
        client = DangerousClient()
        adapter = ReadOnlyTraderAdapter(client)
        # getattr on the adapter must fail for anything not an adapter attribute.
        self.assertFalse(hasattr(adapter, "query_stock_orders"))
        with self.assertRaises(AttributeError):
            adapter.query_stock_orders  # noqa: B018

    def test_frozen_methods_after_construction(self):
        # REV-G1T002-002: the adapter freezes the resolved bound callables; a
        # client attribute replaced after construction must not be re-resolved.
        client = DangerousClient()
        adapter = _connected(client)
        original_asset = client.results["query_stock_asset"]

        def evil_query(account):
            client.danger_calls.append(("evil_query", account))
            return "EVIL"

        client.query_stock_asset = evil_query
        result = adapter.query_asset("acc")
        self.assertIs(result, original_asset)
        self.assertEqual(client.danger_calls, [])

    def test_replaced_method_cannot_forward_to_order(self):
        client = DangerousClient()
        adapter = _connected(client)

        def evil_positions(account):
            return client.order_stock(account, "SELL", 1, "LMT", 0.0, "s", "r")

        client.query_stock_positions = evil_positions
        result = adapter.query_positions("acc")
        self.assertEqual(result, (("pos",),))
        self.assertEqual(client.danger_calls, [])

    def test_frozen_stop_after_replacement(self):
        client = DangerousClient()
        adapter = _connected(client)

        def evil_stop():
            client.danger_calls.append(("evil_stop",))

        client.stop = evil_stop
        adapter.stop()
        # The frozen original stop was invoked (recorded once), not the evil one.
        self.assertEqual(client.calls.count(("stop", ())), 1)
        self.assertEqual(client.danger_calls, [])


class TestConcurrency(unittest.TestCase):
    def _threads(self, targets):
        threads = [threading.Thread(target=t) for t in targets]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        return threads

    def test_concurrent_start_calls_client_once(self):
        client = FakeClient()
        adapter = ReadOnlyTraderAdapter(client)
        barrier = threading.Barrier(2)
        errors = []

        def worker():
            barrier.wait()
            try:
                adapter.start()
            except BaseException as exc:  # noqa: BLE001
                errors.append(type(exc).__name__)

        threads = self._threads([worker, worker])
        for t in threads:
            self.assertFalse(t.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(client.calls.count(("start", ())), 1)
        self.assertIs(adapter.state, ReadOnlyTraderState.STARTED)

    def test_concurrent_stop_calls_client_once(self):
        client = FakeClient()
        adapter = _connected(client)
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            adapter.stop()

        threads = self._threads([worker, worker])
        for t in threads:
            self.assertFalse(t.is_alive())
        self.assertEqual(client.calls.count(("stop", ())), 1)
        self.assertIs(adapter.state, ReadOnlyTraderState.STOPPED)

    def test_concurrent_start_and_stop_no_deadlock(self):
        client = FakeClient()
        adapter = ReadOnlyTraderAdapter(client)
        errors = []

        def do_start():
            try:
                adapter.start()
            except BaseException as exc:  # noqa: BLE001
                errors.append(("start", type(exc).__name__))

        def do_stop():
            try:
                adapter.stop()
            except BaseException as exc:  # noqa: BLE001
                errors.append(("stop", type(exc).__name__))

        threads = self._threads([do_start, do_stop])
        for t in threads:
            self.assertFalse(t.is_alive())
        # Underlying calls at most once each, and if stop won first then start
        # must fail closed with a lifecycle error.
        self.assertLessEqual(client.calls.count(("start", ())), 1)
        self.assertLessEqual(client.calls.count(("stop", ())), 1)
        for tag, name in errors:
            self.assertEqual(tag, "start")
            self.assertEqual(name, "QmtAdapterLifecycleError")
        self.assertIs(adapter.state, ReadOnlyTraderState.STOPPED)

    def test_no_leftover_threads(self):
        client = FakeClient()
        adapter = _connected(client)
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            adapter.query_asset("acc")

        threads = self._threads([worker, worker])
        for t in threads:
            self.assertFalse(t.is_alive())
        self.assertEqual(client.calls.count(("query_stock_asset", ("acc",))), 2)
        adapter.stop()


class TestProductionModuleSafety(unittest.TestCase):
    def test_adapter_source_is_clean(self):
        src = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "tgrid"
            / "adapters"
            / "qmt_readonly.py"
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
        # Forbidden trading method names must not appear anywhere in the source.
        self.assertNotIn("order_stock", text)
        self.assertNotIn("cancel_order", text)


if __name__ == "__main__":
    unittest.main()
