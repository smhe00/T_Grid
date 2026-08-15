# Gate 5.5 Audit Node B — Independent Pre-Live Review — 2026-08-15

## Verdict

`CHANGES_REQUIRED` — Gate 5.5 is not independently accepted for first-real-order readiness.

Audit target GitHub `main` snapshot:

```text
9319465e5b2aa38a2a713dca3e25b93c69d4412f
```

Gate-5.5 implementation commit:

```text
249aa061842eac114d224b384164541619628edc
```

Gate 5 remains independently PASS. Gate 6 / Gate 7 remain BLOCKED. `live_trading_allowed=false` remains mandatory. No real order/cancel invocation is authorized.

## Independently accepted in this iteration

- `NODEB-P0-001` legacy reconciliation Core guard is now wired through the loader: legacy `core_qty` is preserved as `legacy_core_qty`, compared against `SymbolConfig.core_qty`, and never used as a second Core source.
- `LiveBrokerPolicy` provides a non-empty explicit symbol allowlist and positive per-order quantity / cash policy fields.
- `LiveBrokerAdapter` defaults its live-enable and runtime-confirmation flags to false.
- Basic exact-type checks reject non-plain-int quantity and non-numeric price inputs before broker delegation.
- The repository still contains no real XtQuant order/cancel invocation in the Gate-5.5 evidence run, so the pre-live boundary itself was respected.

These accepted items should be retained while fixing the blockers below.

## Blocking findings

### NODEB-001 — P0: target execution chain is not actually connected

The authorized architecture is:

```text
ExecutionEngine -> LiveBrokerAdapter -> XtQuantTrader
```

but the current implementation does not provide that chain.

`ExecutionEngine.__init__` still requires `isinstance(broker, SimBroker)` and later calls SimBroker-specific methods such as `get_order()` and `tick_order()`. Therefore a `LiveBrokerAdapter` cannot be injected into `ExecutionEngine` at all.

At the other end, `LiveBrokerAdapter` only delegates to an abstract injected object exposing `place_order/cancel_order/query_*`; there is no concrete audited XtQuant execution bridge that maps this contract to `XtQuantTrader.order_stock`, `cancel_order_stock`, order status, trades, account token, side constants, price type and remark/client key.

The current capability scan treating **zero** `order_stock/cancel_order_stock` call sites as PASS proves that the real execution capability is absent, not that it is ready.

Required:

1. Define one narrow broker execution port/protocol shared by dry-run and live execution.
2. Refactor `ExecutionEngine` so production execution does not require `SimBroker` and does not depend on `tick_order/get_order` simulation hooks. Keep deterministic scripts in a simulation-only driver/path.
3. Implement exactly one concrete XtQuant broker bridge whose audited call sites are the only permitted `order_stock/cancel_order_stock` calls in the repository.
4. Map broker order/trade/status objects into TGrid-owned typed DTOs so the core does not depend on raw XtQuant object shapes.
5. Update capability scan to allowlist the exact concrete bridge call sites and fail on any additional direct real-broker invocation elsewhere.
6. Use fakes/mocks for tests only; still do not invoke a real order/cancel before Node B PASS.

### NODEB-002 — P0: Gate-4 idempotency / reservation / recovery are not integrated with the live adapter

The self-review claims that Gate-4 OrderIntent + Reservation-before-send semantics are reused, but no test or code path exercises `ExecutionEngine` with `LiveBrokerAdapter`; the current executor rejects it as noted above.

Likewise partial-fill, timeout/cancel/re-query and crash recovery are only demonstrated either by SimBroker logic or by isolated adapter query methods. That is not an end-to-end pre-live proof.

Required integration tests using the real execution port plus fake concrete broker backend:

- durable `OrderIntent + Reservation` created before broker send;
- duplicate `client_order_key` never causes a second broker send;
- crash after local reservation/intent but before send => no blind resend;
- crash after broker accepts but before local broker-id/status persistence => startup reconciliation detects/recovers or enters SAFE_MODE;
- partial fill updates filled quantity while preserving remaining reservation semantics;
- timeout path is exactly `cancel request -> broker re-query -> trade/order reconcile`;
- unmatched tagged broker order => SAFE_MODE / explicit unresolved state;
- broker query failure or ambiguous status => fail closed.

### NODEB-003 — P0: kill switch blocks cancellation

