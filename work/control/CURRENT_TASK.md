# Current Task — Audit Node B Iteration 3 Pre-Live Fixes

## Owner

`DSH (DeepSeek Harness)` — single programming Agent, implementation + self-review allowed.

Self-review must be labelled `SELF_CERTIFIED`; it is not an independent pre-live authorization.

## Status

`CHANGES_REQUIRED` — Audit Node B Iteration 2 did not PASS.

## Audit Source

Read and implement only the remaining findings in:

```text
work/gates/GATE_5_5/NODE_B_REVIEW_ITER2_20260815.md
```

Audit target:

```text
9ef60c75bd72db94f1cfda919965531c4557cb18
```

Reviewed Iteration-2 implementation:

```text
b4d121c00f4c06a71ba5cb134661eac1a686c3cb
```

Gate 5 remains independently PASS. Gate 6 / Gate 7 remain BLOCKED. `live_trading_allowed=false` remains mandatory.

## Accepted Work — Do Not Redo

Retain these Iteration-2 improvements unless a remaining fix requires a local adjustment:

- shared `BrokerPort` + typed broker DTO architecture;
- `ExecutionEngine` broker-type independence and simulation-hook separation;
- one concrete `XtQuantBrokerBridge` + bridge-only capability allowlist;
- end-to-end fake chain `ExecutionEngine -> LiveBrokerAdapter -> XtQuantBrokerBridge`;
- durable OrderIntent + Reservation-before-send and duplicate client-key protection;
- corrected kill-switch semantics: new orders blocked, cancel/query/cancel-all available;
- legacy reconciliation Core guard;
- adapter policy / limit-price NaN/Inf checks;
- removal of generic arbitrary broker callback registration;
- no real order/cancel invocation.

## Required Work — Iteration 3 Only

### 1. Native XtQuant order-id contract

- fake XtQuant `order_stock()` must return a positive `int`, matching the official API;
- concrete `cancel_order_stock(account, order_id)` must receive an `int`;
- if TGrid persists IDs as strings, perform one explicit validated bridge conversion without losing identity;
- add exact mapping tests for order / query / trade / cancel ids.

### 2. UNKNOWN / ambiguous broker state must fail closed

- `poll_order()` must not silently treat broker `UNKNOWN` as local `SUBMITTED`;
- keep reservations while unresolved;
- raise or return an explicit reconciliation/safe-mode signal that blocks further live execution;
- startup recovery must fail closed on UNKNOWN broker states, multiple broker matches for one intent, duplicate/ambiguous remark matches and query ambiguity;
- add integration tests proving new orders remain blocked until explicit reconciliation resolution.

### 3. Wire callbacks to the real TGrid EventQueue

- bridge must connect to `tgrid.events.EventQueue` (`enqueue`) directly or through one audited narrow adapter;
- tests must run the real EventQueue worker and prove callback events are consumed on the single worker thread;
- convert and enqueue immutable events for stock order, stock trade, disconnect, account status, order error and cancel error;
- callback must retain no engine/store/strategy/order-capable adapter refs;
- queue FULL/STOPPED/FAILED must become visible execution-health failure and must not silently allow new live orders.

### 4. Make daily exposure crash-safe and mandatory before readiness

- production-shaped live construction requires durable exposure/journal state;
- add `exposure_ready` or equivalent: no new order until startup exposure reconstruction succeeds;
- close crash window between broker acceptance and local daily-exposure persistence (conservative pre-send durable accounting is acceptable);
- reconstruction must honor the stated submitted-BUY-notional rule including terminal same-day managed orders, or derive from durable execution/order journal;
- strict ISO `trade_date` validation;
- day rollover only from a trusted session/calendar transition, not arbitrary caller strings;
- fault-injection tests: crash-after-accept-before-persist, terminal-order restart, no-reconstruct startup, bogus/future day-roll.

### 5. Executor non-finite validation before durable mutation

- `ExecutionEngine` must reject NaN / +/-Inf in price, expected cash and reserved cash before any intent/reservation is written;
- tests: zero store mutation + zero broker call.

### 6. One production-shaped bootstrap/factory

Add one narrow construction path, exercised only with fake XtQuant, that binds in safe order:

```text
validated config
-> live default OFF
-> policy/allowlist/hard limits
-> durable exposure store
-> real TGrid EventQueue
-> XtQuantBrokerBridge
-> LiveBrokerAdapter
-> startup recovery + exposure reconciliation
-> explicit non-persisted runtime confirmation
-> ExecutionEngine
```

The returned stack must not be able to send a new order before startup reconciliation and runtime confirmation are complete.

## Required Verification

- full unit regression;
- `python -m compileall -q src tests scripts`;
- capability scan: only the exact audited bridge contains direct XtQuant order/cancel calls;
- native-int order-id test;
- UNKNOWN / ambiguous fail-closed tests;
- real EventQueue callback tests;
- exposure crash/restart/readiness tests;
- executor NaN/Inf-before-store tests;
- bootstrap/factory integration test with fake XtQuant only;
- no real order/cancel invocation;
- exact implementation SHA / test count / canonical metadata consistency.

## Forbidden

- no real order invocation;
- no real cancel invocation;
- no Gate 6 tiny-capital run;
- no live-soak claim;
- do not set `live_trading_allowed=true`;
- no force push/history rewrite;
- no account/balance/holding/port/userdata-path/secrets in committed evidence.

## Stop / Handoff

When complete:

1. push normally to `main`;
2. set `state=AUDIT_READY_PRELIVE`;
3. record exact implementation/evidence SHA(s) and exact test count;
4. authorize only `AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`;
5. STOP.

First real order remains prohibited until:

```text
Audit Node B = PASS
AND
explicit user authorization = YES
```
