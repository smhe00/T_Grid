"""TGrid XtQuant integration boundary (G1-T006, user-authorized read-only).

Only ``run_gate1_readonly_acceptance`` is public.  The builder, bridges, and
opaque token are module-private; nothing here returns a raw client, bridge,
account object, or any business data, and nothing enables trading.
"""

from tgrid.integrations.qmt_gate1_runtime import (
    QmtGate1RuntimeAccountError,
    QmtGate1RuntimeConfigError,
    QmtGate1RuntimeConnectionError,
    QmtGate1RuntimeError,
    run_gate1_readonly_acceptance,
)

__all__ = [
    "QmtGate1RuntimeError",
    "QmtGate1RuntimeConfigError",
    "QmtGate1RuntimeConnectionError",
    "QmtGate1RuntimeAccountError",
    "run_gate1_readonly_acceptance",
]
