# Gate 5.5 Audit Node B — Independent Re-Review — Iteration 2 — 2026-08-15

## Verdict

`CHANGES_REQUIRED` — Gate 5.5 is materially closer, but it is still not independently accepted for first-real-order readiness.

Audit target GitHub `main` snapshot:

```text
9ef60c75bd72db94f1cfda919965531c4557cb18
```

Iteration-2 implementation commit:

```text
b4d121c00f4c06a71ba5cb134661eac1a686c3cb
```

Gate 5 remains independently PASS. Gate 6 / Gate 7 remain BLOCKED. `live_trading_allowed=false` remains mandatory. No real order/cancel invocation is authorized.

## Independently accepted / frozen from Iteration 2

The large architectural blocker from Node-B Iteration 1 is closed:

- `BrokerPort` is now the common execution contract;
- `ExecutionEngine` no longer requires `SimBroker` and no longer consumes `tick_order/get_order` simulation hooks;
- deterministic simulation driving is separated into `SimulationDriver`;
- `LiveBrokerAdapter` can be injected into `ExecutionEngine`;
- `XtQuantBrokerBridge` is the single concrete XtQuant order/cancel bridge and the capability scan is based on an explicit bridge allowlist rather than expecting zero real call sites;
- full-chain fake-backend tests now exercise `ExecutionEngine -> LiveBrokerAdapter -> XtQuantBrokerBridge` with durable OrderIntent + Reservation-before-send and duplicate client-key protection;
- kill switch behavior is corrected: new orders are blocked while cancel/query/cancel-all remain available;
- `NODEB-P0-001` legacy Core guard remains fixed;
- adapter policy / limit-price NaN and Inf rejection is implemented;
- generic arbitrary callback registration was removed.

These items should not be reworked unless needed by the remaining blockers.

## Remaining blocking findings

### NODEB-I2-001 — P0: XtQuant native order-id type contract is wrong at the real cancel boundary

The bridge converts the synchronous `order_stock` return value into a string and exposes string `order_id` through the TGrid DTO/port. `cancel_order()` then passes that string directly to:

```python
self._trader.cancel_order_stock(self._account, order_id)
```

However the official XtQuant contract defines:

- `order_stock(...)` return: positive **int** order id (or `-1` on failure);
- `cancel_order_stock(account, order_id)`: `order_id` is **int**;
- `XtOrder.order_id` / `XtTrade.order_id`: **int**.

The current fake trader deliberately generates string ids (`XT00000001`), so the test suite cannot catch the production type mismatch.

Required:

1. Make the fake XtQuant surface mirror the native contract: positive integer order ids.
2. Preserve a lossless internal/native order-id representation or perform one audited, validated conversion at the bridge boundary before cancel.
3. The concrete `cancel_order_stock` invocation must receive an `int` exactly as the XtQuant contract requires.
4. Add a test that inspects the fake trader call and asserts the actual cancel argument is an `int`.
5. Query/order/trade mapping must remain deterministic when TGrid chooses to serialize order ids as strings in its own persistent DTO/store.

### NODEB-I2-002 — P0: UNKNOWN / ambiguous broker state is not fail-closed

`XtQuantBrokerBridge` correctly maps an unrecognized XtQuant `order_status` to `OrderStatus.UNKNOWN`. But `ExecutionEngine.poll_order()` does not fail closed on that value. Instead it leaves the local intent in its previous state (for example `SUBMITTED`) and returns normally.

The new integration test explicitly encodes this behavior: broker status `255` maps to UNKNOWN, but the test expects the local result to remain `SUBMITTED`. This contradicts both the Node-B requirement and the self-review claim that ambiguous state is fail-closed.

Recovery has the same issue: `reconcile_open_intents()` can return `MATCHED` with `broker_status=UNKNOWN` without raising or marking the run unsafe. It also selects the first remark fallback match without detecting multiple candidate broker orders.

Required:

1. Any broker order status outside the known state machine must produce an explicit unresolved/fail-closed outcome before new execution can continue.
2. Preserve reservations while state is unresolved; do not guess FILLED/CANCELED and do not silently downgrade UNKNOWN to SUBMITTED.
3. `poll_order()` should raise a reconciliation/safe-mode signal (or equivalent explicit unresolved result) for UNKNOWN.
4. Startup recovery must reject UNKNOWN broker state, multiple matches for one intent, or any other ambiguous local/broker mapping.
5. Add tests proving UNKNOWN / duplicate remark matches / ambiguous mapping prevent subsequent new-order execution until reconciliation is resolved.

### NODEB-I2-003 — P0: concrete callback bridge is not actually wired to TGrid EventQueue and drops critical broker events

The project `EventQueue` API exposes:

```python
event_queue.enqueue(event)
```

but `XtQuantCallbackHandler` requires a sink with:

```python
event_sink.put(event)
```

The bridge therefore cannot be connected directly to TGrid's actual single-consumer EventQueue. The callback tests use a custom `_Sink.put()` object and bypass the production event-loop API.

In addition, the concrete handler currently implements these critical callbacks as `pass`:

- `on_disconnected`;
- `on_account_status`;
- `on_order_error`;
- `on_cancel_error`.

That means the most important execution-health/error signals can disappear instead of reaching the single strategy/event thread.

Required:

