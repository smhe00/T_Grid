"""QMT adapter layer (Gate 1, read-only boundary).

Contains no XtQuant import and no trading surface.  The only capability here is
the read-only ``ReadOnlyTraderAdapter``, which talks to an injected client via
the fixed read-only method mapping in ``qmt_readonly``.
"""

from tgrid.adapters.qmt_readonly import (
    ReadOnlyTraderAdapter,
    ReadOnlyTraderState,
)

__all__ = ["ReadOnlyTraderAdapter", "ReadOnlyTraderState"]
