"""Tests for the offline Gate 1 read-only integration probe orchestrator (G1-T005).

All tests construct real ``ReadOnlyTraderAdapter`` / ``ReadOnlyMarketDataAdapter``
instances over fake clients; nothing imports XtQuant or connects to QMT.
"""

import ast
import contextlib
import io
import unittest
from pathlib import Path

from tgrid import (
    Gate1ProbeConfigError,
    Gate1ProbeError,
    Gate1ProbeExecutionError,
    Gate1ReadOnlyProbeSummary,
    ReadOnlyMarketDataAdapter,
    ReadOnlyTraderAdapter,
    run_gate1_readonly_probe,
    TGridError,
)

_ALL_NAMES = (
    "trader.start",
    "trader.connect",
    "trader.subscribe",
    "trader.query_asset",
    "trader.query_positions",
    "trader.query_orders",
    "trader.query_trades",
    "market_data.get_full_tick",
    "market_data.get_market_data",
    "market_data.get_market_data_ex",
    "market_data.get_instrument_detail",
    "market_data.get_divid_factors",
    "market_data.get_trading_calendar",
    "market_data.get_trading_dates",
    "market_data.get_trading_period",
)


class FakeTraderClient:
    def __init__(self):
        self.calls = []
        self.fail = {}  # method name -> factory
        self.stop_fail = None

    def _record(self, name, args, default):
        self.calls.append((name, args))
        if name in self.fail:
            raise self.fail[name]()
        return default

    def start(self):
        return self._record("start", (), None)

    def connect(self):
        return self._record("connect", (), 0)

    def subscribe(self, account):
        return self._record("subscribe", (account,), 0)

    def query_stock_asset(self, account):
        return self._record("query_stock_asset", (account,), {"asset": 1})

    def query_stock_positions(self, account):
        return self._record("query_stock_positions", (account,), [])

    def query_stock_orders(self, account, cancelable_only):
        return self._record("query_stock_orders", (account, cancelable_only), [])

    def query_stock_trades(self, account):
        return self._record("query_stock_trades", (account,), [])

    def stop(self):
        self.calls.append(("stop", ()))
        if self.stop_fail is not None:
            raise self.stop_fail
        return None


class FakeMDClient:
    def __init__(self):
        self.calls = []
        self.fail = {}
        self.result = {}

    def _record(self, name, *args):
        self.calls.append((name, args))
        if name in self.fail:
            raise self.fail[name]()
        return self.result

    def get_full_tick(self, codes):
        return self._record("get_full_tick", codes)

    def get_market_data(self, *args):
        return self._record("get_market_data", args)

    def get_market_data_ex(self, *args):
        return self._record("get_market_data_ex", args)

    def get_instrument_detail(self, code, complete):
        return self._record("get_instrument_detail", code, complete)

    def get_divid_factors(self, code, start, end):
        return self._record("get_divid_factors", code, start, end)

    def get_trading_calendar(self, market, start, end):
        return self._record("get_trading_calendar", market, start, end)

    def get_trading_dates(self, market, start, end, count):
        return self._record("get_trading_dates", market, start, end, count)

    def get_trading_period(self, code):
        return self._record("get_trading_period", code)


class _PoisonousObject:
    """Object whose dunder protocols raise if ever observed."""

    def __repr__(self):
        raise RuntimeError("POISON_REPR_XYZ")

    def __str__(self):
        raise RuntimeError("POISON_STR_XYZ")

    def __len__(self):
        raise RuntimeError("POISON_LEN_XYZ")

    def __iter__(self):
        raise RuntimeError("POISON_ITER_XYZ")


def _pair(tc=None, mc=None):
    return (
        ReadOnlyTraderAdapter(tc or FakeTraderClient()),
        ReadOnlyMarketDataAdapter(mc or FakeMDClient()),
    )


def _stop_count(tc):
    return sum(1 for c in tc.calls if c[0] == "stop")


