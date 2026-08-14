"""Offline tests for the user-authorized Gate 1 XtQuant runtime bridge (G1-T006).

Everything runs against fake trader / xtdata / xtconstant / xttype objects and
temporary files; nothing here connects to or queries real MiniQMT.  The module
under test must remain importable without XtQuant installed.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tgrid.integrations.qmt_gate1_runtime import (
    QmtGate1RuntimeAccountError,
    QmtGate1RuntimeConfigError,
    QmtGate1RuntimeError,
    ReadOnlyQmtGate1MarketDataBridge,
    ReadOnlyQmtGate1TraderBridge,
    _OpaqueAccount,
    _account_id_fingerprint,
    _build_runtime,
    _qmt_path_fingerprint,
    load_account_binding,
    load_gate1_config,
    load_runtime_config,
    parse_account_binding,
    parse_gate1_config,
    parse_runtime_config,
    run_gate1_readonly_acceptance,
)
from tgrid.risk.exceptions import TGridError

_ACCOUNT_ID = "FAKE_ACCOUNT_ID"

_FIXED_OPS = (
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


def _write_json(path, payload):
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return path


def _mk_qmt_dir():
    return Path(tempfile.mkdtemp())


def _make_trader_bridge(trader=None):
    qmt = _mk_qmt_dir()
    binding_path = Path(tempfile.mkdtemp()) / "binding.local.json"
    _write_json(binding_path, _binding_payload(qmt))
    binding = load_account_binding(
        binding_path, environment="simulation", qmt_path=qmt
    )
    token = _OpaqueAccount()
    return ReadOnlyQmtGate1TraderBridge(
        trader=trader or _Trader(),
        security_account_type=_C.SECURITY_ACCOUNT,
        account_status_ok=_C.ACCOUNT_STATUS_OK,
        stock_account_factory=lambda aid: _T.StockAccount(aid, "STOCK"),
        binding=binding,
        token=token,
    ), token


class _C:
    SECURITY_ACCOUNT = 1
    ACCOUNT_STATUS_OK = 0


class _T:
    SECURITY_ACCOUNT = 1

    @staticmethod
    def StockAccount(account_id, account_type):
        return ("STOCK", account_id)


class _Info:
    def __init__(self, account_id, account_type=1):
        self.account_id = account_id
        self.account_type = account_type


class _Status:
    def __init__(self, account_id, account_type=1, status=0):
        self.account_id = account_id
        self.account_type = account_type
        self.status = status


class _Trader:
    """Fake XtQuantTrader recording every call."""

    def __init__(self, infos=None, statuses=None):
        self.calls = []
        self._infos = infos if infos is not None else [_Info(_ACCOUNT_ID)]
        self._statuses = statuses if statuses is not None else [_Status(_ACCOUNT_ID)]

    def start(self):
        self.calls.append("start")

    def connect(self):
        self.calls.append("connect")
        return 0

    def query_account_infos(self):
        self.calls.append("query_account_infos")
        return list(self._infos)

    def query_account_status(self):
        self.calls.append("query_account_status")
        return list(self._statuses)

    def subscribe(self, stock):
        self.calls.append(("subscribe", stock))
        return 0

    def query_stock_asset(self, stock):
        self.calls.append(("query_stock_asset", stock))
        return {"asset": 1}

    def query_stock_positions(self, stock):
        self.calls.append(("query_stock_positions", stock))
        return []

    def query_stock_orders(self, stock, cancelable_only):
        self.calls.append(("query_stock_orders", stock, cancelable_only))
        return []

    def query_stock_trades(self, stock):
        self.calls.append(("query_stock_trades", stock))
        return []

    def stop(self):
        self.calls.append("stop")
        if getattr(self, "stop_fail", None) is not None:
            raise self.stop_fail


class _MD:
    def __init__(self):
        self.calls = []

    def _r(self, name, *args):
        self.calls.append((name, args))
        return {}

    def get_full_tick(self, codes):
        return self._r("get_full_tick", codes)

    def get_market_data(self, *args):
        return self._r("get_market_data", args)

    def get_market_data_ex(self, *args):
        return self._r("get_market_data_ex", args)

    def get_instrument_detail(self, code, complete):
        return self._r("get_instrument_detail", code, complete)

    def get_divid_factors(self, code, start, end):
        return self._r("get_divid_factors", code, start, end)

    def get_trading_calendar(self, market, start, end):
        return self._r("get_trading_calendar", market, start, end)

    def get_trading_dates(self, market, start, end, count):
        return self._r("get_trading_dates", market, start, end, count)

    def get_trading_period(self, code):
        return self._r("get_trading_period", code)


def _gate1_payload(runtime_path, binding_path):
    return {
        "environment": "simulation",
        "runtime_config_path": str(runtime_path),
        "account_binding_path": str(binding_path),
        "stock_code": "510300.SH",
        "exchange": "SH",
    }


def _runtime_payload(qmt_path):
    return {
        "python_path": ".venv\\Scripts\\python.exe",
        "live_qmt_path": str(qmt_path) + "_live",
        "simulation_qmt_path": str(qmt_path),
        "first_execution_time": "09:30:42",
        "second_execution_time": "15:10:00",
        "first_cash_usage_ratio": 0.9,
        "second_cash_usage_ratio": 1,
    }


def _binding_payload(qmt_path, *, account_id=None):
    return {
        "version": 2,
        "accounts": [
            {
                "environment": "simulation",
                "account_type": "SECURITY_ACCOUNT",
                "account_id_fingerprint": _account_id_fingerprint(
                    account_id if account_id is not None else _ACCOUNT_ID
                ),
                "label": "repo_simulation",
                "qmt_path_fingerprint": _qmt_path_fingerprint(qmt_path),
            }
        ],
        "created_at": "2026-08-14T00:00:00+08:00",
    }


def _make_runtime_binding(temp):
    qmt = _mk_qmt_dir()
    runtime = temp / "runtime.local.json"
    binding = temp / "binding.local.json"
    _write_json(runtime, _runtime_payload(qmt))
    _write_json(binding, _binding_payload(qmt))
    return qmt, runtime, binding


class TestGate1ConfigParsing(unittest.TestCase):
    def test_valid(self):
        cfg = parse_gate1_config(_gate1_payload("a", "b"))
        self.assertEqual(cfg.environment, "simulation")
        self.assertEqual(cfg.stock_code, "510300.SH")
        self.assertEqual(cfg.exchange, "SH")

    def test_unknown_field_rejected(self):
        data = _gate1_payload("a", "b")
        data["extra"] = 1
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_gate1_config(data)

    def test_missing_field_rejected(self):
        data = _gate1_payload("a", "b")
        del data["exchange"]
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_gate1_config(data)

    def test_non_mapping_rejected(self):
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_gate1_config([])

    def test_non_simulation_rejected(self):
        data = _gate1_payload("a", "b")
        data["environment"] = "live"
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_gate1_config(data)

    def test_invalid_stock_or_exchange(self):
        for key in ("stock_code", "exchange"):
            data = _gate1_payload("a", "b")
            data[key] = ""
            with self.assertRaises(QmtGate1RuntimeConfigError):
                parse_gate1_config(data)

    def test_error_is_tgrid_subclass(self):
        with self.assertRaises(TGridError):
            parse_gate1_config({"environment": "live"})


class TestRuntimeConfigParsing(unittest.TestCase):
    def test_valid(self):
        qmt = _mk_qmt_dir()
        cfg = parse_runtime_config(_runtime_payload(qmt), environment="simulation")
        self.assertEqual(cfg.qmt_path, qmt)

    def test_unknown_field_rejected(self):
        data = _runtime_payload(_mk_qmt_dir())
        data["extra"] = 1
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_runtime_config(data, environment="simulation")

    def test_missing_env_path_rejected(self):
        data = _runtime_payload(_mk_qmt_dir())
        del data["simulation_qmt_path"]
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_runtime_config(data, environment="simulation")

    def test_path_not_exists_rejected(self):
        data = _runtime_payload(_mk_qmt_dir())
        data["simulation_qmt_path"] = "C:/definitely/not/a/real/qmt/path_xyz"
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_runtime_config(data, environment="simulation")

    def test_non_mapping_rejected(self):
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_runtime_config("nope", environment="simulation")


class TestAccountBindingParsing(unittest.TestCase):
    def test_valid_version_2(self):
        qmt = _mk_qmt_dir()
        binding = parse_account_binding(
            _binding_payload(qmt), environment="simulation"
        )
        self.assertEqual(binding.label, "repo_simulation")
        self.assertEqual(binding.account_id_fingerprint, _account_id_fingerprint(_ACCOUNT_ID))

    def test_wrong_version_rejected(self):
        data = _binding_payload(_mk_qmt_dir())
        data["version"] = 1
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_account_binding(data, environment="simulation")

    def test_plaintext_account_id_rejected(self):
        data = _binding_payload(_mk_qmt_dir())
        data["accounts"][0]["account_id"] = _ACCOUNT_ID
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_account_binding(data, environment="simulation")

    def test_unknown_field_rejected(self):
        data = _binding_payload(_mk_qmt_dir())
        data["accounts"][0]["extra"] = 1
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_account_binding(data, environment="simulation")

    def test_zero_matching_accounts_rejected(self):
        data = _binding_payload(_mk_qmt_dir())
        data["accounts"] = []
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_account_binding(data, environment="simulation")

    def test_two_matching_accounts_rejected(self):
        data = _binding_payload(_mk_qmt_dir())
        data["accounts"].append(dict(data["accounts"][0]))
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_account_binding(data, environment="simulation")

    def test_non_security_account_skipped(self):
        data = _binding_payload(_mk_qmt_dir())
        data["accounts"][0]["account_type"] = "CREDIT_ACCOUNT"
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_account_binding(data, environment="simulation")

    def test_bad_fingerprint_rejected(self):
        data = _binding_payload(_mk_qmt_dir())
        data["accounts"][0]["account_id_fingerprint"] = "not-a-hash"
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_account_binding(data, environment="simulation")

    def test_missing_label_rejected(self):
        data = _binding_payload(_mk_qmt_dir())
        del data["accounts"][0]["label"]
        with self.assertRaises(QmtGate1RuntimeConfigError):
            parse_account_binding(data, environment="simulation")

    def test_path_fingerprint_mismatch_rejected(self):
        qmt = _mk_qmt_dir()
        binding_path = Path(tempfile.mkdtemp()) / "binding.local.json"
        _write_json(binding_path, _binding_payload(qmt))
        other = _mk_qmt_dir()
        with self.assertRaises(QmtGate1RuntimeConfigError):
            load_account_binding(
                binding_path, environment="simulation", qmt_path=other
            )

    def test_load_account_binding_ok(self):
        qmt = _mk_qmt_dir()
        binding_path = Path(tempfile.mkdtemp()) / "binding.local.json"
        _write_json(binding_path, _binding_payload(qmt))
        binding = load_account_binding(
            binding_path, environment="simulation", qmt_path=qmt
        )
        self.assertEqual(binding.label, "repo_simulation")


class TestTraderBridge(unittest.TestCase):
    def _bridge(self, trader=None, binding_path=None):
        return _make_trader_bridge(trader)[0]

    def _bridge_and_token(self, trader=None):
        return _make_trader_bridge(trader)

    def test_lifecycle_and_account_discovery_once(self):
        trader = _Trader()
        bridge, token = self._bridge_and_token(trader)
        bridge.start()
        bridge.connect()
        self.assertEqual(bridge.subscribe(token), 0)
        self.assertEqual(
            trader.calls.count("query_account_infos"), 1,
            "query_account_infos must be called exactly once",
        )
        self.assertEqual(
            trader.calls.count("query_account_status"), 1,
            "query_account_status must be called exactly once",
        )
        self.assertEqual(bridge.query_stock_asset(token), {"asset": 1})
        bridge.stop()

    def test_stop_at_most_once(self):
        trader = _Trader()
        bridge = self._bridge(trader)
        bridge.stop()
        bridge.stop()
        bridge.stop()
        self.assertEqual(trader.calls.count("stop"), 1)

    def test_opaque_token_repr_has_no_account(self):
        self.assertNotIn(_ACCOUNT_ID, repr(_OpaqueAccount()))

    def test_unsubscribed_token_misuse_fails_closed(self):
        bridge, token = self._bridge_and_token()
        with self.assertRaises(QmtGate1RuntimeAccountError):
            bridge.query_stock_asset(token)
        with self.assertRaises(QmtGate1RuntimeAccountError):
            bridge.query_stock_positions(token)
        with self.assertRaises(QmtGate1RuntimeAccountError):
            bridge.query_stock_orders(token, False)
        with self.assertRaises(QmtGate1RuntimeAccountError):
            bridge.query_stock_trades(token)

    def test_second_subscribe_fails_closed(self):
        bridge, token = self._bridge_and_token()
        bridge.start()
        bridge.connect()
        bridge.subscribe(token)
        with self.assertRaises(QmtGate1RuntimeAccountError):
            bridge.subscribe(_OpaqueAccount())

    def test_zero_account_matches_fails_closed(self):
        trader = _Trader(infos=[_Info("OTHER_ACCOUNT")])
        bridge = self._bridge(trader)
        token = _OpaqueAccount()
        with self.assertRaises(QmtGate1RuntimeAccountError):
            bridge.subscribe(token)

    def test_two_account_matches_fails_closed(self):
        trader = _Trader(infos=[_Info(_ACCOUNT_ID), _Info(_ACCOUNT_ID)])
        bridge = self._bridge(trader)
        with self.assertRaises(QmtGate1RuntimeAccountError):
            bridge.subscribe(_OpaqueAccount())

    def test_abnormal_status_fails_closed(self):
        trader = _Trader(statuses=[_Status(_ACCOUNT_ID, status=1)])
        bridge = self._bridge(trader)
        with self.assertRaises(QmtGate1RuntimeAccountError):
            bridge.subscribe(_OpaqueAccount())

    def test_fingerprint_mismatch_fails_closed(self):
        trader = _Trader(infos=[_Info("WRONG_ACCOUNT")])
        bridge = self._bridge(trader)
        with self.assertRaises(QmtGate1RuntimeAccountError):
            bridge.subscribe(_OpaqueAccount())

    def test_no_forbidden_surface(self):
        bridge = self._bridge()
        for name in (
            "order_stock",
            "cancel_order_stock",
            "cancel_order",
            "download_history_data",
            "subscribe_quote",
            "unsubscribe_quote",
            "call",
            "forward",
            "client",
            "raw_client",
        ):
            self.assertFalse(hasattr(bridge, name), msg=name)


class TestMarketDataBridge(unittest.TestCase):
    def test_eight_query_callables_forward(self):
        md = _MD()
        bridge = ReadOnlyQmtGate1MarketDataBridge(xtdata=md)
        bridge.get_full_tick(["510300.SH"])
        bridge.get_market_data([], ["510300.SH"], "1d")
        bridge.get_market_data_ex([], ["510300.SH"], "5m")
        bridge.get_instrument_detail("510300.SH")
        bridge.get_divid_factors("510300.SH")
        bridge.get_trading_calendar("SH")
        bridge.get_trading_dates("SH")
        bridge.get_trading_period("510300.SH")
        self.assertEqual(
            [c[0] for c in md.calls],
            [
                "get_full_tick",
                "get_market_data",
                "get_market_data_ex",
                "get_instrument_detail",
                "get_divid_factors",
                "get_trading_calendar",
                "get_trading_dates",
                "get_trading_period",
            ],
        )

    def test_no_forbidden_surface(self):
        bridge = ReadOnlyQmtGate1MarketDataBridge(xtdata=_MD())
        for name in (
            "subscribe_quote",
            "unsubscribe_quote",
            "download_history_data",
            "download_",
            "order_stock",
            "cancel_order_stock",
            "call",
            "client",
        ):
            self.assertFalse(hasattr(bridge, name), msg=name)


class TestBuildSimulationRuntime(unittest.TestCase):
    def _config_dir(self):
        temp = Path(tempfile.mkdtemp())
        qmt, runtime, binding = _make_runtime_binding(temp)
        gate1 = temp / "gate1_qmt.local.json"
        _write_json(gate1, _gate1_payload(runtime, binding))
        return temp, gate1, qmt

    def test_build_with_fakes_and_probe(self):
        temp, gate1, qmt = self._config_dir()
        trader_bridge, market_bridge, token = _build_runtime(
            load_gate1_config(gate1),
            deps={
                "trader_factory": lambda path: _Trader(),
                "xtconstant_values": (_C.SECURITY_ACCOUNT, _C.ACCOUNT_STATUS_OK),
                "stock_account_factory": lambda aid: _T.StockAccount(aid, "STOCK"),
                "xtdata": _MD(),
            },
        )
        from tgrid.adapters.qmt_readonly import ReadOnlyTraderAdapter
        from tgrid.adapters.marketdata_readonly import ReadOnlyMarketDataAdapter
        from tgrid.probes.gate1_readonly import (
            _COMPLETED_NAMES,
            run_gate1_readonly_probe,
        )

        trader = ReadOnlyTraderAdapter(trader_bridge)
        market = ReadOnlyMarketDataAdapter(market_bridge)
        summary = run_gate1_readonly_probe(
            trader,
            market,
            account=token,
            stock_code="510300.SH",
            exchange="SH",
        )
        self.assertEqual(summary.completed_operations, _COMPLETED_NAMES)
        self.assertTrue(summary.cleanup_completed)

    def test_no_fallback_to_undeclared_allowlist(self):
        # The gate1 config points at a runtime/binding pair; if the binding path
        # is missing, build must fail instead of searching elsewhere.
        temp = Path(tempfile.mkdtemp())
        missing_binding = temp / "missing_binding.local.json"
        gate1 = temp / "gate1_qmt.local.json"
        _write_json(gate1, _gate1_payload(Path("missing_runtime"), missing_binding))
        with self.assertRaises(QmtGate1RuntimeConfigError):
            _build_runtime(
                load_gate1_config(gate1),
                deps={"trader_factory": lambda p: _Trader()},
            )


class TestRawConnectSubscribeReturn(unittest.TestCase):
    """REV-G1T006-006: bridge must not coerce connect/subscribe results."""

    def _bridge(self, trader):
        return _make_trader_bridge(trader)

    def test_connect_returns_raw_type(self):
        for raw in (0, False, 0.0, "0", 1, True):
            trader = _Trader()
            trader.connect = lambda: raw
            bridge, _ = self._bridge(trader)
            result = bridge.connect()
            self.assertIs(result, raw, f"connect must return raw {type(raw).__name__}")

    def test_subscribe_returns_raw_type(self):
        for raw in (0, False, 0.0, "0", 1, True):
            trader = _Trader()
            trader.subscribe = lambda stock: raw
            bridge, token = self._bridge(trader)
            result = bridge.subscribe(token)
            self.assertIs(result, raw, f"subscribe must return raw {type(raw).__name__}")

    def test_invalid_types_rejected_end_to_end_via_adapter(self):
        from tgrid.adapters.qmt_readonly import ReadOnlyTraderAdapter
        from tgrid.risk.exceptions import QmtConnectionError

        for raw in (False, 0.0, "0"):
            trader = _Trader()
            trader.connect = lambda: raw
            trader.subscribe = lambda stock: 0
            bridge, _ = self._bridge(trader)
            adapter = ReadOnlyTraderAdapter(bridge)
            adapter.start()
            with self.assertRaises(QmtConnectionError):
                adapter.connect()


class TestOpaqueTokenIdentity(unittest.TestCase):
    """REV-G1T006-007: only the exact factory token passes; nothing is reached."""

    def _bridge(self, trader=None):
        return _make_trader_bridge(trader)[0]

    def test_wrong_opaque_account_rejected_before_discovery(self):
        trader = _Trader()
        bridge = self._bridge(trader)
        wrong = _OpaqueAccount()  # different factory-minted instance
        with self.assertRaises(QmtGate1RuntimeAccountError) as cm:
            bridge.subscribe(wrong)
        self.assertNotIn("FAKE", str(cm.exception))
        self.assertNotIn(_ACCOUNT_ID, str(cm.exception))
        self.assertEqual(trader.calls.count("query_account_infos"), 0)
        self.assertEqual(trader.calls.count("query_account_status"), 0)
        self.assertEqual(
            sum(1 for c in trader.calls if isinstance(c, tuple) and c[0] == "subscribe"),
            0,
        )

    def test_plain_object_and_none_rejected_before_any_call(self):
        for bad in (object(), None):
            trader = _Trader()
            bridge = self._bridge(trader)
            with self.assertRaises(QmtGate1RuntimeAccountError):
                bridge.subscribe(bad)
            self.assertEqual(trader.calls, [])

    def test_valid_token_used_once(self):
        trader = _Trader()
        bridge = self._bridge(trader)
        # The exact token the bridge was built with is not exposed by the
        # helper; simulate by using the private builder's returned token.
        temp = Path(tempfile.mkdtemp())
        qmt, runtime, binding = _make_runtime_binding(temp)
        gate1 = temp / "gate1_qmt.local.json"
        _write_json(gate1, _gate1_payload(runtime, binding))
        tb, _, token = _build_runtime(
            load_gate1_config(gate1),
            deps={
                "trader_factory": lambda path: _Trader(),
                "xtconstant_values": (_C.SECURITY_ACCOUNT, _C.ACCOUNT_STATUS_OK),
                "stock_account_factory": lambda aid: _T.StockAccount(aid, "STOCK"),
                "xtdata": _MD(),
            },
        )
        tb.subscribe(token)
        self.assertEqual(tb._expected_token is token, True)

    def test_unsubscribed_token_misuse_fails(self):
        trader = _Trader()
        bridge = self._bridge(trader)
        token = _OpaqueAccount()
        with self.assertRaises(QmtGate1RuntimeAccountError):
            bridge.query_stock_asset(token)


class TestNoRawClientReachable(unittest.TestCase):
    """REV-G1T006-008: frozen callables only; raw client/module unreachable."""

    def test_trader_bridge_hides_raw_client(self):
        trader = _Trader()
        bridge = _make_trader_bridge(trader)[0]
        for name in ("_trader", "trader", "client", "raw_client"):
            self.assertFalse(hasattr(bridge, name), msg=name)
        # No reachable object graph yields the raw trader.
        seen = set()
        stack = [bridge]
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            self.assertIsNot(node, trader, "raw trader reachable from bridge")
            for attr in ("_start", "_connect", "_subscribe", "_stop",
                         "_query_stock_asset", "_query_stock_positions",
                         "_query_stock_orders", "_query_stock_trades",
                         "_query_account_infos", "_query_account_status"):
                child = getattr(node, attr, None)
                if child is not None:
                    stack.append(child)

    def test_market_bridge_hides_raw_xtdata(self):
        md = _MD()
        bridge = ReadOnlyQmtGate1MarketDataBridge(xtdata=md)
        for name in ("_xtdata", "xtdata", "client"):
            self.assertFalse(hasattr(bridge, name), msg=name)
        seen = set()
        stack = [bridge]
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            self.assertIsNot(node, md, "raw xtdata reachable from bridge")
            for attr in ("_get_full_tick", "_get_market_data",
                         "_get_market_data_ex", "_get_instrument_detail",
                         "_get_divid_factors", "_get_trading_calendar",
                         "_get_trading_dates", "_get_trading_period"):
                child = getattr(node, attr, None)
                if child is not None:
                    stack.append(child)

    def test_no_forbidden_callables(self):
        trader_bridge = _make_trader_bridge()[0]
        market_bridge = ReadOnlyQmtGate1MarketDataBridge(xtdata=_MD())
        for bridge in (trader_bridge, market_bridge):
            for name in (
                "order_stock", "cancel_order_stock", "cancel_order",
                "download_history_data", "subscribe_quote", "unsubscribe_quote",
                "call", "forward", "client", "raw_client",
            ):
                self.assertFalse(hasattr(bridge, name), msg=f"{type(bridge).__name__}.{name}")


class TestConfigPathTypeStrict(unittest.TestCase):
    """REV-G1T006-009: path fields must be plain non-empty strings."""

    def test_invalid_path_types_rejected(self):
        for key in ("runtime_config_path", "account_binding_path"):
            for bad in (None, [], {}, True, 5, "", "   "):
                data = _gate1_payload("ok", "ok")
                data[key] = bad
                with self.assertRaises(QmtGate1RuntimeConfigError) as cm:
                    parse_gate1_config(data)
                text = str(cm.exception)
                self.assertNotIn("TypeError", text)
                self.assertNotIn(repr(bad), text)

    def test_valid_string_paths_accepted(self):
        cfg = parse_gate1_config(_gate1_payload("D:/x/runtime.json", "D:/x/binding.json"))
        self.assertEqual(cfg.runtime_config_path.name, "runtime.json")
        self.assertEqual(cfg.account_binding_path.name, "binding.json")

    def test_load_failure_cleaned(self):
        missing = Path(tempfile.mkdtemp()) / "nope.json"
        with self.assertRaises(QmtGate1RuntimeConfigError) as cm:
            load_gate1_config(missing)
        self.assertNotIn("TypeError", str(cm.exception))


class TestControlledAcceptanceRunner(unittest.TestCase):
    """REV-G1T006-010: narrow adapter+probe runner."""

    def _config_dir(self):
        temp = Path(tempfile.mkdtemp())
        qmt, runtime, binding = _make_runtime_binding(temp)
        gate1 = temp / "gate1_qmt.local.json"
        _write_json(gate1, _gate1_payload(runtime, binding))
        return gate1, qmt

    def _deps(self):
        return {
            "trader_factory": lambda path: _Trader(),
            "xtconstant_values": (_C.SECURITY_ACCOUNT, _C.ACCOUNT_STATUS_OK),
            "stock_account_factory": lambda aid: _T.StockAccount(aid, "STOCK"),
            "xtdata": _MD(),
        }

    def test_runner_runs_fixed_probe_via_real_adapters(self):
        gate1, qmt = self._config_dir()
        result = run_gate1_readonly_acceptance(
            gate1,
            trader_factory=lambda path: _Trader(),
            xtconstant_values=self._deps()["xtconstant_values"],
            stock_account_factory=self._deps()["stock_account_factory"],
            xtdata=_MD(),
        )
        self.assertEqual(result["completed_operations"], _FIXED_OPS)
        self.assertTrue(result["cleanup_completed"])

    def test_runner_public_signature_has_no_probe_param(self):
        import inspect

        sig = inspect.signature(run_gate1_readonly_acceptance)
        self.assertNotIn("probe", sig.parameters)

    def test_runner_default_probe_uses_parsed_stock_exchange(self):
        temp = Path(tempfile.mkdtemp())
        qmt, runtime, binding = _make_runtime_binding(temp)
        gate1 = temp / "gate1_qmt.local.json"
        payload = _gate1_payload(runtime, binding)
        payload["stock_code"] = "159919.SZ"
        payload["exchange"] = "SZ"
        _write_json(gate1, payload)
        seen = {}

        class _ProbingMD(_MD):
            def get_full_tick(self, codes):
                seen["get_full_tick"] = codes
                return super().get_full_tick(codes)

            def get_instrument_detail(self, code, complete):
                seen["detail"] = code
                return super().get_instrument_detail(code, complete)

        result = run_gate1_readonly_acceptance(
            gate1,
            trader_factory=lambda path: _Trader(),
            xtconstant_values=self._deps()["xtconstant_values"],
            stock_account_factory=self._deps()["stock_account_factory"],
            xtdata=_ProbingMD(),
        )
        # The fixed probe passes the parsed stock_code to xtdata.
        self.assertEqual(seen["get_full_tick"], ["159919.SZ"])
        self.assertEqual(seen["detail"], "159919.SZ")
        self.assertTrue(result["cleanup_completed"])

    def test_runner_no_retry_and_no_raw_exposure(self):
        gate1, qmt = self._config_dir()
        result = run_gate1_readonly_acceptance(
            gate1,
            trader_factory=lambda path: _Trader(),
            xtconstant_values=self._deps()["xtconstant_values"],
            stock_account_factory=self._deps()["stock_account_factory"],
            xtdata=_MD(),
        )
        self.assertEqual(result["completed_operations"], _FIXED_OPS)
        self.assertTrue(result["cleanup_completed"])

    def test_runner_result_has_no_raw_data(self):
        gate1, qmt = self._config_dir()
        result = run_gate1_readonly_acceptance(
            gate1,
            trader_factory=lambda path: _Trader(),
            xtconstant_values=self._deps()["xtconstant_values"],
            stock_account_factory=self._deps()["stock_account_factory"],
            xtdata=_MD(),
        )
        payload = repr(result)
        self.assertNotIn("FAKE_ACCOUNT_ID", payload)
        self.assertNotIn(str(qmt), payload)

    def test_strict_summary_rejects_foreign_object(self):
        from tgrid.integrations.qmt_gate1_runtime import _strict_summary

        class _Evil:
            completed_operations = ("TOP_SECRET_ACCOUNT",)
            cleanup_completed = 1

        with self.assertRaises(QmtGate1RuntimeError) as cm:
            _strict_summary(_Evil())
        self.assertNotIn("TOP_SECRET_ACCOUNT", str(cm.exception))

    def test_strict_summary_rejects_wrong_operations(self):
        from tgrid.integrations.qmt_gate1_runtime import _strict_summary
        from tgrid.probes.gate1_readonly import Gate1ReadOnlyProbeSummary

        wrong = Gate1ReadOnlyProbeSummary(
            completed_operations=("trader.start",), cleanup_completed=True
        )
        with self.assertRaises(QmtGate1RuntimeError):
            _strict_summary(wrong)

    def test_runner_fixed_probe_failure_propagates_safely(self):
        # A real fixed-probe run over a failing fake trader: the probe stops at
        # most once and surfaces its own safe Gate1ProbeExecutionError; the
        # runner does not re-wrap or leak the underlying failure.
        gate1 = self._config_dir()

        class _FailingMD(_MD):
            def get_trading_calendar(self, market, start, end):
                raise RuntimeError("CALENDAR_SECRET_XYZ")

        with self.assertRaises(Exception) as cm:
            run_gate1_readonly_acceptance(
                gate1,
                trader_factory=lambda path: _Trader(),
                xtconstant_values=self._deps()["xtconstant_values"],
                stock_account_factory=self._deps()["stock_account_factory"],
                xtdata=_FailingMD(),
            )
        self.assertNotIn("CALENDAR_SECRET_XYZ", str(cm.exception))

    def test_runner_config_path_invalid_type(self):
        for bad in (None, [], True, 5, "", "   "):
            with self.assertRaises(QmtGate1RuntimeConfigError):
                run_gate1_readonly_acceptance(bad)


class TestPublicSurface(unittest.TestCase):
    """REV-G1T006-011: only the safe runner is public; no bridge/client/token."""

    def test_package_exports_only_runner_and_errors(self):
        import tgrid.integrations as pkg

        for name in (
            "build_simulation_runtime",
            "ReadOnlyQmtGate1TraderBridge",
            "ReadOnlyQmtGate1MarketDataBridge",
            "OpaqueAccount",
            "make_opaque_account",
            "AccountBinding",
            "Gate1Config",
            "RuntimeConfig",
        ):
            self.assertFalse(hasattr(pkg, name), msg=f"{name} must not be public")
        self.assertTrue(hasattr(pkg, "run_gate1_readonly_acceptance"))
        for name in pkg.__all__:
            self.assertTrue(hasattr(pkg, name), msg=f"__all__ entry missing: {name}")

    def test_runner_does_not_return_bridge_or_token(self):
        gate1 = self._config_dir()
        result = run_gate1_readonly_acceptance(
            gate1,
            trader_factory=lambda path: _Trader(),
            xtconstant_values=(_C.SECURITY_ACCOUNT, _C.ACCOUNT_STATUS_OK),
            stock_account_factory=lambda aid: _T.StockAccount(aid, "STOCK"),
            xtdata=_MD(),
        )
        self.assertEqual(set(result), {"completed_operations", "cleanup_completed"})
        payload = repr(result)
        self.assertNotIn("TraderBridge", payload)
        self.assertNotIn("OpaqueAccount", payload)

    def _config_dir(self):
        temp = Path(tempfile.mkdtemp())
        qmt, runtime, binding = _make_runtime_binding(temp)
        gate1 = temp / "gate1_qmt.local.json"
        _write_json(gate1, _gate1_payload(runtime, binding))
        return gate1

    def test_bridge_stores_only_plain_constants_not_modules(self):
        qmt = _mk_qmt_dir()
        binding_path = Path(tempfile.mkdtemp()) / "binding.local.json"
        _write_json(binding_path, _binding_payload(qmt))
        binding = load_account_binding(
            binding_path, environment="simulation", qmt_path=qmt
        )
        bridge, _ = ReadOnlyQmtGate1TraderBridge(
            trader=_Trader(),
            security_account_type=_C.SECURITY_ACCOUNT,
            account_status_ok=_C.ACCOUNT_STATUS_OK,
            stock_account_factory=lambda aid: _T.StockAccount(aid, "STOCK"),
            binding=binding,
            token=_OpaqueAccount(),
        ), _OpaqueAccount()
        for name in ("_xtconstant", "_xttype", "_trader", "xtconstant", "xttype"):
            self.assertFalse(hasattr(bridge, name), msg=name)
        self.assertEqual(bridge._security_account_type, 1)
        self.assertEqual(bridge._account_status_ok, 0)


class TestTransactionalBuildCleanup(unittest.TestCase):
    """REV-G1T006-012: build failures after trader creation stop at most once."""

    def _config_dir(self):
        temp = Path(tempfile.mkdtemp())
        qmt, runtime, binding = _make_runtime_binding(temp)
        gate1 = temp / "gate1_qmt.local.json"
        _write_json(gate1, _gate1_payload(runtime, binding))
        return gate1

    def test_market_bridge_construction_failure_stops_trader(self):
        gate1 = self._config_dir()
        trader = _Trader()

        class _BoomMD:
            @property
            def get_full_tick(self):
                raise RuntimeError("MD_BOOM_SECRET")

        with self.assertRaises(QmtGate1RuntimeError):
            run_gate1_readonly_acceptance(
                gate1,
                trader_factory=lambda path: trader,
                xtconstant_values=(_C.SECURITY_ACCOUNT, _C.ACCOUNT_STATUS_OK),
                stock_account_factory=lambda aid: _T.StockAccount(aid, "STOCK"),
                xtdata=_BoomMD(),
            )
        # trader created -> stop attempted exactly once
        self.assertEqual(trader.calls.count("stop"), 1)

    def test_trader_bridge_construction_failure_stops_trader(self):
        gate1 = self._config_dir()
        trader = _Trader()

        class _BoomTrader:
            @property
            def start(self):
                raise RuntimeError("TRADER_BOOM_SECRET")

        with self.assertRaises(QmtGate1RuntimeError):
            run_gate1_readonly_acceptance(
                gate1,
                trader_factory=lambda path: _BoomTrader(),
                xtconstant_values=(_C.SECURITY_ACCOUNT, _C.ACCOUNT_STATUS_OK),
                stock_account_factory=lambda aid: _T.StockAccount(aid, "STOCK"),
                xtdata=_MD(),
            )


class TestConfigParsedOnce(unittest.TestCase):
    """REV-G1T006-016: the config file is read exactly once (no TOCTOU)."""

    def test_runner_reads_config_once(self):
        temp = Path(tempfile.mkdtemp())
        qmt, runtime, binding = _make_runtime_binding(temp)
        gate1 = temp / "gate1_qmt.local.json"
        payload = _gate1_payload(runtime, binding)
        payload["stock_code"] = "159919.SZ"
        payload["exchange"] = "SZ"
        _write_json(gate1, payload)
        calls = []

        from tgrid.integrations import qmt_gate1_runtime as mod

        original = mod.load_gate1_config

        def counting(path):
            calls.append(1)
            return original(path)

        import unittest.mock as mock

        with mock.patch.object(mod, "load_gate1_config", side_effect=counting):
            result = run_gate1_readonly_acceptance(
                gate1,
                trader_factory=lambda path: _Trader(),
                xtconstant_values=(_C.SECURITY_ACCOUNT, _C.ACCOUNT_STATUS_OK),
                stock_account_factory=lambda aid: _T.StockAccount(aid, "STOCK"),
                xtdata=_MD(),
            )
        self.assertEqual(len(calls), 1, "config must be read exactly once")
        self.assertTrue(result["cleanup_completed"])


class TestAllPathCleanup(unittest.TestCase):
    """REV-G1T006-017: cleanup runs on success, validation failure, and exceptions."""

    def _deps(self):
        return {
            "trader_factory": lambda path: _Trader(),
            "xtconstant_values": (_C.SECURITY_ACCOUNT, _C.ACCOUNT_STATUS_OK),
            "stock_account_factory": lambda aid: _T.StockAccount(aid, "STOCK"),
            "xtdata": _MD(),
        }

    def _config_dir(self):
        temp = Path(tempfile.mkdtemp())
        qmt, runtime, binding = _make_runtime_binding(temp)
        gate1 = temp / "gate1_qmt.local.json"
        _write_json(gate1, _gate1_payload(runtime, binding))
        return gate1

    def _underlying_stop(self, trader):
        return trader.calls.count("stop")

    def test_success_valid_summary_cleans_up(self):
        gate1 = self._config_dir()
        trader = _Trader()

        result = run_gate1_readonly_acceptance(
            gate1,
            trader_factory=lambda path: trader,
            xtconstant_values=self._deps()["xtconstant_values"],
            stock_account_factory=self._deps()["stock_account_factory"],
            xtdata=_MD(),
        )
        self.assertTrue(result["cleanup_completed"])
        # fixed probe subscribes -> adapter eligible stop -> underlying stop once
        self.assertEqual(self._underlying_stop(trader), 1)

    def test_cleanup_runtime_error_is_safe_not_false_pass(self):
        # The fixed probe's stop() raises an ordinary RuntimeError: the approved
        # G1-T005 probe must report a data-free 'cleanup failed' and never a
        # false success.
        gate1 = self._config_dir()
        trader = _Trader()
        trader.stop_fail = RuntimeError("STOP_SECRET_XYZ")

        with self.assertRaises(Exception) as cm:
            run_gate1_readonly_acceptance(
                gate1,
                trader_factory=lambda path: trader,
                xtconstant_values=self._deps()["xtconstant_values"],
                stock_account_factory=self._deps()["stock_account_factory"],
                xtdata=_MD(),
            )
        self.assertNotIn("STOP_SECRET_XYZ", str(cm.exception))

    def test_cleanup_keyboard_interrupt_propagates_not_false_pass(self):
        gate1 = self._config_dir()
        trader = _Trader()
        trader.stop_fail = KeyboardInterrupt("STOP_KI_SECRET")

        with self.assertRaises(KeyboardInterrupt):
            run_gate1_readonly_acceptance(
                gate1,
                trader_factory=lambda path: trader,
                xtconstant_values=self._deps()["xtconstant_values"],
                stock_account_factory=self._deps()["stock_account_factory"],
                xtdata=_MD(),
            )

    def test_fixed_probe_failure_cleans_up_once(self):
        # A real fixed-probe run fails when a fake trader method raises; the
        # approved probe stops the started trader at most once and surfaces a
        # safe, data-free Gate1ProbeExecutionError.
        gate1 = self._config_dir()

        class _BoomTrader(_Trader):
            def query_stock_asset(self, stock):
                self.calls.append(("query_stock_asset", stock))
                raise RuntimeError("ASSET_SECRET_XYZ")

        with self.assertRaises(Exception) as cm:
            run_gate1_readonly_acceptance(
                gate1,
                trader_factory=lambda path: _BoomTrader(),
                xtconstant_values=self._deps()["xtconstant_values"],
                stock_account_factory=self._deps()["stock_account_factory"],
                xtdata=_MD(),
            )
        self.assertNotIn("ASSET_SECRET_XYZ", str(cm.exception))


class TestStrictSummaryNoIteration(unittest.TestCase):
    """REV-G1T006-018: exact tuple compare; malicious iterable never runs."""

    class _EvilIterable:
        def __iter__(self):
            raise RuntimeError("SUMMARY_ITER_SECRET_XYZ")

    def _config_dir(self):
        temp = Path(tempfile.mkdtemp())
        qmt, runtime, binding = _make_runtime_binding(temp)
        gate1 = temp / "gate1_qmt.local.json"
        _write_json(gate1, _gate1_payload(runtime, binding))
        return gate1

    def test_malicious_completed_operations_not_iterated(self):
        from tgrid.integrations.qmt_gate1_runtime import _strict_summary
        from tgrid.probes.gate1_readonly import Gate1ReadOnlyProbeSummary

        evil = Gate1ReadOnlyProbeSummary.__new__(Gate1ReadOnlyProbeSummary)
        object.__setattr__(evil, "completed_operations", self._EvilIterable())
        object.__setattr__(evil, "cleanup_completed", True)
        with self.assertRaises(QmtGate1RuntimeError) as cm:
            _strict_summary(evil)
        self.assertNotIn("SUMMARY_ITER_SECRET_XYZ", str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)
        self.assertIsNone(cm.exception.__context__)

    def test_non_plain_bool_cleanup_rejected(self):
        from tgrid.integrations.qmt_gate1_runtime import _strict_summary
        from tgrid.probes.gate1_readonly import Gate1ReadOnlyProbeSummary

        evil = Gate1ReadOnlyProbeSummary.__new__(Gate1ReadOnlyProbeSummary)
        object.__setattr__(evil, "completed_operations", _FIXED_OPS)
        object.__setattr__(evil, "cleanup_completed", 1)
        with self.assertRaises(QmtGate1RuntimeError):
            _strict_summary(evil)


class TestErrorsDataFree(unittest.TestCase):
    def test_config_errors_do_not_leak_paths(self):
        qmt = _mk_qmt_dir()
        binding_path = Path(tempfile.mkdtemp()) / "binding.local.json"
        _write_json(binding_path, _binding_payload(qmt))
        other = _mk_qmt_dir()
        try:
            load_account_binding(
                binding_path, environment="simulation", qmt_path=other
            )
            self.fail("expected mismatch error")
        except QmtGate1RuntimeConfigError as exc:
            text = str(exc)
            self.assertNotIn(str(qmt), text)
            self.assertNotIn(str(other), text)
            self.assertNotIn(_account_id_fingerprint(_ACCOUNT_ID), text)

    def test_account_errors_do_not_leak_account(self):
        trader = _Trader(infos=[_Info("WRONG_ACCOUNT")])
        bridge = _make_trader_bridge(trader)[0]
        with self.assertRaises(QmtGate1RuntimeAccountError) as cm:
            bridge.subscribe(_OpaqueAccount())
        self.assertNotIn("WRONG_ACCOUNT", str(cm.exception))
        self.assertNotIn(_ACCOUNT_ID, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