1. Wire the concrete bridge to the real TGrid EventQueue, either directly via `.enqueue()` or through one narrow audited queue adapter.
2. Tests must instantiate the actual `tgrid.events.EventQueue`, start it, feed concrete fake XtQuant callbacks and prove the immutable broker events are processed on the single worker thread.
3. Add immutable events for disconnect/account-status/order-error/cancel-error; these callbacks may only enqueue data and return.
4. Queue full / stopped / failed conditions must be visible as execution-health failure and must not silently permit new live orders.
5. Keep callback objects free of engine/store/strategy/order-capable references.

### NODEB-I2-004 — P0: daily exposure guard still has restart/crash bypass windows

The direction is improved, but the current hard daily cap is not yet crash-safe.

Problems:

1. `exposure_store` is optional, so a production adapter can still be constructed with only in-memory exposure state.
2. `reconstruct_daily_exposure()` is a public convention, not a mandatory readiness gate. The current tests enable and runtime-confirm an adapter before reconstruction. A fresh process can therefore place a new order without first proving current-day exposure.
3. BUY exposure is persisted only **after** `broker.place_order()` returns. A crash after broker acceptance but before `record_submitted_buy()` creates an unpersisted exposure window.
4. Reconstruction sums only non-terminal managed BUY orders, despite the stated rule that submitted BUY notional is never removed for the trade date. If the missed order has already filled/canceled/rejected before restart, reconstruction can omit it.
5. `roll_day()` uses only lexicographic string ordering. It does not validate an ISO calendar date or bind the reset to a trusted current trading session, so an arbitrary future-looking string/date can reset the hard cap.

Required:

- production/live construction must require a durable exposure store or an equivalently durable execution journal;
- the adapter must have an explicit `exposure_ready/reconciled` state and refuse every new order until startup reconstruction succeeds;
- close the send-before-ledger crash window. A conservative pre-send durable exposure reservation is acceptable; failed/rejected sends do not need to reopen the daily cap;
- reconstruction must be consistent with the chosen "submitted BUY notional" rule, including terminal same-day managed orders, or use the durable intent/order journal as the authoritative submitted-notional source;
- validate `trade_date` as a real ISO date and allow day rollover only from a trusted session/calendar transition, not an arbitrary caller-provided future string;
- add fault-injection for crash after raw broker acceptance but before local exposure persistence, terminal-order restart reconstruction, startup-without-reconstruct, and bogus/future roll-day input.

### NODEB-I2-005 — P1: core ExecutionEngine still allows non-finite capacity/reservation values before durable state mutation

The adapter now rejects non-finite `limit_price`, but `ExecutionEngine._send()` still uses positivity checks such as `< 0` / `<= 0` for `limit_price`, `expected_available_cash` and `cash_amount` without `math.isfinite`.

For a live BUY path, `reserved_cash=float('nan')` or `expected_available_cash=float('nan')` can therefore pass the executor checks and reach `create_intent_with_reservation()` before the LiveBrokerAdapter is called. Node-B's exact-type/fail-closed requirement applies before arithmetic, persistence and broker calls, not only at the final broker adapter.

Required:

- reject NaN / +/-Inf for all price/cash capacity/reservation values in the core executor before creating any intent/reservation;
- add tests proving invalid non-finite inputs cause zero ExecutionStore mutation and zero broker calls.

### NODEB-I2-006 — P1: production bootstrap is still an API convention rather than one audited construction path

The new enable model is safer, but `apply_config_enable(True)`, `confirm_runtime(token)`, exposure reconstruction, EventQueue wiring, bridge construction and policy loading are still independent public steps. There is no single production bootstrap path proving they occur in the safe order.

Iteration 3 should add a narrow live-stack bootstrap/factory (still test/fake only) that binds:

```text
validated runtime config
+ explicit live=false default
+ LiveBrokerPolicy
+ durable DailyExposure store
+ real TGrid EventQueue
+ XtQuantBrokerBridge
+ LiveBrokerAdapter
+ startup recovery/exposure reconciliation
+ separate non-persisted runtime confirmation
+ ExecutionEngine
```

The factory must return a stack that cannot place a new order before startup reconciliation and runtime confirmation are both complete. Tests should use fake XtQuant only. Do not invoke real order/cancel.

## External API verification used by this review

The independent review checked the current official 迅投 XtQuant documentation for the synchronous order/cancel interface and XtOrder/XtTrade structures. The documentation specifies integer order ids at the native interface. This is why NODEB-I2-001 is a real production-contract blocker rather than a stylistic DTO preference.

## Verification required for Iteration 3

DSH must provide SELF_CERTIFIED evidence for:

1. full regression + compileall + capability scan;
2. native-int XtQuant order/cancel id mapping test;
3. UNKNOWN / ambiguous recovery fail-closed tests;
4. actual TGrid EventQueue callback integration tests including disconnect/order-error/cancel-error;
5. durable exposure startup-readiness + crash-window tests;
6. executor NaN/Inf-before-store tests;
7. one production-shaped bootstrap/factory exercised entirely with fake XtQuant;
8. no real order/cancel invocation; `live_trading_allowed=false`;
9. exact implementation/evidence SHA and canonical state consistency.

## Stop condition

After Iteration 3 fixes, DSH must push normally, set state to `AUDIT_READY_PRELIVE`, authorize only `AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`, and STOP.

First real order remains prohibited until:

```text
Audit Node B = PASS
AND
explicit user authorization = YES
```
