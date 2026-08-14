"""Tests for the offline read-only MarketData query adapter (G1-T003).

All tests use fake clients only: nothing here imports or touches XtQuant, and
nothing subscribes, downloads, connects, or reads real market data.
"""

import ast
import contextlib
import io
import unittest
from collections.abc import Sequence
from pathlib import Path

from tgrid import (
    ReadOnlyMarketDataAdapter,
)
from tgrid.risk.exceptions import (
    MarketDataAdapterConfigError,
    MarketDataQueryError,
    MarketDataReadOnlyError,
    MarketDataValidationError,
    TGridError,
)

_METHODS = (
    "get_full_tick",
    "get_market_data",
    "get_market_data_ex",
    "get_instrument_detail",
    "get_divid_factors",
    "get_trading_calendar",
    "get_trading_dates",
    "get_trading_period",
)

_FORBIDDEN_NAMES = (
    "subscribe_quote",
    "unsubscribe_quote",
    "download_history_data",
    "download_history_data2",
    "download_sector_data",
    "download_financial_data",
    "download_cb_data",
    "download_etf_info",
    "download_tabular_data",
    "order_stock",
    "order_stock_async",
    "cancel_order_stock",
    "cancel_order_stock_async",
    "cancel_order",
    "call",
    "forward",
)