def _assert_safe_graph(exc, secret):
    """Assert cause/context are None and the secret appears nowhere in the graph."""
    if exc.__cause__ is not None:
        raise AssertionError("cause must be None")
    if exc.__context__ is not None:
        raise AssertionError("context must be None")
    stack = [exc]
    seen = set()
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if secret in str(node):
            raise AssertionError("secret leaked into exception graph")
        for attr in ("__cause__", "__context__"):
            child = getattr(node, attr, None)
            if child is not None:
                if secret in str(child):
                    raise AssertionError("secret leaked into exception child")
                stack.append(child)


class TestHappyPath(unittest.TestCase):
    def test_exact_15_step_order_and_summary(self):
        tc = FakeTraderClient()
        mc = FakeMDClient()
        trader, market = _pair(tc, mc)
        summary = run_gate1_readonly_probe(
            trader, market, account=object(), stock_code="600000.SH", exchange="SH"
        )
        self.assertIsInstance(summary, Gate1ReadOnlyProbeSummary)
        self.assertEqual(summary.completed_operations, _ALL_NAMES)
        self.assertTrue(summary.cleanup_completed)
        # exactly the 15 primary ops + 1 cleanup, in order
        self.assertEqual([c[0] for c in tc.calls], [
            "start", "connect", "subscribe", "query_stock_asset",
            "query_stock_positions", "query_stock_orders", "query_stock_trades", "stop",
        ])
        self.assertEqual([c[0] for c in mc.calls], [
            "get_full_tick", "get_market_data", "get_market_data_ex",
            "get_instrument_detail", "get_divid_factors", "get_trading_calendar",
            "get_trading_dates", "get_trading_period",
        ])

    def test_exact_arguments(self):
        tc = FakeTraderClient()
        mc = FakeMDClient()
        trader, market = _pair(tc, mc)
        account = object()
        run_gate1_readonly_probe(trader, market, account=account,
                                 stock_code="600000.SH", exchange="SH")
        self.assertEqual(tc.calls[2], ("subscribe", (account,)))
        self.assertEqual(tc.calls[3], ("query_stock_asset", (account,)))
        self.assertEqual(tc.calls[5], ("query_stock_orders", (account, False)))
        self.assertEqual(mc.calls[0], ("get_full_tick", (["600000.SH"],)))
        self.assertEqual(mc.calls[1][1][0], ([], ["600000.SH"], "1d", "", "", 1, "none", True))
        self.assertEqual(mc.calls[2][1][0], ([], ["600000.SH"], "5m", "", "", 1, "none", True))
        self.assertEqual(mc.calls[3], ("get_instrument_detail", ("600000.SH", False)))
        self.assertEqual(mc.calls[5], ("get_trading_calendar", ("SH", "", "")))
        self.assertEqual(mc.calls[6], ("get_trading_dates", ("SH", "", "", 1)))

    def test_summary_is_frozen(self):
        trader, market = _pair()
        summary = run_gate1_readonly_probe(
            trader, market, account=object(), stock_code="600000.SH", exchange="SH"
        )
        with self.assertRaises(Exception):
            summary.completed_operations = ()
        with self.assertRaises(Exception):
            summary.cleanup_completed = False

    def test_summary_contains_only_literal_names(self):
        trader, market = _pair()
        summary = run_gate1_readonly_probe(
            trader, market, account=object(), stock_code="600000.SH", exchange="SH"
        )
        for op in summary.completed_operations:
            self.assertIn(op, _ALL_NAMES)


