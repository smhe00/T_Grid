"""Production live-session factory (NODEB-RR-001 / RR4-001).

The dependency-injected :func:`~tgrid.integrations.live_bootstrap.build_live_stack`
is a test/internal assembly helper.  :func:`build_live_session` is the ONE
production live-session entry point.  It consumes **validated TGrid
configuration** (a :class:`~tgrid.models.RootConfig` whose
``global_config.live_trading`` is the trusted double-enable first step) plus
the separate QMT account/path binding, and follows the established
``reverse_repo`` lifecycle oracle:

::

    construct trader from QMT path
    -> start
    -> connect (exact plain-int success)
    -> strict account info/status discovery
    -> exactly one bound normal securities account
    -> subscribe (exact plain-int success)
    -> assemble bridge/adapter (default OFF via global.live_trading)
    -> mandatory recovery + runtime confirmation (LiveStack.activate)

Wrong environment/path/account, nonzero or wrong-type connect/subscribe
result, or zero/multiple account matches fail before any order-capable stack
becomes ready.  The database is opened from the validated TGrid config
(never an arbitrary caller connection / ``:memory:``), so the durable
exposure journal goes through the normal migration lifecycle (RR4-004).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tgrid.events import EventQueue
from tgrid.integrations.exposure_store import SqliteExposureStore
from tgrid.integrations.live_bootstrap import LiveStack, build_live_stack
from tgrid.integrations.live_broker_adapter import (
    LiveBrokerPolicy,
)
from tgrid.integrations.qmt_gate1_runtime import (
    AccountBinding,
    Gate1Config,
    QmtGate1RuntimeError,
    load_account_binding,
    load_gate1_config,
    load_runtime_config,
)
from tgrid.models import RootConfig
from tgrid.persistence import initialize as initialize_database


class LiveSessionError(QmtGate1RuntimeError):
    """Base class for production live-session construction failures."""


class LiveSessionAccountError(LiveSessionError):
    """Account/environment/path verification failed; order capability denied."""


# Gate 5.5 session-binding config: the same strict fields as Gate 1 but the
# environment is explicitly restricted to exactly {"simulation", "live"} —
# Gate 1's simulation-only parser is left untouched for Gate 1 (RR5-001).
_SESSION_FIELDS = frozenset(
    {
        "environment",
        "runtime_config_path",
        "account_binding_path",
        "stock_code",
        "exchange",
    }
)
_ALLOWED_SESSION_ENVIRONMENTS = frozenset({"simulation", "live"})


@dataclass(frozen=True)
class LiveSessionBindingConfig:
    environment: str
    runtime_config_path: Path
    account_binding_path: Path
    stock_code: str
    exchange: str


def parse_live_session_binding(data: object) -> LiveSessionBindingConfig:
    """Strict Gate-5.5 session-binding parser (RR5-001).

    Accepts exactly ``simulation`` and ``live``; reuses the same strict JSON /
    path validation style as Gate 1 but never the simulation-only parser.
    """
    from tgrid.integrations.qmt_gate1_runtime import (
        QmtGate1RuntimeConfigError,
        _read_json_object,
        _require_nonempty_str,
        _require_path,
        _strict_fields,
    )

    if not isinstance(data, dict):
        raise QmtGate1RuntimeConfigError(
            "live session binding must be a JSON object"
        )
    _strict_fields(data, allowed=_SESSION_FIELDS, label="live session binding")
    environment = _require_nonempty_str(data["environment"], label="environment")
    if environment not in _ALLOWED_SESSION_ENVIRONMENTS:
        raise LiveSessionError(
            "environment must be exactly 'simulation' or 'live'"
        )
    return LiveSessionBindingConfig(
        environment=environment,
        runtime_config_path=_require_path(
            data["runtime_config_path"], label="runtime_config_path"
        ),
        account_binding_path=_require_path(
            data["account_binding_path"], label="account_binding_path"
        ),
        stock_code=_require_nonempty_str(data["stock_code"], label="stock_code"),
        exchange=_require_nonempty_str(data["exchange"], label="exchange"),
    )


def load_live_session_binding(path: object) -> LiveSessionBindingConfig:
    from tgrid.integrations.qmt_gate1_runtime import _read_json_object

    return parse_live_session_binding(_read_json_object(path, label="live session binding"))


def _require_exact_zero(value: object, *, label: str) -> None:
    """The reference lifecycle treats a nonzero/wrong-type result as failure."""
    if type(value) is not int or value != 0:
        raise LiveSessionError(
            f"{label} did not return the exact plain-int success value"
        )


def _fingerprint(account_id: object) -> str:
    import hashlib

    normalized = str(account_id).strip()
    if not normalized:
        raise LiveSessionAccountError("account ID is missing")
    payload = f"miniqmt-account-v1:{normalized}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _select_bound_account(
    trader: object,
    *,
    binding: AccountBinding,
    security_account_type: int,
    account_status_ok: int,
    stock_account_factory,
    attempts: int = 3,
    delay_seconds: float = 0.15,
) -> object:
    """Strictly select exactly one normal account matching the binding.

    Mirrors ``reverse_repo.select_bound_account`` semantics: account infos and
    statuses are strict-queried, the account must be a normal securities
    account in OK status whose fingerprint matches the binding; zero or
    multiple matches fail closed.
    """
    if type(attempts) is not int or attempts < 1:
        raise LiveSessionAccountError("attempts must be a positive int")
    errors: list = []
    for attempt in range(1, attempts + 1):
        try:
            infos = list(trader.query_account_infos())
            statuses = list(trader.query_account_status())
        except Exception as exc:  # noqa: BLE001 - strict query boundary
            errors.append(f"{type(exc).__name__}: {exc}")
        else:
            normal_ids = {
                str(getattr(s, "account_id", "")).strip()
                for s in statuses
                if int(getattr(s, "account_type", -1)) == int(security_account_type)
                and int(getattr(s, "status", -1)) == int(account_status_ok)
            }
            matches = [
                info
                for info in infos
                if int(getattr(info, "account_type", -1)) == int(security_account_type)
                and str(getattr(info, "account_id", "")).strip() in normal_ids
                and _fingerprint(getattr(info, "account_id", ""))
                == binding.account_id_fingerprint
            ]
            if len(matches) == 1:
                return stock_account_factory(
                    str(getattr(matches[0], "account_id", "")).strip()
                )
            errors.append(f"expected exactly one normal account, found {len(matches)}")
        if attempt < attempts:
            import time

            time.sleep(delay_seconds)
    raise LiveSessionAccountError(
        "bound account selection remained ambiguous after repeated strict queries"
    )


@dataclass(frozen=True)
class LiveSessionPaths:
    """Separate QMT account/path binding inputs for the production session."""

    gate1_config_path: Path
    environment: str


def build_live_session(
    *,
    root_config: RootConfig,
    gate1_config_path: object,
    environment: str,
    event_queue: EventQueue,
    policy: LiveBrokerPolicy,
    runtime_confirmation_token: str,
    trade_date: str,
    strategy_name: str = "TGRID",
    order_timeout_seconds: int | None = None,
    trader_factory=None,
    xtconstant_values=None,
    stock_account_factory=None,
) -> LiveStack:
    """Assemble the production live stack from VALIDATED TGrid configuration.

    ``root_config`` is the already-validated TGrid configuration; its
    ``global_config.live_trading`` is the trusted first step of the
    double-enable (default OFF — missing/false keeps execution disabled,
    RR4-001).  ``gate1_config_path`` + ``environment`` provide the separate
    QMT account/path binding.  The database is opened from
    ``root_config.global_config.database`` through the normal migration
    lifecycle (RR4-004); no arbitrary caller connection is accepted.

    Dependency-injected ``trader_factory`` / ``xtconstant_values`` /
    ``stock_account_factory`` are test-only (fake XtQuant); production uses
    the real XtQuant imports (lazy, as in Gate 1).

    SM9-001: the reverse_repo execution authority (state machine + journal +
    cross-process mutex) is ALWAYS wired on this trusted path — journal and
    lock paths are derived from the validated database location and there is
    no silent opt-out that returns an order-capable stack without them.
    """
    if not isinstance(root_config, RootConfig):
        raise LiveSessionError("root_config must be a validated RootConfig")
    global_cfg = root_config.global_config
    if type(global_cfg.live_trading) is not bool:
        raise LiveSessionError("global.live_trading must be a plain bool")

    # Separate QMT binding via the Gate-5.5 session parser (RR5-001); Gate 1's
    # simulation-only parser is never used here.
    binding_cfg = load_live_session_binding(gate1_config_path)
    if binding_cfg.environment != environment:
        raise LiveSessionError(
            f"binding environment {binding_cfg.environment!r} does not match "
            f"requested {environment!r}"
        )
    runtime = load_runtime_config(
        binding_cfg.runtime_config_path, environment=binding_cfg.environment
    )
    binding = load_account_binding(
        binding_cfg.account_binding_path,
        environment=binding_cfg.environment,
        qmt_path=runtime.qmt_path,
    )

    from tgrid.integrations.qmt_gate1_runtime import (
        _real_stock_account_factory,
        _real_trader_factory,
        _real_xtconstant_values,
    )

    # Reference lifecycle: construct -> start -> connect(exact int) ->
    # discover -> unique account -> subscribe(exact int).
    trader = (trader_factory or _real_trader_factory)(str(runtime.qmt_path))
    try:
        trader.start()
        connect_result = trader.connect()
        _require_exact_zero(connect_result, label="trader.connect")
        security_type, status_ok = xtconstant_values or _real_xtconstant_values()
        stock_factory = stock_account_factory or _real_stock_account_factory()
        stock_account = _select_bound_account(
            trader,
            binding=binding,
            security_account_type=security_type,
            account_status_ok=status_ok,
            stock_account_factory=stock_factory,
        )
        subscribe_result = trader.subscribe(stock_account)
        _require_exact_zero(subscribe_result, label="trader.subscribe")
    except QmtGate1RuntimeError:
        _attempt_stop(trader)
        raise
    except Exception as exc:  # noqa: BLE001 - construction boundary
        _attempt_stop(trader)
        raise LiveSessionError("live session construction failed") from exc

    # Database from validated config through the migration lifecycle (RR4-004):
    # never an arbitrary caller connection / :memory:.
    db_path = str(global_cfg.database)
    if not db_path or db_path == ":memory:":
        _attempt_stop(trader)
        raise LiveSessionError(
            "live session requires a persistent database path from validated config"
        )
    conn = initialize_database(db_path)
    exposure_store = SqliteExposureStore(conn)

    timeout = (
        order_timeout_seconds
        if order_timeout_seconds is not None
        else global_cfg.order_timeout_seconds
    )
    from tgrid.execution.store import ExecutionStore

    # SM9-001: the state-machine extension is part of the TRUSTED production
    # factory — never a silent opt-out.  The execution journal + cross-process
    # mutex are derived from the validated database location and enabled
    # unconditionally, so a production simulation/live stack always carries
    # the execution authority.
    db_dir = Path(db_path).resolve().parent
    journal_path = str(db_dir / f"tgrid-execution-{trade_date}.json")
    lock_path = str(db_dir / "tgrid-execution.lock")

    stack = build_live_stack(
        trader=trader, account=stock_account, store=ExecutionStore(conn),
        policy=policy, exposure_store=exposure_store, event_queue=event_queue,
        trade_date=trade_date,
        runtime_confirmation_token=runtime_confirmation_token,
        strategy_name=strategy_name, order_timeout_seconds=timeout,
        config_live_enabled=global_cfg.live_trading,
        security_account_type=int(security_type),
        account_status_ok=int(status_ok),
        journal_path=journal_path,
        execution_lock_path=lock_path,
    )
    # No silent opt-out (SM9-001): an order-capable production stack must
    # carry the journal + mutex before it can ever be activated.
    if stack.journal is None or stack.execution_lock is None:
        _attempt_stop(trader)
        raise LiveSessionError(
            "production stack missing state-machine authority "
            "(journal/mutex)"
        )
    # attach the opened connection so the caller can close it after teardown
    stack._db_conn = conn  # test/internal convenience only
    return stack


def _attempt_stop(trader: object) -> None:
    try:
        trader.stop()
    except BaseException:
        pass
