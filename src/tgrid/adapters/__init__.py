"""QMT adapter layer (Gate 1, read-only boundary).

Contains no XtQuant import and no trading surface.  The only capabilities here
are the read-only ``ReadOnlyTraderAdapter`` (fixed trader query/lifecycle
methods), ``ReadOnlyMarketDataAdapter`` (fixed market/reference data query
methods), and ``ReadOnlyQuoteSubscriptionAdapter`` (single-subscription
lifecycle), all talking to an injected client via frozen read-only callables.
"""

from tgrid.adapters.marketdata_readonly import ReadOnlyMarketDataAdapter
from tgrid.adapters.qmt_readonly import (
    ReadOnlyTraderAdapter,
    ReadOnlyTraderState,
)
from tgrid.adapters.quote_subscription_readonly import (
    ReadOnlyQuoteSubscriptionAdapter,
    QuoteSubscriptionState,
)

__all__ = [
    "ReadOnlyTraderAdapter",
    "ReadOnlyTraderState",
    "ReadOnlyMarketDataAdapter",
    "ReadOnlyQuoteSubscriptionAdapter",
    "QuoteSubscriptionState",
]