class TestConfigBoundary(unittest.TestCase):
    def test_wrong_trader_type_rejected(self):
        trader, market = _pair()
        with self.assertRaises(Gate1ProbeConfigError):
            run_gate1_readonly_probe(object(), market, account=object(),
                                     stock_code="600000.SH", exchange="SH")

    def test_wrong_market_data_type_rejected(self):
        trader, market = _pair()
        with self.assertRaises(Gate1ProbeConfigError):
            run_gate1_readonly_probe(trader, object(), account=object(),
                                     stock_code="600000.SH", exchange="SH")

    def test_subclass_rejected(self):
        market = ReadOnlyMarketDataAdapter(FakeMDClient())
        class SubTrader(ReadOnlyTraderAdapter):
            pass
        sub = SubTrader(FakeTraderClient())
        with self.assertRaises(Gate1ProbeConfigError):
            run_gate1_readonly_probe(sub, market, account=object(),
                                     stock_code="600000.SH", exchange="SH")

    def test_none_account_rejected_zero_calls(self):
        tc = FakeTraderClient()
        trader, market = _pair(tc)
        with self.assertRaises(Gate1ProbeConfigError):
            run_gate1_readonly_probe(trader, market, account=None,
                                     stock_code="600000.SH", exchange="SH")
        self.assertEqual(tc.calls, [])

    def test_invalid_stock_code_rejected(self):
        trader, market = _pair()
        for bad in ("", None, 5):
            with self.assertRaises(Gate1ProbeConfigError):
                run_gate1_readonly_probe(trader, market, account=object(),
                                         stock_code=bad, exchange="SH")

    def test_invalid_exchange_rejected(self):
        trader, market = _pair()
        for bad in ("", None, 5):
            with self.assertRaises(Gate1ProbeConfigError):
                run_gate1_readonly_probe(trader, market, account=object(),
                                         stock_code="600000.SH", exchange=bad)

    def test_config_error_no_illegal_value(self):
        trader, market = _pair()
        with self.assertRaises(Gate1ProbeConfigError) as cm:
            run_gate1_readonly_probe(trader, market, account=object(),
                                     stock_code="SECRET_SYMBOL_XYZ", exchange="")
        self.assertNotIn("SECRET_SYMBOL_XYZ", str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)
        self.assertIsNone(cm.exception.__context__)


class TestPerStepFailure(unittest.TestCase):
    """Every one of the 15 primary operations, injected independently."""

    # method name (on fake) -> operation literal name
    TRADER_FAILS = {
        "start": "trader.start",
        "connect": "trader.connect",
        "subscribe": "trader.subscribe",
        "query_stock_asset": "trader.query_asset",
        "query_stock_positions": "trader.query_positions",
        "query_stock_orders": "trader.query_orders",
        "query_stock_trades": "trader.query_trades",
    }
    MD_FAILS = {
        "get_full_tick": "market_data.get_full_tick",
        "get_market_data": "market_data.get_market_data",
        "get_market_data_ex": "market_data.get_market_data_ex",
        "get_instrument_detail": "market_data.get_instrument_detail",
        "get_divid_factors": "market_data.get_divid_factors",
        "get_trading_calendar": "market_data.get_trading_calendar",
        "get_trading_dates": "market_data.get_trading_dates",
        "get_trading_period": "market_data.get_trading_period",
    }

    def test_each_trader_step_failure(self):
        for method, op_name in self.TRADER_FAILS.items():
            tc = FakeTraderClient()
            tc.fail[method] = lambda: RuntimeError("UNIQUE_SECRET_XYZ")
            trader, market = _pair(tc)
            out = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with self.assertRaises(Gate1ProbeExecutionError) as cm:
                    run_gate1_readonly_probe(
                        trader, market, account=object(),
                        stock_code="600000.SH", exchange="SH")
            self.assertEqual(str(cm.exception), f"{op_name} failed", msg=method)
            _assert_safe_graph(cm.exception, "UNIQUE_SECRET_XYZ")
            self.assertNotIn("UNIQUE_SECRET_XYZ", out.getvalue())
            self.assertNotIn("UNIQUE_SECRET_XYZ", err.getvalue())
            # The runner always calls trader.stop() at most once; the trader
            # adapter itself skips the underlying client stop when its own
            # start() never succeeded (only the "start" step).
            expected = 0 if method == "start" else 1
            self.assertEqual(_stop_count(tc), expected, msg=f"{method} cleanup")

    def test_each_md_step_failure(self):
        for method, op_name in self.MD_FAILS.items():
            tc = FakeTraderClient()
            mc = FakeMDClient()
            mc.fail[method] = lambda: RuntimeError("UNIQUE_SECRET_XYZ")
            trader, market = _pair(tc, mc)
            with self.assertRaises(Gate1ProbeExecutionError) as cm:
                run_gate1_readonly_probe(
                    trader, market, account=object(),
                    stock_code="600000.SH", exchange="SH")
            self.assertEqual(str(cm.exception), f"{op_name} failed", msg=method)
            _assert_safe_graph(cm.exception, "UNIQUE_SECRET_XYZ")
            self.assertEqual(_stop_count(tc), 1, msg=f"{method} cleanup")

    def test_execution_error_is_tgrid_subclass(self):
        tc = FakeTraderClient()
        tc.fail["start"] = lambda: RuntimeError()
        trader, market = _pair(tc)
        with self.assertRaises(Gate1ProbeError):
            run_gate1_readonly_probe(trader, market, account=object(),
                                     stock_code="600000.SH", exchange="SH")

    def test_completed_before_failure_auditable_via_fake_log(self):
        # Failure on the 4th trader op -> stop called once, trader started/connected.
        tc = FakeTraderClient()
        tc.fail["query_stock_asset"] = lambda: RuntimeError()
        trader, market = _pair(tc)
        with self.assertRaises(Gate1ProbeExecutionError):
            run_gate1_readonly_probe(trader, market, account=object(),
                                     stock_code="600000.SH", exchange="SH")
        # start+connect+subscribe completed; stop attempted exactly once.
        self.assertEqual([c[0] for c in tc.calls],
                         ["start", "connect", "subscribe", "query_stock_asset", "stop"])


