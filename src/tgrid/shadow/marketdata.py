"""Explicit RAW / ADJUSTED market-data acquisition (Gate 5 remediation,
AUD-R1-001).

The strategy's indicator history and the execution-price surface must never
depend on the terminal's default adjustment state.  Every acquisition here
explicitly binds the dividend/adjustment mode and stamps every returned
:class:`~tgrid.strategy.bars.Bar` with the exact :data:`PriceBasis` it was
requested with; an unknown mode fails closed before any underlying call.

XtQuant modes used by this module:

* ``none``  -> RAW (unadjusted) prices: live/execution reference (design §7.1);
* ``front`` -> ADJUSTED (forward-adjusted) history for indicators (design §7.1).

The request wrapper is injectable and offline-testable: the unit tests provide
a fake ``xtdata`` and assert the exact arguments passed to the underlying
``get_market_data_ex`` call, so RAW/ADJUSTED mixing can never happen silently.
"""

from __future__ import annotations

from dataclasses import dataclass

from tgrid.strategy.bars import Bar
from tgrid.shadow.engine import ShadowInputError

# The only supported modes.  ``none`` = RAW, ``front`` = ADJUSTED.
_DIVIDEND_NONE = "none"
_DIVIDEND_FRONT = "front"

_KNOWN_DIVIDEND_MODES = frozenset({_DIVIDEND_NONE, _DIVIDEND_FRONT})

# Period -> kind mapping (design §8/§20: 5m bars drive decisions, 1d drives
# the anchor/ATR basis).  Any other period fails closed.
_KNOWN_PERIODS = frozenset({"1d", "5m"})

# Field list always requested so every Bar has complete OHLCV.
_FIELDS = ["open", "high", "low", "close", "volume"]

_MODE_TO_BASIS = {
    _DIVIDEND_NONE: "RAW",
    _DIVIDEND_FRONT: "ADJUSTED",
}


@dataclass(frozen=True)
class BasisBinding:
    """Auditable record of exactly how one acquisition was made."""

    period: str
    dividend_type: str
    price_basis: str

    def __post_init__(self) -> None:
        if self.period not in _KNOWN_PERIODS:
            raise ShadowInputError(f"unsupported period {self.period!r}")
        if self.dividend_type not in _KNOWN_DIVIDEND_MODES:
            raise ShadowInputError(
                f"unsupported dividend_type {self.dividend_type!r}; "
                "explicit RAW (none) / ADJUSTED (front) only"
            )


def resolve_basis(dividend_type: str) -> str:
    """Map an explicit dividend mode to the price basis, fail closed otherwise."""
    if type(dividend_type) is not str or dividend_type not in _KNOWN_DIVIDEND_MODES:
        raise ShadowInputError(
            "dividend_type must be explicitly 'none' (RAW) or 'front' (ADJUSTED)"
        )
    return _MODE_TO_BASIS[dividend_type]


def _parse_iso_time(value) -> str:
    # xtdata timestamps look like 20260814093500 -> 2026-08-14T09:35:00.
    text = str(value)
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 14:
        raise ShadowInputError("market-data timestamp is not parseable")
    return (
        f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}T"
        f"{digits[8:10]}:{digits[10:12]}:{digits[12:14]}"
    )


def fetch_bars(
    xtdata: object,
    *,
    code: str,
    period: str,
    start_time: str,
    end_time: str,
    dividend_type: str,
    count: int = -1,
) -> tuple:
    """Fetch bars with an explicitly bound basis; returns (bars, binding).

    ``xtdata`` is the injected data module (real ``xtquant.xtdata`` in
    production, a fake in tests).  The returned bars are stamped with the
    basis resolved from ``dividend_type``; the binding is returned alongside
    so callers can persist the auditable basis metadata (AUD-R1-001).
    """
    if type(code) is not str or code == "":
        raise ShadowInputError("code must be a non-empty string")
    if type(start_time) is not str or type(end_time) is not str:
        raise ShadowInputError("start_time/end_time must be strings")
    if type(count) is not int or count == 0 or count < -1:
        raise ShadowInputError("count must be -1 or a positive int")
    binding = BasisBinding(period=period, dividend_type=dividend_type,
                           price_basis=resolve_basis(dividend_type))

    # The explicit mode argument is what makes this deterministic (AUD-R1-001):
    # the underlying call must receive the exact dividend_type we resolved.
    data = xtdata.get_market_data_ex(
        _FIELDS, [code], period,
        start_time=start_time, end_time=end_time, count=count,
        dividend_type=dividend_type, fill_data=True,
    )
    frame = data.get(code)
    if frame is None or len(frame) == 0:
        return (), binding

    bars = []
    for ts, row in frame.iterrows():
        close = float(row["close"])
        if close <= 0:
            raise ShadowInputError("market-data close price must be > 0")
        bars.append(
            Bar(
                symbol=code,
                time=_parse_iso_time(ts),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=close,
                volume=int(row["volume"]),
                kind="DAILY" if period == "1d" else "5m",
                price_basis=binding.price_basis,
            )
        )
    return tuple(bars), binding
