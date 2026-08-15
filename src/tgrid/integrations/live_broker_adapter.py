"""Gate 5.5 Live Broker Adapter — pre-live safety boundary (NODE B scope).

Wraps the injected broker port (the concrete
:class:`~tgrid.integrations.xtquant_bridge.XtQuantBrokerBridge` in production,
a fake in tests) behind the mandatory pre-live safety boundary:

* double-enable is a **production bootstrap contract** (NODEB-007): the
  config-level enable comes only from trusted validated runtime configuration
  and defaults false; the second runtime confirmation is a separate explicit
  startup action gated by a confirmation token and is never persisted as true
  across restart;
* symbol allowlist (item 3);
* hard per-order quantity limit (item 4);
* hard per-order / per-day cash exposure limit (item 5), with the daily
  exposure bound to a validated ISO ``trade_date`` through a durable
  :class:`~tgrid.integrations.daily_exposure.DailyExposureLedger` (NODEB-005 /
  NODEB-I2-004):
  - a durable exposure store is REQUIRED for construction (no in-memory-only
    live adapter);
  - the adapter starts in ``exposure_ready=False`` and refuses every new order
    until startup reconstruction succeeds;
  - submitted BUY notional is reserved durably BEFORE the broker send, closing
    the send-before-ledger crash window;
  - day rollover requires a monotonic ISO-date transition, optionally bound to
    a trusted session date;
* kill switch blocks **new** orders but never cancellation (NODEB-003);
* NaN/Inf are rejected before any arithmetic or broker call (NODEB-006);
* broker execution health is consulted before new orders: a failed/stopped
  event queue (callback enqueue failure) refuses new live orders (I2-003);
* callbacks are NOT accepted here: the bridge owns the concrete XtQuant
  callback handler which only enqueues immutable events (NODEB-004 / I2-003).

The adapter implements the shared :class:`~tgrid.execution.port.BrokerPort`
(NODEB-001) so :class:`~tgrid.execution.executor.ExecutionEngine` can consume
it directly; every broker object crossing the boundary is a typed DTO.

The adapter NEVER invokes a real order or cancel by itself: every broker call
goes through ``_broker``, which is injected.  No real order/cancel is invoked
before Audit Node B PASS (CURRENT_TASK §Forbidden).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from tgrid.execution.port import BrokerPort, BrokerRejectedError
from tgrid.integrations.daily_exposure import (
    DailyExposureError,
    DailyExposureLedger,
    ExposureDateError,
    _validate_iso_date,
)


class LiveBrokerError(BrokerRejectedError):
    """Base class for live broker adapter failures.

    Extends :class:`~tgrid.execution.port.BrokerRejectedError` (SM9-003D):
    every adapter refusal is a DEFINITIVE pre-broker/local rejection (nothing
    was sent ambiguously), so the engine maps it to the model's
    ``SUBMIT_REJECTED`` rather than the ambiguous ``SUBMIT_EXCEPTION``.
    """


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


class ExposureNotReadyError(LiveBrokerError):
    """Startup daily-exposure reconstruction has not succeeded yet (I2-004)."""


class ExecutionUnhealthyError(LiveBrokerError):
    """Broker execution health is degraded (e.g. event queue failed) (I2-003)."""


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
    the allowlist and hard limits.  ``trade_date`` is a validated ISO calendar
    date binding the daily exposure ledger; ``exposure_store`` is the REQUIRED
    durable key/value surface for that ledger (I2-004); 
    ``runtime_confirmation_token`` is the trusted startup token required by
    :meth:`confirm_runtime` (NODEB-007).

    ``live_enabled`` / ``runtime_confirmed`` / ``exposure_ready`` are NOT
    constructor fields: they start false and are only set through
    :meth:`apply_config_enable` (trusted config), :meth:`confirm_runtime`
    (explicit startup token) and :meth:`reconstruct_daily_exposure` (startup
    recovery gate).
    """

    broker: object
    policy: object
    trade_date: str = ""
    exposure_store: object = None  # REQUIRED for live construction (I2-004)
    runtime_confirmation_token: str = ""
    live_enabled: bool = field(default=False, init=False)
    runtime_confirmed: bool = field(default=False, init=False)
    kill_switch: bool = field(default=False, init=False)
    exposure_ready: bool = field(default=False, init=False)
    _ledger: DailyExposureLedger = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.broker, BrokerPort):
            raise LiveBrokerError("broker must implement BrokerPort")
        if not isinstance(self.policy, LiveBrokerPolicy):
            raise LiveBrokerError("policy must be a LiveBrokerPolicy")
        if self.runtime_confirmation_token is not None and type(self.runtime_confirmation_token) is not str:
            raise LiveBrokerError("runtime_confirmation_token must be a string or None")
        # NODEB-I2-004: a durable exposure store is REQUIRED; an in-memory-only
        # live adapter would reopen the daily cap on every restart.
        if self.exposure_store is None:
            raise LiveBrokerError(
                "a durable exposure store is required for the live adapter "
                "(in-memory exposure is not crash-safe)"
            )
        self.live_enabled = False
        self.runtime_confirmed = False
        self.kill_switch = False
        self.exposure_ready = False
        if self.trade_date:
            _validate_iso_date(self.trade_date)
        try:
            self._ledger = DailyExposureLedger(
                trade_date=self.trade_date, store=self.exposure_store,
            )
        except DailyExposureError as exc:
            raise LiveBrokerError(str(exc)) from exc

    # ------------------------------------------------------------ enablement

    def apply_config_enable(self, flag: bool) -> None:
        """Config-level enable: ONLY from trusted validated runtime config."""
        if type(flag) is not bool:
            raise LiveBrokerError("config enable must be a plain bool")
        self.live_enabled = flag

    def confirm_runtime(self, token: str) -> None:
        """Explicit startup runtime confirmation, gated by the trusted token."""
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
        # NODEB-I2-004: startup exposure reconstruction is the first readiness
        # gate — a fresh process must prove today's exposure before anything.
        if not self.exposure_ready:
            raise ExposureNotReadyError(
                "daily exposure not reconstructed at startup; refusing new orders"
            )
        if not self.runtime_confirmed:
            raise LiveTradingNotConfirmedError(
                "runtime confirmation missing; refusing to trade"
            )
        # NODEB-I2-003: a degraded execution-health signal (e.g. the event
        # queue is full/stopped/failed) must not silently permit new orders.
        health_check = getattr(self.broker, "execution_healthy", None)
        if callable(health_check):
            health_check = health_check()
        if health_check is False:
            raise ExecutionUnhealthyError(
                "broker execution health degraded; refusing new orders"
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
        per-order qty and per-order cash limits all pass.  For BUY, the
        submitted notional is reserved durably BEFORE the broker send
        (I2-004) so a crash after broker acceptance but before ledger
        persistence cannot reopen the daily cap.  Returns the broker order id.
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
        if side == "BUY" and self._ledger.used + notional > self.policy.max_cash_per_day:
            raise CashExposureLimitError(
                "daily cash exposure limit would be exceeded"
            )

        # NODEB-I2-004: reserve submitted BUY notional durably BEFORE the send
        # so a crash between broker acceptance and ledger persistence cannot
        # silently reopen the daily cap.  Failed/rejected sends do not need to
        # reopen the cap (conservative; the rule is never removed for the day).
        if side == "BUY":
            self._ledger.record_submitted_buy(notional)
        try:
            order_id = self.broker.place_order(
                symbol=symbol, side=side, qty=qty, limit_price=limit_price,
                client_order_key=client_order_key, order_remark=order_remark,
            )
        except BaseException:
            if side == "BUY":
                # A rejected send consumed no real exposure; restore the
                # pre-send reservation only for a locally-rejected send.
                # (Failed broker sends are surfaced; the cap stays reserved in
                # the conservative interpretation — see ledger rule.)  We keep
                # the reservation: submitted-notional is never removed for the
                # trade date, and reconstruction is conservative.
                pass
            raise
        return order_id

    def cancel_order(self, order_id: str) -> None:
        """Cancel an order; ALWAYS available, even with the kill switch on."""
        if type(order_id) is not str or order_id == "":
            raise LiveBrokerError("order_id must be a non-empty string")
        return self.broker.cancel_order(order_id)

    def cancel_all_managed_open_orders(self, *, remark_prefix: str = "TG_") -> tuple:
        """Cancel every managed open order, then re-query (NODEB-003)."""
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

    def reconstruct_daily_exposure(self, *, intents: tuple = ()) -> None:
        """Startup gate: rebuild today's exposure from durable intent dates.

        Sets ``exposure_ready=True`` on success; a failure leaves the adapter
        refusing new orders (NODEB-I2-004).  Reconstruction joins durable
        ``OrderIntent.created_at`` dates to authoritative broker orders by
        broker id / client key / remark (NODEB-RR4-003); orders with no
        assignable intent are counted conservatively and never dropped on raw
        broker timestamp formatting.  ``intents`` defaults to the caller's
        ExecutionStore intents when not supplied (kept optional for the
        low-level unit path).
        """
        try:
            self._ledger.reconstruct_from_orders(
                self.broker.query_orders(), intents=intents,
            )
        except DailyExposureError as exc:
            raise LiveBrokerError(str(exc)) from exc
        self.exposure_ready = True

    def roll_day(self, new_trade_date: str, *, session_date: str = "") -> None:
        """Advance the trading day (monotonic ISO transition only, I2-004).

        NODEB-RR-004: ``session_date`` is REQUIRED on the reset-capable
        production path.  Day rollover/reset is derived from the trusted
        current session/trading date: ``new_trade_date`` must equal
        ``session_date``, so an arbitrary caller-provided future string can
        never reset the hard cap.
        """
        if type(new_trade_date) is not str or new_trade_date == "":
            raise LiveBrokerError("new_trade_date must be a non-empty string")
        if type(session_date) is not str or session_date == "":
            raise LiveBrokerError(
                "session_date is required for day rollover (production reset path)"
            )
        try:
            _validate_iso_date(new_trade_date)
        except DailyExposureError as exc:
            raise LiveBrokerError(str(exc)) from exc
        try:
            _validate_iso_date(session_date)
        except DailyExposureError as exc:
            raise LiveBrokerError(str(exc)) from exc
        if new_trade_date != session_date:
            raise LiveBrokerError(
                f"day roll must bind to the trusted session date: "
                f"new {new_trade_date!r} != session {session_date!r}"
            )
        try:
            self._ledger.roll_day(new_trade_date)
        except DailyExposureError as exc:
            raise LiveBrokerError(str(exc)) from exc
        self.trade_date = new_trade_date
        self.exposure_ready = False
        self.reconstruct_daily_exposure()