class TestCleanupContract(unittest.TestCase):
    def test_primary_and_cleanup_failure_message(self):
        # A query_asset failure leaves the trader started, so the adapter's
        # cleanup reaches the underlying client stop and both fail.
        tc = FakeTraderClient()
        tc.fail["query_stock_asset"] = lambda: RuntimeError()
        tc.stop_fail = RuntimeError("CLEANUP_SECRET_XYZ")
        trader, market = _pair(tc)
        with self.assertRaises(Gate1ProbeExecutionError) as cm:
            run_gate1_readonly_probe(trader, market, account=object(),
                                     stock_code="600000.SH", exchange="SH")
        self.assertEqual(str(cm.exception), "trader.query_asset failed; cleanup failed")
        _assert_safe_graph(cm.exception, "CLEANUP_SECRET_XYZ")
        self.assertEqual(_stop_count(tc), 1)

    def test_all_success_cleanup_failure(self):
        tc = FakeTraderClient()
        tc.stop_fail = RuntimeError("CLEANUP_SECRET_XYZ")
        trader, market = _pair(tc)
        with self.assertRaises(Gate1ProbeExecutionError) as cm:
            run_gate1_readonly_probe(trader, market, account=object(),
                                     stock_code="600000.SH", exchange="SH")
        self.assertEqual(str(cm.exception), "cleanup failed")
        _assert_safe_graph(cm.exception, "CLEANUP_SECRET_XYZ")
        self.assertEqual(_stop_count(tc), 1)

    def test_cleanup_attempted_once_on_success(self):
        tc = FakeTraderClient()
        trader, market = _pair(tc)
        run_gate1_readonly_probe(trader, market, account=object(),
                                 stock_code="600000.SH", exchange="SH")
        self.assertEqual(_stop_count(tc), 1)