class FakeClient:
    """Records calls and returns configurable results / raises configured exceptions."""

    def __init__(self):
        self.calls = []
        self.results = {
            "get_full_tick": {"600000.SH": {"last": 10.0}},
            "get_market_data": {"600000.SH": {"close": [10.0]}},
            "get_market_data_ex": {"600000.SH": {"close": [10.0]}},
            "get_instrument_detail": {"code": "600000.SH"},
            "get_divid_factors": {"600000.SH": []},
            "get_trading_calendar": ["20260814"],
            "get_trading_dates": ["20260814"],
            "get_trading_period": {"600000.SH": ["093000", "150000"]},
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

    def get_full_tick(self, stock_codes):
        return self._record("get_full_tick", stock_codes)

    def get_market_data(self, *args):
        return self._record("get_market_data", *args)

    def get_market_data_ex(self, *args):
        return self._record("get_market_data_ex", *args)

    def get_instrument_detail(self, stock_code, complete):
        return self._record("get_instrument_detail", stock_code, complete)

    def get_divid_factors(self, stock_code, start_time, end_time):
        return self._record("get_divid_factors", stock_code, start_time, end_time)

    def get_trading_calendar(self, market, start_time, end_time):
        return self._record("get_trading_calendar", market, start_time, end_time)

    def get_trading_dates(self, market, start_time, end_time, count):
        return self._record("get_trading_dates", market, start_time, end_time, count)

    def get_trading_period(self, stock_code):
        return self._record("get_trading_period", stock_code)


class DangerousClient(FakeClient):
    """Exposes subscribe/download/order/cancel methods the adapter must never reach."""

    def __init__(self):
        super().__init__()
        self.danger_calls = []

    def subscribe_quote(self, *a, **k):
        self.danger_calls.append(("subscribe_quote", a, k))

    def unsubscribe_quote(self, *a, **k):
        self.danger_calls.append(("unsubscribe_quote", a, k))

    def download_history_data(self, *a, **k):
        self.danger_calls.append(("download_history_data", a, k))

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
    get_market_data = _SecretDescriptor()


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
    return ReadOnlyMarketDataAdapter(client or FakeClient())


# -- REV-G1T003-001: single-snapshot Sequence failure injections -------------


class LenBombSequence(list):
    """A Sequence whose ``__len__`` raises; snapshot must not call it."""

    def __len__(self):
        raise RuntimeError("LEN_SECRET_7A")


class FirstPassBombSequence(Sequence):
    """Iterator raises RuntimeError on the very first next(); must not leak."""

    def __len__(self):
        return 1

    def __getitem__(self, index):
        raise IndexError

    def __iter__(self):
        def gen():
            raise RuntimeError("FIRST_PASS_SECRET_9B")
            yield  # pragma: no cover

        return gen()


class ChangingSequence(Sequence):
    """Returns different content on each iteration; only one pass is allowed."""

    def __init__(self):
        self.passes = 0

    def __len__(self):
        return 1

    def __getitem__(self, index):
        raise IndexError

    def __iter__(self):
        self.passes += 1
        if self.passes == 1:
            return iter(["600000.SH"])
        return iter([""])


class SecretIteratorSequence(Sequence):
    """Iterator raises RuntimeError carrying a unique secret."""

    def __len__(self):
        return 1

    def __getitem__(self, index):
        raise IndexError

    def __iter__(self):
        def gen():
            raise RuntimeError("ITERATOR_SECRET_XYZ")
            yield  # pragma: no cover

        return gen()


class TestConstructorValidation(unittest.TestCase):
    def test_none_client_rejected(self):
        with self.assertRaises(MarketDataAdapterConfigError):
            ReadOnlyMarketDataAdapter(None)

    def test_error_is_tgrid_subclass(self):
        with self.assertRaises(TGridError):
            ReadOnlyMarketDataAdapter(None)

    def test_missing_method_rejected(self):
        for name in _METHODS:
            client = _client_variant(missing=(name,))
            with self.assertRaises(MarketDataAdapterConfigError) as cm:
                ReadOnlyMarketDataAdapter(client)
            self.assertIn(name, str(cm.exception))
            self.assertIsNone(cm.exception.__cause__)
            self.assertIsNone(cm.exception.__context__)

    def test_non_callable_method_rejected(self):
        for name in _METHODS:
            client = _client_variant(non_callable=(name,))
            with self.assertRaises(MarketDataAdapterConfigError) as cm:
                ReadOnlyMarketDataAdapter(client)
            self.assertIn(name, str(cm.exception))

    def test_error_has_type_name_no_client_repr(self):
        client = _client_variant(missing=("get_trading_period",), repr_secret="REPR_SECRET_XYZ")
        with self.assertRaises(MarketDataAdapterConfigError) as cm:
            ReadOnlyMarketDataAdapter(client)
        self.assertIn("PartialClient", str(cm.exception))
        self.assertIn("get_trading_period", str(cm.exception))
        self.assertNotIn("REPR_SECRET_XYZ", str(cm.exception))

    def test_valid_client_accepted(self):
        _adapter(FakeClient())

    def test_constructor_descriptor_secret_not_leaked(self):
        client = _DescriptorSecretClient()
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(MarketDataAdapterConfigError) as cm:
                ReadOnlyMarketDataAdapter(client)
        exc = cm.exception
        self.assertIn("get_market_data", str(exc))
        self.assertIn("_DescriptorSecretClient", str(exc))
        self.assertIsNone(exc.__cause__)
        self.assertIsNone(exc.__context__)
        for text in (str(exc), out.getvalue(), err.getvalue()):
            self.assertNotIn("CONSTRUCTOR_DESCRIPTOR_SECRET_XYZ", text)


class TestMethodMapping(unittest.TestCase):
    def test_all_eight_methods_map_exactly_once(self):
        client = FakeClient()
        adapter = _adapter(client)

        r1 = adapter.get_full_tick(["600000.SH", "000001.SZ"])
        self.assertEqual(client.calls[-1], ("get_full_tick", (["600000.SH", "000001.SZ"],)))
        self.assertIs(r1, client.results["get_full_tick"])

        r2 = adapter.get_market_data(
            ["close", "volume"], ["600000.SH"], "1d",
            start_time="20260801", end_time="20260814", count=5,
            dividend_type="front", fill_data=False,
        )
        self.assertEqual(
            client.calls[-1],
            ("get_market_data", (["close", "volume"], ["600000.SH"], "1d",
                                 "20260801", "20260814", 5, "front", False)),
        )
        self.assertIs(r2, client.results["get_market_data"])

        r3 = adapter.get_market_data_ex([], ["600000.SH"], "1m")
        self.assertEqual(
            client.calls[-1],
            ("get_market_data_ex", ([], ["600000.SH"], "1m", "", "", -1, "none", True)),
        )
        self.assertIs(r3, client.results["get_market_data_ex"])

        r4 = adapter.get_instrument_detail("600000.SH", complete=True)
        self.assertEqual(client.calls[-1], ("get_instrument_detail", ("600000.SH", True)))
        self.assertIs(r4, client.results["get_instrument_detail"])

        r5 = adapter.get_divid_factors("600000.SH", start_time="20260101", end_time="20260814")
        self.assertEqual(client.calls[-1], ("get_divid_factors", ("600000.SH", "20260101", "20260814")))
        self.assertIs(r5, client.results["get_divid_factors"])

        r6 = adapter.get_trading_calendar("SH", start_time="20260801", end_time="20260814")
        self.assertEqual(client.calls[-1], ("get_trading_calendar", ("SH", "20260801", "20260814")))
        self.assertIs(r6, client.results["get_trading_calendar"])

        r7 = adapter.get_trading_dates("SH", start_time="20260801", end_time="20260814", count=10)
        self.assertEqual(client.calls[-1], ("get_trading_dates", ("SH", "20260801", "20260814", 10)))
        self.assertIs(r7, client.results["get_trading_dates"])

        r8 = adapter.get_trading_period("600000.SH")
        self.assertEqual(client.calls[-1], ("get_trading_period", ("600000.SH",)))
        self.assertIs(r8, client.results["get_trading_period"])

    def test_market_data_defaults(self):
        client = FakeClient()
        adapter = _adapter(client)
        adapter.get_market_data(["close"], ["600000.SH"], "1d")
        self.assertEqual(
            client.calls[-1],
            ("get_market_data", (["close"], ["600000.SH"], "1d", "", "", -1, "none", True)),
        )
        adapter.get_market_data_ex(["close"], ["600000.SH"], "1d")
        self.assertEqual(
            client.calls[-1],
            ("get_market_data_ex", (["close"], ["600000.SH"], "1d", "", "", -1, "none", True)),
        )

    def test_sequences_copied_before_call(self):
        class MutatingClient(FakeClient):
            def get_full_tick(self, stock_codes):
                self.calls.append(("get_full_tick", stock_codes))
                stock_codes.append("MUTATED")  # mutate whatever list it received
                return self.results["get_full_tick"]

        client = MutatingClient()
        adapter = _adapter(client)
        codes = ["600000.SH"]
        adapter.get_full_tick(codes)
        self.assertEqual(codes, ["600000.SH"])  # caller container untouched
        self.assertEqual(client.calls[-1][1], ["600000.SH", "MUTATED"])  # underlying saw the copy

    def test_field_list_may_be_empty(self):
        client = FakeClient()
        adapter = _adapter(client)
        adapter.get_market_data([], ["600000.SH"], "1d")
        self.assertEqual(client.calls[-1], ("get_market_data", ([], ["600000.SH"], "1d", "", "", -1, "none", True)))


class TestValidation(unittest.TestCase):
    def _assert_rejected(self, adapter, call, param):
        with self.assertRaises(MarketDataValidationError) as cm:
            call()
        self.assertIn(param, str(cm.exception))

    def test_stock_codes_validation(self):
        adapter = _adapter()
        for bad in ("600000.SH", [""], ["ok", 1], [None], [], (), 5, None):
            self._assert_rejected(adapter, lambda bad=bad: adapter.get_full_tick(bad), "stock_codes")
        self.assertEqual(adapter._methods["get_full_tick"].__self__.calls, [])

    def test_market_data_stock_list_validation(self):
        adapter = _adapter()
        for bad in ("600000.SH", [], [""], ["ok", 2], None):
            self._assert_rejected(
                adapter, lambda bad=bad: adapter.get_market_data(["close"], bad, "1d"), "stock_list"
            )

    def test_market_data_field_list_validation(self):
        adapter = _adapter()
        for bad in ("close", ["close", ""], ["close", 1], None):
            self._assert_rejected(
                adapter, lambda bad=bad: adapter.get_market_data(bad, ["600000.SH"], "1d"), "field_list"
            )

    def test_market_data_period_validation(self):
        adapter = _adapter()
        for bad in ("", None, 5, True):
            self._assert_rejected(
                adapter, lambda bad=bad: adapter.get_market_data([], ["600000.SH"], bad), "period"
            )

    def test_time_and_dividend_must_be_string(self):
        adapter = _adapter()
        for kwargs in (
            {"start_time": 20260801},
            {"end_time": None},
            {"dividend_type": 3},
        ):
            name = next(iter(kwargs))
            self._assert_rejected(
                adapter,
                lambda kwargs=kwargs: adapter.get_market_data([], ["600000.SH"], "1d", **kwargs),
                name,
            )

    def test_count_validation(self):
        adapter = _adapter()
        for bad in (0, -2, 3.5, True, "5", None):
            self._assert_rejected(
                adapter,
                lambda bad=bad: adapter.get_trading_dates("SH", start_time="a", end_time="b", count=bad),
                "count",
            )
        # -1 and positive ints accepted
        adapter.get_trading_dates("SH", count=1)
        adapter.get_trading_dates("SH", count=-1)

    def test_bool_validation(self):
        adapter = _adapter()
        for bad in (1, "yes", None, 0):
            self._assert_rejected(
                adapter, lambda bad=bad: adapter.get_instrument_detail("600000.SH", complete=bad), "complete"
            )
            self._assert_rejected(
                adapter,
                lambda bad=bad: adapter.get_market_data([], ["600000.SH"], "1d", fill_data=bad),
                "fill_data",
            )

    def test_single_code_and_market_validation(self):
        adapter = _adapter()
        for bad in ("", None, 5):
            self._assert_rejected(adapter, lambda bad=bad: adapter.get_instrument_detail(bad), "stock_code")
            self._assert_rejected(adapter, lambda bad=bad: adapter.get_trading_calendar(bad), "market")
            self._assert_rejected(adapter, lambda bad=bad: adapter.get_trading_period(bad), "stock_code")

    def test_validation_error_has_no_illegal_value(self):
        adapter = _adapter()
        with self.assertRaises(MarketDataValidationError) as cm:
            adapter.get_full_tick("SECRET_SYMBOL_XYZ")
        self.assertNotIn("SECRET_SYMBOL_XYZ", str(cm.exception))

    def test_validation_failure_calls_nothing(self):
        client = FakeClient()
        adapter = _adapter(client)
        with self.assertRaises(MarketDataValidationError):
            adapter.get_full_tick([])
        self.assertEqual(client.calls, [])


class TestSingleSnapshotSequence(unittest.TestCase):
    """REV-G1T003-001: sequences are materialized exactly once, safely."""

    def test_len_bomb_is_unaffected(self):
        # list() uses iteration, not __len__; a raising __len__ must not matter.
        client = FakeClient()
        adapter = _adapter(client)
        codes = LenBombSequence(["600000.SH"])
        result = adapter.get_full_tick(codes)
        self.assertIs(result, client.results["get_full_tick"])
        self.assertEqual(client.calls[-1], ("get_full_tick", (["600000.SH"],)))

    def test_first_pass_iterator_bomb_becomes_safe_validation_error(self):
        client = FakeClient()
        adapter = _adapter(client)
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(MarketDataValidationError) as cm:
                adapter.get_full_tick(FirstPassBombSequence())
        exc = cm.exception
        self.assertEqual(str(exc), "stock_codes: expected a non-string sequence of non-empty strings")
        self.assertIsNone(exc.__cause__)
        self.assertIsNone(exc.__context__)
        for text in (str(exc), out.getvalue(), err.getvalue()):
            self.assertNotIn("FIRST_PASS_SECRET_9B", text)
        self.assertEqual(client.calls, [])

    def test_changing_sequence_uses_first_snapshot_only(self):
        client = FakeClient()
        adapter = _adapter(client)
        seq = ChangingSequence()
        adapter.get_full_tick(seq)
        # Only one pass was observed; the validated snapshot is what reached the client.
        self.assertEqual(seq.passes, 1)
        self.assertEqual(client.calls[-1], ("get_full_tick", (["600000.SH"],)))
        self.assertNotIn(("get_full_tick", ([""],)), client.calls)

    def test_secret_iterator_exception_not_leaked(self):
        client = FakeClient()
        adapter = _adapter(client)
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(MarketDataValidationError) as cm:
                adapter.get_full_tick(SecretIteratorSequence())
        exc = cm.exception
        self.assertIsNone(exc.__cause__)
        self.assertIsNone(exc.__context__)
        for text in (str(exc), out.getvalue(), err.getvalue()):
            self.assertNotIn("ITERATOR_SECRET_XYZ", text)
        self.assertEqual(client.calls, [])

    def test_market_data_snapshot_shared_for_validation_and_call(self):
        client = FakeClient()
        adapter = _adapter(client)
        stocks = ChangingSequence()
        adapter.get_market_data([], stocks, "1d")
        self.assertEqual(stocks.passes, 1)
        self.assertEqual(
            client.calls[-1],
            ("get_market_data", ([], ["600000.SH"], "1d", "", "", -1, "none", True)),
        )


class TestQueryFailure(unittest.TestCase):
    def _assert_safe_graph(self, exc, secret):
        self.assertIsNone(exc.__cause__)
        self.assertIsNone(exc.__context__)
        if secret:
            self.assertNotIn(secret, str(exc))
        seen = set()
        stack = [exc]
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            if secret:
                self.assertNotIn(secret, str(node))
            for attr in ("__cause__", "__context__"):
                child = getattr(node, attr, None)
                if child is not None:
                    if secret:
                        self.assertNotIn(secret, str(child))
                    stack.append(child)

    def test_none_result_fails_closed(self):
        client = FakeClient()
        client.set_result("get_full_tick", None)
        adapter = _adapter(client)
        with self.assertRaises(MarketDataQueryError) as cm:
            adapter.get_full_tick(["600000.SH"])
        self.assertEqual(str(cm.exception), "get_full_tick returned None")
        self._assert_safe_graph(cm.exception, "")

    def test_empty_container_is_valid_result(self):
        client = FakeClient()
        client.set_result("get_full_tick", {})
        client.set_result("get_market_data", {})
        adapter = _adapter(client)
        self.assertEqual(adapter.get_full_tick(["600000.SH"]), {})
        self.assertEqual(adapter.get_market_data([], ["600000.SH"], "1d"), {})

    def test_all_eight_secret_failures_safe(self):
        calls = {
            "get_full_tick": lambda a: a.get_full_tick(["600000.SH"]),
            "get_market_data": lambda a: a.get_market_data([], ["600000.SH"], "1d"),
            "get_market_data_ex": lambda a: a.get_market_data_ex([], ["600000.SH"], "1d"),
            "get_instrument_detail": lambda a: a.get_instrument_detail("600000.SH"),
            "get_divid_factors": lambda a: a.get_divid_factors("600000.SH"),
            "get_trading_calendar": lambda a: a.get_trading_calendar("SH"),
            "get_trading_dates": lambda a: a.get_trading_dates("SH"),
            "get_trading_period": lambda a: a.get_trading_period("600000.SH"),
        }
        for name, invoke in calls.items():
            client = FakeClient()
            client.set_exception(name, lambda: RuntimeError("UNIQUE_SECRET_XYZ"))
            adapter = _adapter(client)
            out = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with self.assertRaises(MarketDataQueryError) as cm:
                    invoke(adapter)
            self.assertEqual(str(cm.exception), f"{name} failed: RuntimeError")
            self._assert_safe_graph(cm.exception, "UNIQUE_SECRET_XYZ")
            self.assertNotIn("UNIQUE_SECRET_XYZ", out.getvalue())
            self.assertNotIn("UNIQUE_SECRET_XYZ", err.getvalue())

    def test_query_error_is_tgrid_subclass(self):
        client = FakeClient()
        client.set_exception("get_full_tick", lambda: RuntimeError())
        adapter = _adapter(client)
        with self.assertRaises(MarketDataReadOnlyError):
            adapter.get_full_tick(["600000.SH"])


class TestBaseExceptionPropagation(unittest.TestCase):
    def test_keyboard_interrupt_propagates(self):
        for name in ("get_full_tick", "get_market_data", "get_trading_dates"):
            client = FakeClient()
            client.set_exception(name, lambda: KeyboardInterrupt("INT_SECRET"))
            adapter = _adapter(client)
            out = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with self.assertRaises(KeyboardInterrupt):
                    {
                        "get_full_tick": lambda: adapter.get_full_tick(["600000.SH"]),
                        "get_market_data": lambda: adapter.get_market_data([], ["600000.SH"], "1d"),
                        "get_trading_dates": lambda: adapter.get_trading_dates("SH"),
                    }[name]()
            self.assertNotIn("INT_SECRET", out.getvalue())
            self.assertNotIn("INT_SECRET", err.getvalue())

    def test_system_exit_and_generator_exit_propagate(self):
        client = FakeClient()
        client.set_exception("get_divid_factors", lambda: SystemExit(3))
        adapter = _adapter(client)
        with self.assertRaises(SystemExit):
            adapter.get_divid_factors("600000.SH")

        client2 = FakeClient()
        client2.set_exception("get_instrument_detail", lambda: GeneratorExit())
        adapter2 = _adapter(client2)
        with self.assertRaises(GeneratorExit):
            adapter2.get_instrument_detail("600000.SH")


class TestSecurityBoundary(unittest.TestCase):
    def test_adapter_has_no_dangerous_api(self):
        adapter = _adapter(DangerousClient())
        for name in _FORBIDDEN_NAMES + ("raw_client", "client"):
            self.assertFalse(hasattr(adapter, name), msg=f"adapter must not expose {name}")
        for name in ("subscribe_quote", "unsubscribe_quote", "download_history_data",
                     "order_stock", "cancel_order_stock", "call", "forward"):
            with self.assertRaises(AttributeError):
                getattr(adapter, name)

    def test_normal_use_leaves_danger_count_zero(self):
        client = DangerousClient()
        adapter = _adapter(client)
        adapter.get_full_tick(["600000.SH"])
        adapter.get_market_data([], ["600000.SH"], "1d")
        adapter.get_trading_dates("SH")
        self.assertEqual(client.danger_calls, [])

    def test_injected_client_not_reachable_publicly(self):
        client = DangerousClient()
        adapter = _adapter(client)
        self.assertNotIn("client", vars(adapter))
        self.assertNotIn("raw_client", vars(adapter))

    def test_frozen_methods_after_construction(self):
        client = DangerousClient()
        adapter = _adapter(client)
        original = client.results["get_full_tick"]

        def evil(codes):
            client.danger_calls.append(("evil_full_tick", codes))
            return "EVIL"

        client.get_full_tick = evil
        result = adapter.get_full_tick(["600000.SH"])
        self.assertIs(result, original)
        self.assertEqual(client.danger_calls, [])

    def test_replaced_method_cannot_forward_to_order(self):
        client = DangerousClient()
        adapter = _adapter(client)

        def evil_md(*args):
            return client.order_stock("acc", "600000.SH")

        client.get_market_data = evil_md
        result = adapter.get_market_data([], ["600000.SH"], "1d")
        self.assertIs(result, client.results["get_market_data"])
        self.assertEqual(client.danger_calls, [])


class TestProductionModuleSafety(unittest.TestCase):
    def test_adapter_source_is_clean(self):
        src = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "tgrid"
            / "adapters"
            / "marketdata_readonly.py"
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
        for forbidden in ("subscribe_quote", "unsubscribe_quote", "download_", "order_", "cancel_"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
