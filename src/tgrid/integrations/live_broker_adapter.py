"""Gate 5.5 Live Broker Adapter — pre-live safety boundary (NODE B scope).

Wraps the injected broker port (the concrete
:class:`~tgrid.integrations.xtquant_bridge.XtQuantBrokerBridge` in production,
a fake in tests) behind the mandatory pre-live safety boundary:

* double-enable is a **production bootstrap contract** (NODEB-007): the
  config-level enable comes only from trusted validated runtime configuration
  and defaults false; the second runtime confirmation is a separate explicit
  startup action gated by a confirmation token and is never persisted as true
  across restart (a fresh adapter always starts with runtime confirmation
  false, even when the config-level enable stays true);
* symbol allowlist (item 3);
* hard per-order quantity limit (item 4);
* hard per-order / per-day cash exposure limit (item 5), with the daily
  exposure bound to ``trade_date`` through a durable
  :class:`~tgrid.integrations.daily_exposure.DailyExposureLedger` that
  reconstructs conservatively on startup and only resets on a monotonic
  trading-day transition (NODEB-005);
* kill switch blocks **new** orders but never cancellation: cancel, re-query,
  recovery and ``cancel_all_managed_open_orders`` stay available (NODEB-003);
* NaN/Inf are rejected before any arithmetic or broker call (NODEB-006);
* callbacks are NOT accepted here: the bridge owns the concrete
  XtQuant callback handler which only enqueues immutable events onto an
  injected event sink (NODEB-004).

The adapter implements the shared :class:`~tgrid.execution.port.BrokerPort`
(NODEB-001) so :class:`~tgrid.execution.executor.ExecutionEngine` can consume
it directly; every broker object crossing the boundary is a typed DTO.

The adapter NEVER invokes a real order or cancel by itself: every broker call
goes through ``_broker``, which is injected.  In production this is the
XtQuantBrokerBridge; in tests it is a fake.  No real order/cancel is invoked
before Audit Node B PASS (CURRENT_TASK §Forbidden).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from tgrid.execution.port import BrokerPort
from tgrid.integrations.daily_exposure import (
    DailyExposureError,
    DailyExposureLedger,
)
from tgrid.risk.exceptions import TGridError


class LiveBrokerError(TGridError):
    """Base class for live broker adapter failures."""


class LiveTradingDisabledError(LiveBrokerError):
    """live_trading is not enabled (config-level enable missing)."""


class LiveTradingNotConfirmedError(LiveBrokerError):
    """The explicit runtime confirmation (token-gated) is missing."""


class RuntimeConfirmationTokenError(LiveBrokerError):
    """The runtime confirmation token is invalid or not configured."""


class SymbolNotAllowedError(LiveBrokerError):
    """The symbol is not on the explicit allowlist."""


class OrderQtyLimitError(LiveBrokerError):
    """The order quantity exceeds the hard per-order limit."""


class CashExposureLimitError(LiveBrokerError):
    """The order notional exceeds the hard cash exposure limit."""


class KillSwitchEngagedError(LiveBrokerError):
    """The kill switch is engaged; no NEW orders are permitted (cancel stays)."""


@dataclass(frozen=True)
class LiveBrokerPolicy:
    """Immutable pre-live safety policy (NODE-B items 2-6)."""

    allowlist: frozenset
    max_order_qty: int
    max_cash_per_order: float
    max_cash_per_day: float

    def __post_init__(self) -> None:
        if not isinstance(self.allowlist, frozenset) or not self.allowlist:
            raise LiveBrokerError("allowlist must be a non-empty frozenset of symbols")
        for symbol in self.allowlist:
            if type(symbol) is not str or symbol == "":
                raise LiveBrokerError("allowlist entries must be non-empty strings")
        if type(self.max_order_qty) is not int or self.max_order_qty <= 0:
            raise LiveBrokerError("max_order_qty must be a positive plain int")
        # NODEB-006: finite positive plain numeric values only (NaN/Inf rejected).
        for name, value in (
            ("max_cash_per_order", self.max_cash_per_order),
            ("max_cash_per_day", self.max_cash_per_day),
        ):
            if type(value) not in (int, float) or isinstance(value, bool):
                raise LiveBrokerError(f"{name} must be a plain number")
            if not math.isfinite(float(value)) or value <= 0:
                raise LiveBrokerError(f"{name} must be a finite positive number")


@dataclass
class LiveBrokerAdapter(BrokerPort):
    """Pre-live broker adapter with mandatory safety boundary.

    ``broker`` is the injected :class:`~tgrid.execution.port.BrokerPort`
    (XtQuantBrokerBridge in production, a fake in tests).  ``policy`` carries
    the allowlist and hard limits.  ``trade_date`` binds the daily exposure
    ledger; ``exposure_store`` is the optional durable key/value surface for
    that ledger; ``runtime_confirmation_token`` is the trusted startup token
    required by :meth:`confirm_runtime` (NODEB-007).

    ``live_enabled`` / ``runtime_confirmed`` are NOT constructor fields: they
    start false and can only be set through :meth:`apply_config_enable` (trusted
    config input) and :meth:`confirm_runtime` (explicit startup token).
    """

    broker: object
    policy: object
    trade_date: str = ""
    exposure_store: object | None = None
    runtime_confirmation_token: str = ""
    live_enabled: bool = field(default=False, init=False)
    runtime_confirmed: bool = field(default=False, init=False)
    kill_switch: bool = field(default=False, init=False)
    _ledger: DailyExposureLedger = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.broker, BrokerPort):
            raise LiveBrokerError("broker must implement BrokerPort")
        if not isinstance(self.policy, LiveBrokerPolicy):
            raise LiveBrokerError("policy must be a LiveBrokerPolicy")
        if type(self.trade_date) is not str:
            raise LiveBrokerError("trade_date must be a string")
        if self.runtime_confirmation_token is not None and type(self.runtime_confirmation_token) is not str:
            raise LiveBrokerError("runtime_confirmation_token must be a string or None")
        self.live_enabled = False
        self.runtime_confirmed = False
        self.kill_switch = False
        try:
            self._ledger = DailyExposureLedger(
                trade_date=self.trade_date, store=self.exposure_store,
            )
        except DailyExposureError as exc:
            raise LiveBrokerError(str(exc)) from exc

    # ------------------------------------------------------------ enablement

    def apply_config_enable(self, flag: bool) -> None:
        """Config-level enable: ONLY from trusted validated runtime config.

        Defaults false; an untrusted value (non-bool) fails closed.  This is
        the first step of the double-enable bootstrap (NODEB-007).
        """
        if type(flag) is not bool:
            raise LiveBrokerError("config enable must be a plain bool")
        self.live_enabled = flag

    def confirm_runtime(self, token: str) -> None:
        """Explicit startup runtime confirmation, gated by the trusted token.

        The second step of double-enable.  Never persisted as true: a fresh
        adapter (process restart) always starts with ``runtime_confirmed``
        false even when the config-level enable remains true (NODEB-007).
        """
        if type(token) is not str:
            raise LiveBrokerError("confirmation token must be a string")
        if not self.runtime_confirmation_token:
            raise RuntimeConfirmationTokenError(
                "no runtime confirmation token configured; refusing to confirm"
            )
        if token != self.runtime_confirmation_token:
            raise RuntimeConfirmationTokenError("runtime confirmation token mismatch")
        self.runtime_confirmed = True

    def _require_ready_to_trade(self) -> None:
        if self.kill_switch:
            raise KillSwitchEngagedError("kill switch engaged; no NEW orders")
        if not self.live_enabled:
            raise LiveTradingDisabledError("live_trading is not enabled")
        if not self.runtime_confirmed:
            raise LiveTradingNotConfirmedError(
                "runtime confirmation missing; refusing to trade"
            )

    def _require_finite_positive(self, value, name: str) -> None:
        if type(value) not in (int, float) or isinstance(value, bool):
            raise LiveBrokerError(f"{name} must be a plain number")
        if not math.isfinite(float(value)) or value <= 0:
            raise LiveBrokerError(f"{name} must be a finite positive number")

    def engage_kill_switch(self) -> None:
        """Emergency disable: blocks NEW orders; cancel/query/recovery stay."""
        self.kill_switch = True

    # ------------------------------------------------------------ order path

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: int,
        limit_price: float,
        client_order_key: str | None = None,
        order_remark: str | None = None,
    ) -> str:
        """Validate the safety boundary, then delegate to the injected broker.

        Exact-type + finiteness validation (NODEB-006) runs BEFORE any broker
        call.  The order is refused unless the double-enable, allowlist,
        per-order qty and per-order cash limits all pass; BUY notional is then
        recorded in the daily ledger (NODEB-005).  Returns the broker order id.
        """
        if type(symbol) is not str or symbol == "":
            raise LiveBrokerError("symbol must be a non-empty string")
        if side not in ("BUY", "SELL"):
            raise LiveBrokerError("side must be BUY or SELL")
        if type(qty) is not int or qty <= 0:
            raise LiveBrokerError("qty must be a positive plain int")
        self._require_finite_positive(limit_price, "limit_price")

        self._require_ready_to_trade()
        if symbol not in self.policy.allowlist:
            raise SymbolNotAllowedError(f"{symbol!r} is not on the allowlist")
        if qty > self.policy.max_order_qty:
            raise OrderQtyLimitError(
                f"order qty {qty} exceeds max_order_qty {self.policy.max_order_qty}"
            )
        notional = qty * float(limit_price)
        if notional > self.policy.max_cash_per_order:
            raise CashExposureLimitError(
                f"order notional {notional:.2f} exceeds max_cash_per_order "
                f"{self.policy.max_cash_per_order:.2f}"
            )
        # The daily ledger counts submitted BUY notional only (SELL does not
        # consume cash exposure; the ledger rule is documented in NODEB-005).
        if side == "BUY" and self._ledger.used + notional > self.policy.max_cash_per_day:
            raise CashExposureLimitError(
                "daily cash exposure limit would be exceeded"
            )

        order_id = self.broker.place_order(
            symbol=symbol, side=side, qty=qty, limit_price=limit_price,
            client_order_key=client_order_key, order_remark=order_remark,
        )
        if side == "BUY":
            self._ledger.record_submitted_buy(notional)
        return order_id

    def cancel_order(self, order_id: str) -> None:
        """Cancel an order; ALWAYS available, even with the kill switch on.

        NODEB-003: the kill switch blocks NEW orders / amend / reprice, never
        cancellation of existing managed orders.  Re-query is the caller's
        responsibility (design §25: cancel never implies zero fill).
        """
        if type(order_id) is not str or order_id == "":
            raise LiveBrokerError("order_id must be a non-empty string")
        return self.broker.cancel_order(order_id)

    def cancel_all_managed_open_orders(self, *, remark_prefix: str = "TG_") -> tuple:
        """Cancel every managed open order, then re-query (NODEB-003).

        Available under the kill switch; returns a tuple of the re-queried
        broker order DTOs so the caller can reconcile after cancellation.
        """
        cancelled: list = []
        for order in self.broker.query_orders():
            remark = getattr(order, "order_remark", None)
            if not isinstance(remark, str) or not remark.startswith(remark_prefix):
                continue
            if getattr(order, "status", None) in ("FILLED", "CANCELED", "REJECTED", "UNKNOWN"):
                continue
            self.broker.cancel_order(order.order_id)
            cancelled.append(order.order_id)
        return tuple(self.broker.query_order(oid) for oid in cancelled)

    def query_order(self, order_id: str):
        """Read the current broker-side order state (always available)."""
        if type(order_id) is not str or order_id == "":
            raise LiveBrokerError("order_id must be a non-empty string")
        return self.broker.query_order(order_id)

    def query_trades(self, order_id: str) -> tuple:
        if type(order_id) is not str or order_id == "":
            raise LiveBrokerError("order_id must be a non-empty string")
        return self.broker.query_trades(order_id)

    def query_orders(self, *, symbol: str | None = None) -> tuple:
        if symbol is not None and type(symbol) is not str:
            raise LiveBrokerError("symbol must be a string or None")
        return self.broker.query_orders(symbol=symbol)

    # ------------------------------------------------------------- exposure

    @property
    def daily_cash_used(self) -> float:
        return self._ledger.used

    def reconstruct_daily_exposure(self) -> None:
        """Rebuild today's exposure from managed broker orders (NODEB-005).

        Call on startup/recovery BEFORE enabling new orders so a restart can
        never silently reopen the daily cap.
        """
        try:
            self._ledger.reconstruct_from_orders(self.broker.query_orders())
        except DailyExposureError as exc:
            raise LiveBrokerError(str(exc)) from exc

    def roll_day(self, new_trade_date: str) -> None:
        """Advance the trading day; ONLY a strict monotonic transition resets."""
        if type(new_trade_date) is not str or new_trade_date == "":
            raise LiveBrokerError("new_trade_date must be a non-empty string")
        try:
            self._ledger.roll_day(new_trade_date)
        except DailyExposureError as exc:
            raise LiveBrokerError(str(exc)) from exc
        self.trade_date = new_trade_date
        self.reconstruct_daily_exposure()