class TestCleanupBaseExceptionPriority(unittest.TestCase):
    """REV-G1T005-001: a cleanup BaseException never overrides or leaks over an
    ordinary primary failure; it folds into the fixed project error."""

    def _assert_safe_graph(self, exc, secrets):
        if exc.__cause__ is not None:
            raise AssertionError("cause must be None")
        if exc.__context__ is not None:
            raise AssertionError("context must be None")
        stack = [exc]
        seen = set()
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            for secret in secrets:
                if secret in str(node):
                    raise AssertionError(f"secret leaked: {secret}")
            for attr in ("__cause__", "__context__"):
                child = getattr(node, attr, None)
                if child is not None:
                    stack.append(child)

    def test_ordinary_primary_cleanup_keyboard_interrupt(self):
        tc = FakeTraderClient()
        tc.fail["query_stock_asset"] = lambda: RuntimeError("PRIMARY_SECRET_XYZ")
        tc.stop_fail = KeyboardInterrupt("CLEANUP_KI_SECRET")
        trader, market = _pair(tc)
        with self.assertRaises(Gate1ProbeExecutionError) as cm:
            run_gate1_readonly_probe(trader, market, account=object(),
                                     stock_code="600000.SH", exchange="SH")
        self.assertEqual(str(cm.exception), "trader.query_asset failed; cleanup failed")
        self._assert_safe_graph(cm.exception, ["PRIMARY_SECRET_XYZ", "CLEANUP_KI_SECRET"])
        self.assertEqual(_stop_count(tc), 1)

    def test_ordinary_primary_cleanup_system_exit(self):
        tc = FakeTraderClient()
        tc.fail["query_stock_asset"] = lambda: RuntimeError()
        tc.stop_fail = SystemExit(9)
        trader, market = _pair(tc)
        with self.assertRaises(Gate1ProbeExecutionError) as cm:
            run_gate1_readonly_probe(trader, market, account=object(),
                                     stock_code="600000.SH", exchange="SH")
        self.assertEqual(str(cm.exception), "trader.query_asset failed; cleanup failed")
        self.assertIsNone(cm.exception.__cause__)
        self.assertIsNone(cm.exception.__context__)
        self.assertEqual(_stop_count(tc), 1)

    def test_ordinary_primary_cleanup_generator_exit(self):
        tc = FakeTraderClient()
        tc.fail["query_stock_asset"] = lambda: RuntimeError()
        tc.stop_fail = GeneratorExit()
        trader, market = _pair(tc)
        with self.assertRaises(Gate1ProbeExecutionError) as cm:
            run_gate1_readonly_probe(trader, market, account=object(),
                                     stock_code="600000.SH", exchange="SH")
        self.assertEqual(str(cm.exception), "trader.query_asset failed; cleanup failed")
        self.assertEqual(_stop_count(tc), 1)

    def test_ordinary_primary_cleanup_ordinary_exception(self):
        tc = FakeTraderClient()
        tc.fail["query_stock_asset"] = lambda: RuntimeError("PRIMARY_SECRET_XYZ")
        tc.stop_fail = RuntimeError("CLEANUP_SECRET_XYZ")
        trader, market = _pair(tc)
        with self.assertRaises(Gate1ProbeExecutionError) as cm:
            run_gate1_readonly_probe(trader, market, account=object(),
                                     stock_code="600000.SH", exchange="SH")
        self.assertEqual(str(cm.exception), "trader.query_asset failed; cleanup failed")
        self._assert_safe_graph(cm.exception, ["PRIMARY_SECRET_XYZ", "CLEANUP_SECRET_XYZ"])
        self.assertEqual(_stop_count(tc), 1)

    def test_primary_base_exception_cleanup_base_exception_primary_wins(self):
        tc = FakeTraderClient()
        tc.fail["query_stock_asset"] = lambda: KeyboardInterrupt("PRIMARY_KI_SECRET")
        tc.stop_fail = SystemExit(7)
        trader, market = _pair(tc)
        with self.assertRaises(KeyboardInterrupt):
            run_gate1_readonly_probe(trader, market, account=object(),
                                     stock_code="600000.SH", exchange="SH")
        self.assertEqual(_stop_count(tc), 1)

    def test_all_success_cleanup_base_exception_propagates(self):
        tc = FakeTraderClient()
        tc.stop_fail = GeneratorExit()
        trader, market = _pair(tc)
        with self.assertRaises(GeneratorExit):
            run_gate1_readonly_probe(trader, market, account=object(),
                                     stock_code="600000.SH", exchange="SH")
        self.assertEqual(_stop_count(tc), 1)


