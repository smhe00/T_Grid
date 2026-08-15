"""Adaptive geometric grid mathematics (Gate 3, offline, design §10–§11).

The grid width is adaptive to volatility:

    G = clip(max(G_min, K_ATR × ATR%), G_min, G_max)

(design §10; the cost term K_cost × Cost is not part of the V1 config surface
and is intentionally omitted rather than guessed).  Buy levels are geometric:

    Buy_n = Anchor × (1 - G)^n          (n = 1, 2, …)

and a T-lot exits at its own cost-based target:

    ExitPrice_i = EntryPrice_i × (1 + G × ExitMultiplier)

(design §11).  All functions are pure, deterministic, and fail closed on
invalid inputs (no NaN, no negative grid, no degenerate levels).
"""

from __future__ import annotations

from tgrid.strategy.exceptions import StrategyInputError


def _require_finite_number(value, name: str) -> float:
    if type(value) not in (int, float) or isinstance(value, bool):
        raise StrategyInputError(f"{name} must be a number")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise StrategyInputError(f"{name} must be finite")
    return result


def grid_pct(
    atr_pct: float,
    *,
    atr_k: float,
    min_grid: float,
    max_grid: float,
) -> float:
    """Adaptive grid width G = clip(max(G_min, K_ATR × ATR%), G_min, G_max).

    ``atr_pct`` is ATR14/Close (non-negative), ``atr_k`` > 0, and
    ``0 < min_grid <= max_grid``.  Returns a finite value inside
    ``[min_grid, max_grid]``; a zero ``atr_pct`` degrades to ``min_grid``
    (fail closed to the widest safe minimum, never a zero-width grid).
    """
    atr = _require_finite_number(atr_pct, "atr_pct")
    k = _require_finite_number(atr_k, "atr_k")
    g_min = _require_finite_number(min_grid, "min_grid")
    g_max = _require_finite_number(max_grid, "max_grid")
    if atr < 0:
        raise StrategyInputError("atr_pct must be >= 0")
    if k <= 0 or g_min <= 0 or g_max <= 0:
        raise StrategyInputError("atr_k, min_grid and max_grid must be > 0")
    if g_max < g_min:
        raise StrategyInputError("max_grid must be >= min_grid")
    raw = max(g_min, k * atr)
    return min(raw, g_max)


def buy_level(anchor: float, g: float, n: int) -> float:
    """Buy_n = Anchor × (1 - G)^n (design §11), n >= 1.

    ``anchor`` > 0, ``0 < g < 1``, ``n`` a plain positive int.  Returns a
    strictly positive finite level strictly below the anchor for g > 0.
    """
    anchor_value = _require_finite_number(anchor, "anchor")
    g_value = _require_finite_number(g, "g")
    if anchor_value <= 0:
        raise StrategyInputError("anchor must be > 0")
    if not (0 < g_value < 1):
        raise StrategyInputError("g must be strictly between 0 and 1")
    if type(n) is not int or n < 1:
        raise StrategyInputError("n must be a plain positive int")
    level = anchor_value * ((1.0 - g_value) ** n)
    if level <= 0 or level != level:
        raise StrategyInputError("buy level must be finite and positive")
    return level


def exit_target_price(entry_price: float, g: float, exit_multiple: float) -> float:
    """ExitPrice = EntryPrice × (1 + G × ExitMultiplier) (design §11, §15).

    ``entry_price`` > 0, ``0 < g < 1``, ``exit_multiple`` >= 1.  The target is
    strictly above the entry price, so a T-lot can never be told to exit below
    its cost (no price stop-loss, INV-007).
    """
    entry = _require_finite_number(entry_price, "entry_price")
    g_value = _require_finite_number(g, "g")
    multiple = _require_finite_number(exit_multiple, "exit_multiple")
    if entry <= 0:
        raise StrategyInputError("entry_price must be > 0")
    if not (0 < g_value < 1):
        raise StrategyInputError("g must be strictly between 0 and 1")
    if multiple < 1:
        raise StrategyInputError("exit_multiple must be >= 1")
    target = entry * (1.0 + g_value * multiple)
    if target <= entry or target != target:
        raise StrategyInputError("exit target must be finite and above entry")
    return target


class _Side:
    BUY = "BUY"
    SELL = "SELL"


Side = _Side()


def legalize_price(price: float, price_tick: float, *, side: str) -> float:
    """Round ``price`` to the exchange ``price_tick`` without guessing (design §18.1).

    A BUY limit is floored (never pay more than the level); a SELL limit is
    ceiled (never accept less than the target).  The result is always a legal
    tick value; the caller is never given an "automatic correction" toward an
    opaque direction.  ``price_tick`` > 0, ``side`` exactly ``BUY`` or ``SELL``.
    """
    price_value = _require_finite_number(price, "price")
    tick = _require_finite_number(price_tick, "price_tick")
    if price_value <= 0 or tick <= 0:
        raise StrategyInputError("price and price_tick must be > 0")
    if side not in (Side.BUY, Side.SELL):
        raise StrategyInputError("side must be BUY or SELL")
    # Exact decimal division so floating-point noise (e.g. 420.0 / 0.2 ==
    # 2099.9999...) can never push a legal tick off the lattice (design §18.1:
    # never auto-correct in an opaque direction).
    from decimal import Decimal

    quotient = Decimal(str(price_value)) / Decimal(str(tick))
    if quotient == quotient.to_integral_value():
        steps = int(quotient)
    elif side == Side.BUY:
        steps = int(quotient)  # floor for positive prices
    else:
        steps = int(quotient) + 1  # ceil for positive prices
    return round(steps * tick, 10)
