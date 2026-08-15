"""Production live-session factory (NODEB-RR-001).

The dependency-injected :func:`~tgrid.integrations.live_bootstrap.build_live_stack`
is a test/internal assembly helper.  This module adds the ONE production
live-session factory that reuses the hardened Gate-1 / ``reverse_repo``
account-binding semantics instead of accepting an arbitrary raw account object:

* instantiate/connect the trader from the selected QMT userdata path;
* distinguish live vs simulation path;
* validate the configured QMT-path fingerprint;
* discover account infos/statuses through strict queries;
* select exactly one normal securities account whose account fingerprint
  matches the binding;
* subscribe that exact account;
* persist only non-sensitive account label/environment verification, never
  plaintext account ids.

Production order capability is unreachable if account/path/environment
verification fails or is ambiguous.
"""

from __future__ import annotations

from pathlib import Path

from tgrid.events import EventQueue
from tgrid.execution.store import ExecutionStore
from tgrid.integrations.live_bootstrap import LiveStack, build_live_stack
from tgrid.integrations.live_broker_adapter import (
    LiveBrokerAdapter,
    LiveBrokerPolicy,
)
from tgrid.integrations.qmt_gate1_runtime import (
    AccountBinding,
    Gate1Config,
    QmtGate1RuntimeAccountError,
    QmtGate1RuntimeError,
    load_account_binding,
    load_gate1_config,
    load_runtime_config,
)
from tgrid.integrations.exposure_store import SqliteExposureStore


class LiveSessionError(QmtGate1RuntimeError):
    """Base class for production live-session construction failures."""


class LiveSessionAccountError(LiveSessionError):
    """Account/environment/path verification failed; order capability denied."""


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
    for _ in range(1, attempts + 1):
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
        if _ < attempts:
            import time

            time.sleep(delay_seconds)
    raise LiveSessionAccountError(
        "bound account selection remained ambiguous after repeated strict queries"
    )


def _fingerprint(account_id: object) -> str:
    import hashlib

    normalized = str(account_id).strip()
    if not normalized:
        raise LiveSessionAccountError("account ID is missing")
    payload = f"miniqmt-account-v1:{normalized}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_live_session(
    *,
    config_path: object,
    event_queue: EventQueue,
    store: ExecutionStore,
    policy: LiveBrokerPolicy,
    db_conn,
    runtime_confirmation_token: str,
    trade_date: str,
    strategy_name: str = "TGRID",
    order_timeout_seconds: int = 120,
    trader_factory=None,
    xtconstant_values=None,
    stock_account_factory=None,
    environment: str = "simulation",
) -> LiveStack:
    """Assemble the production live stack with verified account binding.

    ``trader_factory`` / ``xtconstant_values`` / ``stock_account_factory`` are
    dependency injection points for tests (fake XtQuant only).  In production
    they default to the real XtQuant imports (lazy, as in Gate 1).

    Returns a :class:`LiveStack` whose adapter holds an opaque-bound account;
    order capability is unreachable until :meth:`LiveStack.activate` completes
    startup recovery + runtime confirmation (RR-003).
    """
    from tgrid.integrations.qmt_gate1_runtime import (
        _real_stock_account_factory,
        _real_trader_factory,
        _real_xtconstant_values,
    )

    config: Gate1Config = load_gate1_config(config_path)
    if config.environment != environment:
        raise LiveSessionError(
            f"configured environment {config.environment!r} does not match "
            f"requested {environment!r}"
        )
    runtime = load_runtime_config(
        config.runtime_config_path, environment=config.environment
    )
    binding = load_account_binding(
        config.account_binding_path,
        environment=config.environment,
        qmt_path=runtime.qmt_path,
    )

    trader = (trader_factory or _real_trader_factory)(str(runtime.qmt_path))
    try:
        security_type, status_ok = xtconstant_values or _real_xtconstant_values()
        stock_factory = stock_account_factory or _real_stock_account_factory()
        # Discovery: strict query of account infos/statuses, select exactly one
        # normal securities account matching the binding fingerprint.
        stock_account = _select_bound_account(
            trader,
            binding=binding,
            security_account_type=security_type,
            account_status_ok=status_ok,
            stock_account_factory=stock_factory,
        )
        trader.start()
        trader.connect()
        trader.subscribe(stock_account)
    except QmtGate1RuntimeError:
        _attempt_stop(trader)
        raise
    except Exception as exc:  # noqa: BLE001 - construction boundary
        _attempt_stop(trader)
        raise LiveSessionError("live session construction failed") from exc

    # Durable exposure journal: the production bootstrap constructs the
    # concrete SQLite store itself (RR-004) — callers cannot substitute a fake.
    exposure_store = SqliteExposureStore(db_conn)

    # Assemble the stack via the single assembly helper; the bridge + adapter
    # hold an opaque-bound account and no plaintext account id ever crosses
    # into the stack.
    return build_live_stack(
        trader=trader, account=stock_account, store=store, policy=policy,
        exposure_store=exposure_store, event_queue=event_queue,
        trade_date=trade_date, runtime_confirmation_token=runtime_confirmation_token,
        strategy_name=strategy_name, order_timeout_seconds=order_timeout_seconds,
        config_live_enabled=False,
    )


def _attempt_stop(trader: object) -> None:
    try:
        trader.stop()
    except BaseException:
        pass