class TestBaseException(unittest.TestCase):
    def test_keyboard_interrupt_propagates_after_cleanup(self):
        tc = FakeTraderClient()
        tc.fail["query_stock_asset"] = lambda: KeyboardInterrupt("INT_SECRET_XYZ")
        trader, market = _pair(tc)
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(KeyboardInterrupt):
                run_gate1_readonly_probe(trader, market, account=object(),
                                         stock_code="600000.SH", exchange="SH")
        self.assertNotIn("INT_SECRET_XYZ", out.getvalue())
        self.assertNotIn("INT_SECRET_XYZ", err.getvalue())
        self.assertEqual(_stop_count(tc), 1)

    def test_cleanup_ordinary_exception_does_not_override_primary_base_exception(self):
        # query_asset failure leaves the trader started, so cleanup reaches the
        # underlying stop; a cleanup ordinary exception must not override the
        # primary KeyboardInterrupt.
        tc = FakeTraderClient()
        tc.fail["query_stock_asset"] = lambda: KeyboardInterrupt()
        tc.stop_fail = RuntimeError("CLEANUP_SECRET_XYZ")
        trader, market = _pair(tc)
        with self.assertRaises(KeyboardInterrupt):
            run_gate1_readonly_probe(trader, market, account=object(),
                                     stock_code="600000.SH", exchange="SH")
        self.assertEqual(_stop_count(tc), 1)

    def test_system_exit_propagates(self):
        tc = FakeTraderClient()
        tc.fail["query_stock_positions"] = lambda: SystemExit(3)
        trader, market = _pair(tc)
        with self.assertRaises(SystemExit):
            run_gate1_readonly_probe(trader, market, account=object(),
                                     stock_code="600000.SH", exchange="SH")
        self.assertEqual(_stop_count(tc), 1)

    def test_cleanup_base_exception_without_primary_propagates(self):
        tc = FakeTraderClient()
        tc.stop_fail = GeneratorExit()
        trader, market = _pair(tc)
        with self.assertRaises(GeneratorExit):
            run_gate1_readonly_probe(trader, market, account=object(),
                                     stock_code="600000.SH", exchange="SH")


class TestPoisonousObjects(unittest.TestCase):
    def test_poisonous_account_never_observed(self):
        tc = FakeTraderClient()
        mc = FakeMDClient()
        trader, market = _pair(tc, mc)
        run_gate1_readonly_probe(trader, market, account=_PoisonousObject(),
                                 stock_code="600000.SH", exchange="SH")
        # runner never called repr/str/len/iter on the account

    def test_poisonous_return_objects_never_observed(self):
        mc = FakeMDClient()
        mc.result = _PoisonousObject()
        tc = FakeTraderClient()
        trader, market = _pair(tc, mc)
        run_gate1_readonly_probe(trader, market, account=object(),
                                 stock_code="600000.SH", exchange="SH")
        # runner never observed the returned objects (no repr/str/len/iter)


class TestProductionModuleSafety(unittest.TestCase):
    def test_probe_source_is_clean(self):
        src = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "tgrid"
            / "probes"
            / "gate1_readonly.py"
        )
        text = src.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(src))
        # "connect" is excluded: trader.connect() is a required probe operation.
        forbidden = ("subscribe_quote", "unsubscribe_quote", "download_", "order_", "cancel_")
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
                if name:
                    self.assertFalse(any(k in name for k in forbidden), msg=f"forbidden call {name}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
                args = node.args
                self.assertTrue(
                    len(args) < 2 or (isinstance(args[1], ast.Constant) and isinstance(args[1].value, str)),
                    msg="dynamic getattr name in production source",
                )
        # No private access: only the approved public adapter methods appear.
        for priv in ("_methods", "._client", "._state", "._op_lock", "._state_lock"):
            self.assertNotIn(priv, text)


if __name__ == "__main__":
    unittest.main()
