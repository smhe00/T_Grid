"""Crash recovery reconciliation (Gate 4, offline, design §21–§23).

On startup the engine must reconstruct state from the broker (orders + trades)
plus the local OrderIntent store — never from callback history (design §23).
:func:`reconcile_open_intents` walks every local intent that is not terminal,
matches it against the broker order book by ``client_order_key``/remark, and
produces one of:

* ``MATCHED`` — the broker order exists and its status is known;
* ``INTENT_ONLY`` — the intent exists locally but no broker order matches:
  this is the "crash after local write, before broker send" case and must not
  be re-sent blindly (it may still reach the broker late);
* ``UNMATCHED_BROKER_ORDER`` — a broker order with a TGRID remark has no local
  intent: this is a duplicate-order risk and requires SAFE_MODE.

The decision is data-only and fail-closed: anything ambiguous raises
:class:`OrderReconciliationError` instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass

from tgrid.execution.models import OrderIntent, OrderStatus
from tgrid.execution.port import BrokerOrder, BrokerTrade
from tgrid.execution.store import ExecutionStore
from tgrid.risk.exceptions import TGridError

# Broker-side statuses reported by query_order (design §24).
BrokerOrderStatus = OrderStatus  # reuse the single status set


class OrderReconciliationError(TGridError):
    """Broker/local state cannot be reconciled; fail closed to SAFE_MODE."""


@dataclass(frozen=True)
class IntentReconciliation:
    """Outcome of reconciling one local intent against the broker."""

    client_order_key: str
    outcome: str  # MATCHED | INTENT_ONLY | UNMATCHED_BROKER_ORDER
    broker_status: str | None
    matched_broker_order_id: str | None
    filled_qty: int


def _terminal(intent: OrderIntent) -> bool:
    return intent.status in ("FILLED", "CANCELED", "REJECTED", "UNKNOWN")


def reconcile_open_intents(
    store: object,
    broker: object,
    *,
    strategy_name: str = "TGRID",
) -> tuple:
    """Reconcile non-terminal local intents against the broker order book.

    ``store`` is an :class:`ExecutionStore`, ``broker`` any broker port
    (SimBroker or LiveBrokerAdapter/bridge) exposing ``query_orders()``.
    Returns a tuple of :class:`IntentReconciliation` (one per open intent).
    Matching is by ``client_order_key`` first, then by ``order_remark``
    (design §18 tag); an intent whose broker order cannot be found is reported
    as ``INTENT_ONLY`` (never silently re-sent).  Raises
    :class:`OrderReconciliationError` on a broker query failure so the engine
    can enter SAFE_MODE.
    """
    if not isinstance(store, ExecutionStore):
        raise OrderReconciliationError("store must be an ExecutionStore")
    if type(strategy_name) is not str or strategy_name == "":
        raise OrderReconciliationError("strategy_name must be a non-empty string")

    results = []
    open_intents = [i for i in store.list_intents() if not _terminal(i)]
    broker_orders = broker.query_orders()

    for intent in open_intents:
        match = None
        for order in broker_orders:
            if getattr(order, "client_order_key", None) == intent.client_order_key:
                match = order
                break
        if match is None:
            for order in broker_orders:
                if getattr(order, "order_remark", None) == intent.order_remark:
                    match = order
                    break
        if match is None:
            results.append(
                IntentReconciliation(
                    client_order_key=intent.client_order_key,
                    outcome="INTENT_ONLY",
                    broker_status=None,
                    matched_broker_order_id=None,
                    filled_qty=0,
                )
            )
        else:
            results.append(
                IntentReconciliation(
                    client_order_key=intent.client_order_key,
                    outcome="MATCHED",
                    broker_status=match.status,
                    matched_broker_order_id=match.order_id,
                    filled_qty=match.filled_qty,
                )
            )

    # Broker orders tagged TGRID that have no local intent: duplicate-order risk.
    local_keys = {i.client_order_key for i in store.list_intents()}
    matched_keys = {r.client_order_key for r in results if r.outcome == "MATCHED"}
    for order in broker_orders:
        remark = getattr(order, "order_remark", None)
        if remark is None or not remark.startswith("TG_"):
            continue
        if order.order_id in local_keys:
            continue
        if getattr(order, "client_order_key", None) in local_keys:
            continue
        if getattr(order, "client_order_key", None) in matched_keys:
            continue
        if order.status in ("FILLED", "CANCELED", "REJECTED"):
            continue  # historical noise, not an open risk
        results.append(
            IntentReconciliation(
                client_order_key="<none>",
                outcome="UNMATCHED_BROKER_ORDER",
                broker_status=order.status,
                matched_broker_order_id=order.order_id,
                filled_qty=order.filled_qty,
            )
        )

    return tuple(results)