`cancel_order()` calls `_require_ready_to_trade()`, and `_require_ready_to_trade()` raises immediately when `kill_switch=True`. Thus after the emergency switch is engaged, TGrid cannot cancel its existing open orders through this adapter.

That is the opposite of the required emergency behavior.

Required:

- kill switch blocks **new order / amend / reprice** capability;
- query and recovery remain available;
- cancellation of existing managed orders remains available, preferably with an explicit `cancel_all_managed_open_orders()` path followed by broker re-query/reconciliation;
- tests must prove `kill_switch=True` rejects new orders but still permits cancel + re-query of an existing order.

### NODEB-004 — P0: callback isolation is not structurally enforced

`register_callback(callback)` accepts an arbitrary callable and simply invokes it. The test only proves the returned function does not expose a `.broker` attribute. A callback closure can still capture the adapter, store, engine, DB object or other mutable state and mutate it directly or issue an order.

Therefore the claim that callbacks are structurally limited to Event Queue enqueueing is not established.

Required:

- remove the generic arbitrary-callback execution boundary for broker callbacks;
- concrete XtQuant callback handlers should be adapter-owned and convert broker callback payloads into immutable/data-only TGrid events, then perform only `event_queue.put(event)`;
- callback objects must not receive or retain ExecutionEngine, ExecutionStore, strategy state or an order-capable adapter reference;
- add tests that exercise the concrete callback bridge and verify it only enqueues events; all state changes occur later on the single strategy/event thread.

### NODEB-005 — P0: daily exposure guard is volatile and resettable, so restart/manual reset bypasses the cap

`_daily_cash_used` is in-memory only and initializes to zero on every adapter construction. `reset_daily_exposure()` is also a public unconditional reset. A restart or an accidental/inappropriate call during the same trading day can therefore reopen the full daily limit.

This violates the intended hard daily exposure boundary and the deterministic crash-recovery requirement.

Required:

- bind exposure accounting to `trade_date` and durable/reconstructable local/broker state;
- on startup/recovery, reconstruct the current-day exposure conservatively from managed broker orders/trades and/or persisted intents/reservations before enabling new orders;
- reset only on a validated monotonic trading-day transition, not through an unrestricted public zeroing method;
- define whether the cap counts submitted BUY notional, filled BUY notional, active reservation or a conservative maximum, and make that rule deterministic under cancel/reject/partial-fill/restart;
- add restart and same-day-reset fault-injection tests.

### NODEB-006 — P0: NaN can bypass cash/price limits

`LiveBrokerPolicy` and `place_order()` check positivity but not finiteness. Python `float('nan')` is neither `<= 0` nor `> limit`, so NaN policy values / prices can flow through comparisons and bypass the cash gates.

Required:

- require all monetary/price limits and prices to be finite positive plain numeric values (`math.isfinite` after exact-type acceptance);
- reject NaN and +/-Inf before any arithmetic or broker call;
- add tests for NaN/Inf in policy values and `limit_price`.

### NODEB-007 — P1: double-enable is only two mutable booleans, not a production bootstrap contract

The current dataclass can be constructed directly with `live_enabled=True, runtime_confirmed=True`, and both flags can be toggled through public methods. This is adequate as a unit-test scaffold but not sufficient as the production activation path.

Before Node B PASS, production wiring must establish:

- config-level enable comes only from trusted validated runtime configuration and defaults false;
- runtime confirmation is a separate explicit startup action/token and is never persisted as true across restart;
- strategy callbacks/event handlers cannot invoke the enable/confirm methods;
- process restart returns to runtime-confirmation false even when config live enable remains true.

## Evidence quality note

The reported `865 tests OK`, compileall result and capability scan are `SELF_CERTIFIED`. The repository exposes no GitHub CI result for this implementation. More importantly, the current tests do not cover the required live-execution integration chain; `test_live_broker_adapter.py` exercises the adapter in isolation with `_FakeBroker`.

## Iteration-2 stop condition

DSH is authorized only to fix the Node-B findings above. It must not place or cancel a real broker order during the remediation.

After the fixes:

1. push normally to `main`;
2. set state to `AUDIT_READY_PRELIVE`;
3. record exact implementation commit(s) and self-certified test evidence;
4. include integration tests for the full `ExecutionEngine -> LiveBrokerAdapter -> FakeXtQuantBridge` path and concrete XtQuant argument/status mapping without invoking the real client;
5. authorize only `AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`;
6. STOP.

First real order remains prohibited until:

```text
Audit Node B = PASS
AND
explicit user authorization = YES
```
