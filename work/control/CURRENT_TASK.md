# Current Task — Audit Node B Iteration 2 Pre-Live Fixes

## Owner

`DSH (DeepSeek Harness)` — single implementation/self-review agent.

Self-review must remain `SELF_CERTIFIED`; it is not authorization for a real broker order.

## Status

`CHANGES_REQUIRED` — Audit Node B Iteration 1 did not pass.

Gate 5 remains independently PASS. Gate 6 / Gate 7 remain BLOCKED. `live_trading_allowed=false` remains mandatory.

## Review source

Implement only the findings in:

```text
work/gates/GATE_5_5/NODE_B_REVIEW_20260815.md
```

Audit target:

```text
9319465e5b2aa38a2a713dca3e25b93c69d4412f
```

Gate-5.5 implementation commit under review:

```text
249aa061842eac114d224b384164541619628edc
```

## Accepted work — retain

- Gate 5 / Node A PASS remains valid.
- NODEB-P0-001 legacy Core mismatch guard is accepted.
- live flags default false in the adapter scaffold.
- explicit allowlist and basic per-order qty/cash policy structure.
- no real order/cancel was invoked while producing Gate-5.5 evidence.

## Required fixes

1. **Connect the actual pre-live execution architecture**
   - refactor away the `ExecutionEngine -> SimBroker only` type restriction;
   - define a shared broker execution port/DTO contract;
   - isolate simulation-only `tick_order/get_order/script` behavior from production execution;
   - implement one concrete XtQuant bridge mapping TGrid order/cancel/query operations to the real XtQuant API;
   - keep all real invocations unexecuted during this task.

2. **Prove Reservation/Idempotency/Recovery end to end**
   - integration-test `ExecutionEngine -> LiveBrokerAdapter -> fake XtQuant bridge`;
   - intent + reservation before send;
   - duplicate key no duplicate broker send;
   - pre-send crash, post-send/pre-persist crash, unmatched broker order and ambiguous query all fail closed/reconcile deterministically;
   - partial fill and cancel->requery semantics must run through this integrated path.

3. **Fix emergency kill-switch semantics**
   - block new order/amend/reprice;
   - allow query/recovery;
   - allow cancellation of existing managed open orders under kill switch;
   - preferably add cancel-all-managed + re-query/reconcile.

4. **Make callback isolation structural**
   - remove generic arbitrary callback execution as the broker callback boundary;
   - concrete broker callbacks convert payload -> data-only event -> `event_queue.put(event)` only;
   - no strategy/store/DB/order-capable reference in callback objects.

5. **Make daily exposure hard across restart**
   - no public unrestricted same-day reset;
   - bind exposure to validated trading day;
   - reconstruct current-day exposure on restart from durable local/broker state before enabling new orders;
   - define deterministic exposure semantics under cancel/reject/partial fill.

6. **Close numeric-limit bypass**
   - reject NaN/+Inf/-Inf for policy cash limits and order prices before arithmetic/broker calls.

7. **Harden production double-enable**
   - config enable from trusted validated runtime config, default false;
   - separate non-persistent runtime confirmation required after each restart;
   - callbacks/strategy event handlers cannot self-enable execution.

8. **Capability scan semantics**
   - after a concrete XtQuant bridge exists, scan should allowlist only the exact audited real order/cancel call sites in that bridge;
   - any additional direct call elsewhere => fail.

## Required self-certified verification

- full unittest regression and compileall;
- capability scan with exact allowlisted concrete XtQuant call sites;
- integrated pre-live execution tests using a fake/raw-XtQuant surface only;
- kill-switch allows cancel/re-query while blocking new orders;
- malicious/arbitrary callback path cannot mutate engine/store/order state directly;
- restart cannot reset daily exposure;
- NaN/Inf fail-closed tests;
- runtime confirmation resets false on restart;
- NODEB-P0-001 retained;
- no real order/cancel invocation;
- no sensitive local runtime artifacts committed.

## Forbidden

- no real order invocation;
- no real cancel invocation;
- no Gate 6 tiny-capital run;
- no `live_trading_allowed=true` in canonical state;
- no bypass of Audit Node B.

## Stop / handoff

When complete, push to `main`, set `state=AUDIT_READY_PRELIVE`, record exact implementation/evidence SHA(s), authorize only `AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`, and STOP.
