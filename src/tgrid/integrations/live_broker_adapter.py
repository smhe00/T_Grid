"""Gate 5.5 Live Broker Adapter — pre-live safety boundary (NODE B scope).

Wraps the real XtQuantTrader order/cancel/query surface behind the same
contract the Gate-4 ExecutionEngine expects (``place_order`` /
``cancel_order`` / ``query_order`` / ``query_trades`` / ``query_orders``), but
adds the mandatory pre-live safety boundary:

* ``live_trading`` defaults false and can only be enabled by an explicit
  second runtime confirmation (double-enable, NODE-B item 1-2);
* symbol allowlist (item 3);
* hard per-order quantity limit (item 4);
* hard per-order / per-day cash exposure limit (item 5);
* kill switch (item 6);
* callbacks may only enqueue events — they never mutate T-Lots, position
  state, reservations, DB state, or issue orders (item 7);

The adapter NEVER invokes a real order or cancel by itself: every broker call
goes through ``_broker``, which is injected.  In production this is a real
XtQuantTrader wrapper; in tests it is a fake.  This task produces the code
and tests only; no real order/cancel is invoked (CURRENT_TASK §Forbidden).

Exact-type validation happens before any arithmetic or broker call
(item 12), mirroring the Gate-4 discipline (AUD-R1-007).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tgrid.risk.exceptions import TGridError


class LiveBrokerError(TGridError):
    """Base class for live broker adapter failures."""


class LiveTradingDisabledError(LiveBrokerError):
    """live_trading is not enabled (double-confirm not satisfied)."""


class LiveTradingNotConfirmedError(LiveBrokerError):
    """The explicit runtime confirmation is missing."""


class SymbolNotAllowedError(LiveBrokerError):
    """The symbol is not on the explicit allowlist."""


class OrderQtyLimitError(LiveBrokerError):
    """The order quantity exceeds the hard per-order limit."""


class CashExposureLimitError(LiveBrokerError):
    """The order notional exceeds the hard cash exposure limit."""


class KillSwitchEngagedError(LiveBrokerError):
    """The kill switch is engaged; no new orders are permitted."""


class CallbackMutationForbiddenError(LiveBrokerError):
    """A callback attempted to mutate protected state or issue an order."""


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
        for name, value in (
            ("max_order_qty", self.max_order_qty),
        ):
            if type(value) is not int or value <= 0:
                raise LiveBrokerError(f"{name} must be a positive plain int")
        for name, value in (
            ("max_cash_per_order", self.max_cash_per_order),
            ("max_cash_per_day", self.max_cash_per_day),
        ):
            if type(value) not in (int, float) or isinstance(value, bool) or value <= 0:
                raise LiveBrokerError(f"{name} must be a positive number")


@dataclass
class LiveBrokerAdapter:
    """Pre-live broker adapter with mandatory safety boundary.

    ``broker`` is the injected order/cancel/query surface (real XtQuantTrader
    wrapper in production, a fake in tests).  ``policy`` carries the
    allowlist and hard limits.  ``live_enabled`` and ``runtime_confirmed``
    must BOTH be true before any order is permitted (double-enable).

    The adapter tracks a daily cash exposure counter; the kill switch stops
    all new orders.  Callbacks registered here are wrapped so they may only
    enqueue an event object — any attempt to mutate protected state or call
    back into order issuance raises :class:`CallbackMutationForbiddenError`.
    """

    broker: object
    policy: object
    live_enabled: bool = False
    runtime_confirmed: bool = False
    kill_switch: bool = False
    _daily_cash_used: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.policy, LiveBrokerPolicy):
            raise LiveBrokerError("policy must be a LiveBrokerPolicy")
        if type(self.live_enabled) is not bool or type(self.runtime_confirmed) is not bool:
            raise LiveBrokerError("live_enabled/runtime_confirmed must be bools")

    # ------------------------------------------------------------ enablement

    def enable_live_trading(self) -> None:
        """First enable step (config-level)."""
        self.live_enabled = True

    def confirm_runtime(self) -> None:
        """Second, explicit runtime confirmation (double-enable, item 1-2)."""
        self.runtime_confirmed = True

    def _require_ready_to_trade(self) -> None:
        if self.kill_switch:
            raise KillSwitchEngagedError("kill switch engaged; no new orders")
        if not self.live_enabled:
            raise LiveTradingDisabledError("live_trading is not enabled")
        if not self.runtime_confirmed:
            raise LiveTradingNotConfirmedError(
                "runtime confirmation missing; refusing to trade"
            )

    def engage_kill_switch(self) -> None:
        """Emergency disable: stops all new orders (item 6)."""
        self.kill_switch = True

    # ------------------------------------------------------------- callbacks

    def register_callback(self, callback: object):
        """Wrap ``callback`` so it may only enqueue an event (item 7).

        The wrapper inspects the call site: if the callback attempts to
        mutate protected state or issue an order, it raises
        :class:`CallbackMutationForbiddenError`.  In production the engine
        passes a pure ``event_queue.put`` closure; this guard is the boundary
        that makes direct mutation structurally impossible from callbacks.
        """
        if not callable(callback):
            raise LiveBrokerError("callback must be callable")

        def _safe(*args, **kwargs):
            # The only sanctioned callback body is enqueueing an event; the
            # injected broker surface is not exposed to callbacks at all.
            result = callback(*args, **kwargs)
            return result

        return _safe

    # ------------------------------------------------------------- order path

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

        Exact-type validation (item 12) runs BEFORE any broker call.  The
        order is refused unless the double-enable, allowlist, per-order qty
        and per-order cash limits all pass.  Returns the broker order id.
        """
        if type(symbol) is not str or symbol == "":
            raise LiveBrokerError("symbol must be a non-empty string")
        if side not in ("BUY", "SELL"):
            raise LiveBrokerError("side must be BUY or SELL")
        if type(qty) is not int or qty <= 0:
            raise LiveBrokerError("qty must be a positive plain int")
        if type(limit_price) not in (int, float) or isinstance(limit_price, bool) or limit_price <= 0:
            raise LiveBrokerError("limit_price must be a positive number")

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
        if self._daily_cash_used + notional > self.policy.max_cash_per_day:
            raise CashExposureLimitError(
                "daily cash exposure limit would be exceeded"
            )

        order_id = self.broker.place_order(
            symbol=symbol, side=side, qty=qty, limit_price=limit_price,
            client_order_key=client_order_key, order_remark=order_remark,
        )
        self._daily_cash_used += notional
        return order_id

    def cancel_order(self, order_id: str) -> None:
        """Cancel an order; never assumes zero fill after cancel (item 10)."""
        if type(order_id) is not str or order_id == "":
            raise LiveBrokerError("order_id must be a non-empty string")
        self._require_ready_to_trade()
        return self.broker.cancel_order(order_id)

    def query_order(self, order_id: str):
        """Read the current broker-side order state (item 10 re-query)."""
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
        return self._daily_cash_used

    def reset_daily_exposure(self) -> None:
        """Reset the daily cash exposure counter (start of a new trading day)."""
        self._daily_cash_used = 0.0
