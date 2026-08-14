"""User-authorized Gate 1 read-only XtQuant runtime bridge (G1-T006).

This is the only place in production ``src/tgrid`` that may import XtQuant, and
it does so lazily inside the real-run factory only.  The trader bridge exposes
exactly the eight callables the approved ``ReadOnlyTraderAdapter`` requires and
discovers the bound account inside ``subscribe`` via SHA-256 fingerprints
(path + account), selecting the single normal securities account in memory.

No account ID, QMT path, fingerprint, or any business value is ever printed,
returned, or persisted.  All errors are data-free.  No order / cancel / download
/ quote-subscription surface exists here, and ``live_trading_allowed`` is never
touched (it remains ``false``).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from tgrid.risk.exceptions import TGridError

_SIMULATION = "simulation"
_SECURITY_ACCOUNT = "SECURITY_ACCOUNT"

_GATE1_FIELDS = frozenset(
    {
        "environment",
        "runtime_config_path",
        "account_binding_path",
        "stock_code",
        "exchange",
    }
)
_RUNTIME_FIELDS = frozenset(
    {
        "python_path",
        "live_qmt_path",
        "simulation_qmt_path",
        "first_execution_time",
        "second_execution_time",
        "first_cash_usage_ratio",
        "second_cash_usage_ratio",
    }
)
_BINDING_FIELDS = frozenset({"version", "accounts", "created_at"})
_BINDING_ENTRY_FIELDS = frozenset(
    {
        "environment",
        "account_type",
        "account_id_fingerprint",
        "label",
        "qmt_path_fingerprint",
    }
)

_ACCOUNT_FINGERPRINT_PREFIX = "miniqmt-account-v1:"

# The fixed operation literals the approved probe reports.  The runner verifies
# the summary against exactly these (REV-G1T006-013).
_FIXED_OPERATIONS = (
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


# -- exceptions ---------------------------------------------------------------


class QmtGate1RuntimeError(TGridError):
    """Base class for Gate 1 runtime bridge failures."""


class QmtGate1RuntimeConfigError(QmtGate1RuntimeError):
    """A configuration or binding file is invalid (data-free message)."""


class QmtGate1RuntimeConnectionError(QmtGate1RuntimeError):
    """The runtime bridge could not start or connect."""


class QmtGate1RuntimeAccountError(QmtGate1RuntimeError):
    """Account discovery or opaque-token misuse failed (data-free message)."""


# -- config dataclasses -------------------------------------------------------


@dataclass(frozen=True)
class Gate1Config:
    environment: str
    runtime_config_path: Path
    account_binding_path: Path
    stock_code: str
    exchange: str


@dataclass(frozen=True)
class RuntimeConfig:
    qmt_path: Path


@dataclass(frozen=True)
class AccountBinding:
    label: str
    account_id_fingerprint: str
    qmt_path_fingerprint: str


# -- strict JSON helpers ------------------------------------------------------


def _read_json_object(path: Path, *, label: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QmtGate1RuntimeConfigError(
            f"{label} is unreadable"
        ) from None
    if not isinstance(payload, dict):
        raise QmtGate1RuntimeConfigError(f"{label} must be a JSON object")
    return payload


def _strict_fields(data: dict, *, allowed: frozenset, label: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise QmtGate1RuntimeConfigError(f"{label} contains unknown field(s)")


def _require_present(data: dict, *, required: frozenset, label: str) -> None:
    missing = required - set(data)
    if missing:
        raise QmtGate1RuntimeConfigError(
            f"{label} is missing required field(s)"
        )


def _require_nonempty_str(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QmtGate1RuntimeConfigError(f"{label} must be a non-empty string")
    return value.strip()


def _require_path(value: object, *, label: str) -> Path:
    # Strict plain-string type before Path(...) so null/list/bool/int never
    # leak a raw TypeError (REV-G1T006-009).
    if not isinstance(value, str) or not value.strip():
        raise QmtGate1RuntimeConfigError(
            f"{label} must be a non-empty string path"
        )
    return Path(value)


def _is_sha256(value: object) -> bool:
    text = str(value or "").strip().lower()
    return (
        len(text) == 64
        and all(char in "0123456789abcdef" for char in text)
    )


def _account_id_fingerprint(account_id: object) -> str:
    normalized = str(account_id).strip()
    if not normalized:
        raise QmtGate1RuntimeAccountError("account ID is missing")
    payload = f"{_ACCOUNT_FINGERPRINT_PREFIX}{normalized}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _qmt_path_fingerprint(qmt_path: Path) -> str:
    normalized = os.path.normcase(str(Path(qmt_path).resolve()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# -- strict parsers -----------------------------------------------------------


def parse_gate1_config(data: dict) -> Gate1Config:
    if not isinstance(data, dict):
        raise QmtGate1RuntimeConfigError("gate1 config must be a JSON object")
    _strict_fields(data, allowed=_GATE1_FIELDS, label="gate1 config")
    _require_present(data, required=_GATE1_FIELDS, label="gate1 config")
    environment = _require_nonempty_str(
        data["environment"], label="environment"
    )
    if environment != _SIMULATION:
        raise QmtGate1RuntimeConfigError(
            "only the simulation environment is authorized"
        )
    stock_code = _require_nonempty_str(data["stock_code"], label="stock_code")
    exchange = _require_nonempty_str(data["exchange"], label="exchange")
    return Gate1Config(
        environment=environment,
        runtime_config_path=_require_path(
            data["runtime_config_path"], label="runtime_config_path"
        ),
        account_binding_path=_require_path(
            data["account_binding_path"], label="account_binding_path"
        ),
        stock_code=stock_code,
        exchange=exchange,
    )


def parse_runtime_config(data: dict, *, environment: str) -> RuntimeConfig:
    if not isinstance(data, dict):
        raise QmtGate1RuntimeConfigError(
            "runtime config must be a JSON object"
        )
    _strict_fields(data, allowed=_RUNTIME_FIELDS, label="runtime config")
    path_field = f"{environment}_qmt_path"
    if path_field not in data:
        raise QmtGate1RuntimeConfigError(
            "runtime config is missing the environment QMT path"
        )
    path = Path(_require_nonempty_str(data[path_field], label=path_field))
    if not path.exists():
        raise QmtGate1RuntimeConfigError(
            "runtime QMT path does not exist"
        )
    return RuntimeConfig(qmt_path=path)


def parse_account_binding(data: dict, *, environment: str) -> AccountBinding:
    if not isinstance(data, dict):
        raise QmtGate1RuntimeConfigError(
            "account binding must be a JSON object"
        )
    _strict_fields(data, allowed=_BINDING_FIELDS, label="account binding")
    _require_present(
        data, required=frozenset({"version", "accounts"}), label="account binding"
    )
    if data["version"] != 2:
        raise QmtGate1RuntimeConfigError(
            "account binding version must be 2"
        )
    accounts = data["accounts"]
    if not isinstance(accounts, list):
        raise QmtGate1RuntimeConfigError(
            "account binding accounts must be a list"
        )
    matches: list[AccountBinding] = []
    for entry in accounts:
        if not isinstance(entry, dict):
            raise QmtGate1RuntimeConfigError(
                "account binding entry must be an object"
            )
        _strict_fields(
            entry,
            allowed=_BINDING_ENTRY_FIELDS,
            label="account binding entry",
        )
        if "account_id" in entry:
            raise QmtGate1RuntimeConfigError(
                "plaintext account IDs are forbidden in account bindings"
            )
        if entry.get("environment") != environment:
            continue
        if entry.get("account_type") != _SECURITY_ACCOUNT:
            continue
        fingerprint = entry.get("account_id_fingerprint")
        if not _is_sha256(fingerprint):
            raise QmtGate1RuntimeConfigError(
                "invalid account fingerprint in binding"
            )
        path_fingerprint = entry.get("qmt_path_fingerprint")
        if not _is_sha256(path_fingerprint):
            raise QmtGate1RuntimeConfigError(
                "invalid QMT path fingerprint in binding"
            )
        label = _require_nonempty_str(entry.get("label"), label="label")
        matches.append(
            AccountBinding(
                label=label,
                account_id_fingerprint=str(fingerprint).strip().lower(),
                qmt_path_fingerprint=str(path_fingerprint).strip().lower(),
            )
        )
    if len(matches) != 1:
        raise QmtGate1RuntimeConfigError(
            "expected exactly one bound securities account"
        )
    return matches[0]


# -- loaders ------------------------------------------------------------------


def load_gate1_config(path: object) -> Gate1Config:
    return parse_gate1_config(_read_json_object(_resolve_path(path), label="gate1 config"))


def load_runtime_config(path: object, *, environment: str) -> RuntimeConfig:
    data = _read_json_object(_resolve_path(path), label="runtime config")
    return parse_runtime_config(data, environment=environment)


def load_account_binding(
    path: object,
    *,
    environment: str,
    qmt_path: Path,
) -> AccountBinding:
    data = _read_json_object(_resolve_path(path), label="account binding")
    binding = parse_account_binding(data, environment=environment)
    actual_path = _qmt_path_fingerprint(qmt_path)
    if actual_path != binding.qmt_path_fingerprint:
        raise QmtGate1RuntimeConfigError(
            "QMT path does not match the bound environment"
        )
    return binding


def _resolve_path(path: object) -> Path:
    if isinstance(path, Path):
        return path
    if isinstance(path, str) and path.strip():
        return Path(path)
    raise QmtGate1RuntimeConfigError(
        "config path must be a non-empty string or Path"
    )


# -- opaque account token -----------------------------------------------------


class _OpaqueAccount:
    """Opaque token carrying no account data; only its identity matters."""

    __slots__ = ("_nonce",)

    def __init__(self) -> None:
        self._nonce = os.urandom(16)

    def __repr__(self) -> str:
        return "OpaqueAccount()"


# -- account selection --------------------------------------------------------


def _select_normal_account(
    infos: object,
    statuses: object,
    *,
    binding: AccountBinding,
    security_account_type: int,
    account_status_ok: int,
    stock_account_factory: Callable[[str], object],
) -> object:
    normal_ids = {
        str(getattr(status, "account_id", "")).strip()
        for status in statuses
        if int(getattr(status, "account_type", -1)) == int(security_account_type)
        and int(getattr(status, "status", -1)) == int(account_status_ok)
    }
    matches = [
        info
        for info in infos
        if int(getattr(info, "account_type", -1)) == int(security_account_type)
        and str(getattr(info, "account_id", "")).strip() in normal_ids
        and _account_id_fingerprint(getattr(info, "account_id", ""))
        == binding.account_id_fingerprint
    ]
    if len(matches) != 1:
        raise QmtGate1RuntimeAccountError(
            "expected exactly one normal account matching the binding"
        )
    account_id = str(getattr(matches[0], "account_id", "")).strip()
    return stock_account_factory(account_id)


# -- trader bridge ------------------------------------------------------------


class ReadOnlyQmtGate1TraderBridge:
    """Trader surface exposing exactly the eight Adapter callables.

    The underlying XtQuantTrader is private.  ``subscribe`` discovers the bound
    account once (one ``query_account_infos`` and one ``query_account_status``),
    maps the opaque token to an in-memory StockAccount, and every query resolves
    the token back.  ``stop`` runs at most once.
    """

    def __init__(
        self,
        *,
        trader: object,
        security_account_type: int,
        account_status_ok: int,
        stock_account_factory: Callable[[str], object],
        binding: AccountBinding,
        token: _OpaqueAccount,
    ) -> None:
        # REV-G1T006-011: only plain constants + a StockAccount factory are
        # stored (never the xtconstant/xttype modules).  Only the exact approved
        # callables are frozen; the raw client is not stored as an attribute.
        self._expected_token = token
        self._start = trader.start
        self._connect = trader.connect
        self._query_account_infos = trader.query_account_infos
        self._query_account_status = trader.query_account_status
        self._subscribe = trader.subscribe
        self._query_stock_asset = trader.query_stock_asset
        self._query_stock_positions = trader.query_stock_positions
        self._query_stock_orders = trader.query_stock_orders
        self._query_stock_trades = trader.query_stock_trades
        self._stop = trader.stop
        self._security_account_type = int(security_account_type)
        self._account_status_ok = int(account_status_ok)
        self._stock_account_factory = stock_account_factory
        self._binding = binding
        self._token: object = None
        self._stock: object = None
        self._stop_called = False

    def start(self) -> None:
        self._start()

    def connect(self) -> object:
        # REV-G1T006-006: return the raw result unchanged; the approved Adapter
        # enforces the exact plain-int contract.
        return self._connect()

    def subscribe(self, account: object) -> object:
        if self._token is not None:
            raise QmtGate1RuntimeAccountError("account already subscribed")
        if account is not self._expected_token:
            # REV-G1T006-007: only the exact factory-minted token instance
            # passes identity; a foreign OpaqueAccount, plain object, or None
            # fails closed before any discovery or underlying call.
            raise QmtGate1RuntimeAccountError(
                "opaque account token is not valid"
            )
        self._token = account
        infos = list(self._query_account_infos())
        statuses = list(self._query_account_status())
        stock = _select_normal_account(
            infos,
            statuses,
            binding=self._binding,
            security_account_type=self._security_account_type,
            account_status_ok=self._account_status_ok,
            stock_account_factory=self._stock_account_factory,
        )
        self._stock = stock
        # REV-G1T006-006: raw result, no int coercion.
        return self._subscribe(stock)

    def query_stock_asset(self, account: object) -> object:
        return self._query_stock_asset(self._resolve(account))

    def query_stock_positions(self, account: object) -> object:
        return self._query_stock_positions(self._resolve(account))

    def query_stock_orders(self, account: object, cancelable_only: bool) -> object:
        return self._query_stock_orders(self._resolve(account), cancelable_only)

    def query_stock_trades(self, account: object) -> object:
        return self._query_stock_trades(self._resolve(account))

    def stop(self) -> None:
        if self._stop_called:
            return
        self._stop_called = True
        self._stop()

    def _resolve(self, account: object) -> object:
        # REV-G1T006-007: exact identity check against the single subscribed token.
        if self._token is None or account is not self._token:
            raise QmtGate1RuntimeAccountError(
                "opaque account token was not subscribed"
            )
        return self._stock


# -- market data bridge -------------------------------------------------------


class ReadOnlyQmtGate1MarketDataBridge:
    """Market-data surface exposing exactly the eight Adapter query callables.

    Wraps ``xtdata`` and deliberately has no subscribe/unsubscribe/download or
    any trading surface.
    """

    def __init__(self, *, xtdata: object) -> None:
        # REV-G1T006-008: only the eight approved query callables are frozen;
        # the raw xtdata module is never stored, so it is unreachable.
        self._get_full_tick = xtdata.get_full_tick
        self._get_market_data = xtdata.get_market_data
        self._get_market_data_ex = xtdata.get_market_data_ex
        self._get_instrument_detail = xtdata.get_instrument_detail
        self._get_divid_factors = xtdata.get_divid_factors
        self._get_trading_calendar = xtdata.get_trading_calendar
        self._get_trading_dates = xtdata.get_trading_dates
        self._get_trading_period = xtdata.get_trading_period

    def get_full_tick(self, stock_codes: object) -> object:
        return self._get_full_tick(stock_codes)

    def get_market_data(
        self,
        field_list: object,
        stock_list: object,
        period: object,
        start_time: object = "",
        end_time: object = "",
        count: object = -1,
        dividend_type: object = "none",
        fill_data: object = True,
    ) -> object:
        return self._get_market_data(
            field_list,
            stock_list,
            period,
            start_time,
            end_time,
            count,
            dividend_type,
            fill_data,
        )

    def get_market_data_ex(
        self,
        field_list: object,
        stock_list: object,
        period: object,
        start_time: object = "",
        end_time: object = "",
        count: object = -1,
        dividend_type: object = "none",
        fill_data: object = True,
    ) -> object:
        return self._get_market_data_ex(
            field_list,
            stock_list,
            period,
            start_time,
            end_time,
            count,
            dividend_type,
            fill_data,
        )

    def get_instrument_detail(
        self, stock_code: object, complete: object = False
    ) -> object:
        return self._get_instrument_detail(stock_code, complete)

    def get_divid_factors(
        self,
        stock_code: object,
        start_time: object = "",
        end_time: object = "",
    ) -> object:
        return self._get_divid_factors(stock_code, start_time, end_time)

    def get_trading_calendar(
        self,
        market: object,
        start_time: object = "",
        end_time: object = "",
    ) -> object:
        return self._get_trading_calendar(market, start_time, end_time)

    def get_trading_dates(
        self,
        market: object,
        start_time: object = "",
        end_time: object = "",
        count: object = -1,
    ) -> object:
        return self._get_trading_dates(market, start_time, end_time, count)

    def get_trading_period(self, stock_code: object) -> object:
        return self._get_trading_period(stock_code)


# -- real-run factory (lazy XtQuant) ------------------------------------------


def _real_trader_factory(qmt_path: str) -> object:
    # Lazily import XtQuant via importlib so the offline import graph and the
    # literal-import scan (no ``import xtquant`` in src/tgrid) stay clean.  This
    # remains the single authorized runtime import point (G1-T006).
    import importlib

    xttrader = importlib.import_module("xtquant.xttrader")
    trader_type = xttrader.XtQuantTrader
    return trader_type(qmt_path, random.randint(100_000_000, 999_999_999))


def _real_xtconstant_values() -> tuple:
    import importlib

    xtconstant = importlib.import_module("xtquant.xtconstant")
    return (
        int(getattr(xtconstant, "SECURITY_ACCOUNT", -1)),
        int(getattr(xtconstant, "ACCOUNT_STATUS_OK", -1)),
    )


def _real_stock_account_factory() -> Callable[[str], object]:
    import importlib

    xttype = importlib.import_module("xtquant.xttype")

    def make(account_id: str) -> object:
        return xttype.StockAccount(account_id, "STOCK")

    return make


def _real_xtdata() -> object:
    import importlib

    return importlib.import_module("xtquant.xtdata")


def _resolve_config_path(config_path: object) -> Path:
    # REV-G1T006-014: plain str or Path only; anything else is a safe config error.
    if isinstance(config_path, Path):
        return config_path
    if isinstance(config_path, str) and config_path.strip():
        return Path(config_path)
    raise QmtGate1RuntimeConfigError(
        "config path must be a non-empty string or Path"
    )


def _build_runtime(config: Gate1Config, *, deps: dict):
    """Build bridges + token (private; never exported).

    Transactional: once the underlying trader is created, any later ordinary or
    BaseException triggers at most one cleanup attempt (REV-G1T006-012).
    ``config`` is the single parsed snapshot from the runner (REV-G1T006-016),
    so the runtime and probe never re-read the file.
    """
    runtime = load_runtime_config(
        config.runtime_config_path, environment=config.environment
    )
    binding = load_account_binding(
        config.account_binding_path,
        environment=config.environment,
        qmt_path=runtime.qmt_path,
    )
    factory = deps.get("trader_factory") or _real_trader_factory
    trader = factory(str(runtime.qmt_path))
    _BASE = (KeyboardInterrupt, SystemExit, GeneratorExit)
    build_failed = False
    try:
        security_type, status_ok = deps.get("xtconstant_values") or _real_xtconstant_values()
        stock_factory = deps.get("stock_account_factory") or _real_stock_account_factory()
        token = _OpaqueAccount()
        trader_bridge = ReadOnlyQmtGate1TraderBridge(
            trader=trader,
            security_account_type=security_type,
            account_status_ok=status_ok,
            stock_account_factory=stock_factory,
            binding=binding,
            token=token,
        )
        market_bridge = ReadOnlyQmtGate1MarketDataBridge(
            xtdata=deps.get("xtdata") or _real_xtdata()
        )
    except _BASE:
        # REV-G1T006-012: BaseException during build still stops at most once
        # and propagates unchanged.
        _attempt_stop(trader)
        raise
    except BaseException:
        # Ordinary construction failure: stop at most once, then a data-free
        # project error OUTSIDE the active except block.
        _attempt_stop(trader)
        build_failed = True
    if build_failed:
        raise QmtGate1RuntimeError("gate1 runtime build failed") from None
    return trader_bridge, market_bridge, token


def _attempt_stop(trader: object) -> None:
    try:
        trader.stop()
    except BaseException:
        pass


# -- controlled adapter+probe runner (sole public entry) ----------------------


def run_gate1_readonly_acceptance(
    config_path: object,
    *,
    trader_factory: Optional[Callable[[str], object]] = None,
    xtconstant_values: Optional[tuple] = None,
    stock_account_factory: Optional[Callable[[str], object]] = None,
    xtdata: Optional[object] = None,
) -> dict:
    """Run the approved Gate 1 read-only probe exactly once, data-free.

    This is the ONLY production entry for a real acceptance run.  It parses the
    config once, builds the authorized simulation runtime, and calls the ALREADY
    APPROVED fixed ``run_gate1_readonly_probe`` exactly once.  The fixed probe
    owns all at-most-once cleanup, ordinary-error sanitization and cleanup
    BaseException propagation (G1-T005 contract); this runner never re-implements
    a lifecycle or cleanup branch (REV-G1T006-019).  It returns only the fixed 15
    operation literals plus ``cleanup_completed=True``.
    """
    # REV-G1T006-016: the config is parsed exactly once and the same frozen
    # snapshot feeds both the builder and the probe.
    config = load_gate1_config(_resolve_config_path(config_path))
    deps = {
        "trader_factory": trader_factory,
        "xtconstant_values": xtconstant_values,
        "stock_account_factory": stock_account_factory,
        "xtdata": xtdata,
    }
    trader_bridge, market_bridge, token = _build_runtime(config, deps=deps)
    from tgrid.adapters.marketdata_readonly import ReadOnlyMarketDataAdapter
    from tgrid.adapters.qmt_readonly import ReadOnlyTraderAdapter

    trader = ReadOnlyTraderAdapter(trader_bridge)
    market_data = ReadOnlyMarketDataAdapter(market_bridge)

    # The fixed probe performs every op then calls trader.stop() at most once;
    # success/failure/BaseException priority all live in the approved probe.
    result = _default_probe(trader, market_data, token, config)
    summary = _strict_summary(result)
    return {
        "completed_operations": _FIXED_OPERATIONS,
        "cleanup_completed": summary.cleanup_completed is True,
    }


def _strict_summary(result: object):
    from tgrid.probes.gate1_readonly import Gate1ReadOnlyProbeSummary

    if type(result) is not Gate1ReadOnlyProbeSummary:
        raise QmtGate1RuntimeError("unexpected probe result type")
    # REV-G1T006-018: require an exact tuple BEFORE any iteration/compare so a
    # malicious completed_operations can never execute its __iter__ here.
    ops = getattr(result, "completed_operations", None)
    if type(ops) is not tuple:
        raise QmtGate1RuntimeError("probe summary operations mismatch")
    if ops != _FIXED_OPERATIONS:
        raise QmtGate1RuntimeError("probe summary operations mismatch")
    # REV-G1T006-018: exact identity; no bool()/iter/repr/str/len on unknowns.
    if getattr(result, "cleanup_completed", None) is not True:
        raise QmtGate1RuntimeError("probe cleanup was not completed")
    return result


def _default_probe(
    trader: object, market_data: object, token: object, config: Gate1Config
) -> object:
    from tgrid.probes.gate1_readonly import run_gate1_readonly_probe

    # REV-G1T006-014: the probe uses the strictly parsed config values.
    return run_gate1_readonly_probe(
        trader,
        market_data,
        account=token,
        stock_code=config.stock_code,
        exchange=config.exchange,
    )
