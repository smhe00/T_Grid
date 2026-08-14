"""TGrid probe orchestrators.

Contains only offline, read-only integration probes.  ``gate1_readonly``
combines the approved Trader and MarketData adapters into a fixed-order Gate 1
probe; nothing here imports XtQuant, connects to QMT, or reads real
account/market data.
"""

from tgrid.probes.gate1_readonly import (
    Gate1ReadOnlyProbeSummary,
    run_gate1_readonly_probe,
)

__all__ = ["Gate1ReadOnlyProbeSummary", "run_gate1_readonly_probe"]
