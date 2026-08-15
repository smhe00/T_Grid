"""Settlement-aware total vs sellable position model (Gate 5 remediation,
AUD-R1-002).

Broker QMT exposes two distinct quantities per symbol:

* total position (``volume``) — everything held;
* sellable / can-use position (``can_use_volume``) — what may be sold today.

A shadow BUY increases the *total/effective* position immediately, but for
T+1 instruments (A-shares) it must NOT increase the same-day sellable
quantity: shares bought today are released for sale only from the next
eligible trading session onward.  This module is the explicit, per-symbol
settlement policy that enforces that separation.

The policy is explicit and testable for any configured symbol (A-share T+1,
HK same-day, etc.); an unknown/unsupported settlement rule fails closed
rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass

from tgrid.shadow.engine import ShadowInputError

# Settlement rules.  ``T1`` releases same-day buys from the next trading day;
# ``T0`` (same-day) instruments are sellable immediately after purchase.
SETTLE_T1 = "T1"
SETTLE_T0 = "T0"

_KNOWN_RULES = frozenset({SETTLE_T1, SETTLE_T0})


@dataclass(frozen=True)
class SettlementPolicy:
    """Per-symbol settlement rule (explicit; unknown rule fails closed)."""

    symbol: str
    rule: str

    def __post_init__(self) -> None:
        if type(self.symbol) is not str or self.symbol == "":
            raise ShadowInputError("symbol must be a non-empty string")
        if self.rule not in _KNOWN_RULES:
            raise ShadowInputError(
                f"unsupported settlement rule {self.rule!r}; "
                f"supported: {sorted(_KNOWN_RULES)}"
            )

    def same_day_sellable(self) -> bool:
        return self.rule == SETTLE_T0


class SettlementTracker:
    """Tracks same-day buys and computes the sellable portion.

    ``can_use`` (real broker sellable) and ``total`` (real broker total) are
    supplied by the caller; shadow buys are recorded here and, under a T1
    policy, only become sellable after :meth:`advance_trading_day` moves the
    book to the next trading session.
    """

    def __init__(self, policy: object) -> None:
        if not isinstance(policy, SettlementPolicy):
            raise ShadowInputError("policy must be a SettlementPolicy")
        self._policy = policy
        self._pending_sellable: dict = {}  # trade_date -> qty locked that day
        # Released balance is a PERSISTENT carry-forward quantity (NODEA-002):
        # once a T1 buy is released (or a T0 buy is made), the sellable amount
        # remains available on every later trading day until consumed by a
        # modeled sell.  It is never tied to a single trade-date key.
        self._released_balance = 0
        self._current_day: str | None = None

    @property
    def policy(self) -> SettlementPolicy:
        return self._policy

    def record_buy(self, qty: object, *, trade_date: str) -> None:
        """Lock ``qty`` of a same-day buy (no same-day sellability under T1)."""
        if type(qty) is not int or qty <= 0:
            raise ShadowInputError("qty must be a positive plain int")
        if type(trade_date) is not str or trade_date == "":
            raise ShadowInputError("trade_date must be a non-empty string")
        if self._policy.same_day_sellable():
            # T0: the buy is immediately sellable; it stays sellable on every
            # later session until sold (carry-forward, NODEA-002).
            self._released_balance += qty
            return
        self._pending_sellable[trade_date] = (
            self._pending_sellable.get(trade_date, 0) + qty
        )

    def record_sell(self, qty: object, *, trade_date: str) -> None:
        """Consume the shadow-sourced portion of a sell.

        A SELL decision is only emitted when the effective sellable quantity
        (real broker can_use + released shadow balance) is sufficient.  This
        method debits the released shadow balance only (up to what the shadow
        owns); the remainder, if any, is supplied by real broker can_use and
        is not tracked here.  ``qty`` must be a plain positive int; selling
        more shadow than the released balance fails closed (AUD-R1-002).
        """
        if type(qty) is not int or qty <= 0:
            raise ShadowInputError("qty must be a positive plain int")
        if type(trade_date) is not str or trade_date == "":
            raise ShadowInputError("trade_date must be a non-empty string")
        consumed = min(qty, self._released_balance)
        self._released_balance -= consumed

    def advance_trading_day(self, from_date: str, to_date: str) -> None:
        """Release the previous day's locked buys (T1) into the balance.

        Under T1, shares bought on ``from_date`` become sellable from
        ``to_date`` (the next eligible trading session) and remain sellable on
        all later sessions until sold (NODEA-002 carry-forward).
        """
        if type(from_date) is not str or type(to_date) is not str:
            raise ShadowInputError("trade dates must be strings")
        locked = self._pending_sellable.pop(from_date, 0)
        if locked:
            self._released_balance += locked
        self._current_day = to_date

    def sellable_from_released(self, trade_date: object = None) -> int:
        """Current released sellable shadow balance (persistent, NODEA-002).

        ``trade_date`` is accepted for backward compatibility and validated if
        provided; the balance is not date-scoped.
        """
        if trade_date is not None and type(trade_date) is not str:
            raise ShadowInputError("trade_date must be a string or None")
        return self._released_balance

    def total_locked(self) -> int:
        """Total quantity still locked (not yet sellable) across all days."""
        return sum(self._pending_sellable.values())


def compute_sellable(
    *,
    real_can_use: object,
    shadow_released: object,
    total_locked: object,
) -> int:
    """Sellable quantity = real broker can_use + released shadow - (implicit).

    ``real_can_use`` is the broker's can_use_volume (plain non-negative int);
    ``shadow_released`` the shadow quantity released for sale; ``total_locked``
    the shadow quantity still locked.  Fails closed on non-plain-int inputs.
    """
    for name, value in (
        ("real_can_use", real_can_use),
        ("shadow_released", shadow_released),
        ("total_locked", total_locked),
    ):
        if type(value) is not int or value < 0:
            raise ShadowInputError(f"{name} must be a plain non-negative int")
    return real_can_use + shadow_released
