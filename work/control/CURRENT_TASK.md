# Current Task — Gate 5.5 Live Broker Adapter (Pre-Live Only)

## Owner

`DSH (DeepSeek Harness)` — single programming Agent, implementation + self-review allowed.

Self-review must be labelled `SELF_CERTIFIED`; it is not an independent pre-live authorization.

## Status

`AUDIT_READY_PRELIVE (ITERATION 2)`（NODEB-001..007 remediation complete, SELF_CERTIFIED, awaiting Audit Node B re-review）

## Completion Record — Iteration 2 (SELF_CERTIFIED — 2026-08-15)

Node B audit (`0f8e0a19`) returned `CHANGES_REQUIRED`; all 7 findings closed:

- **NODEB-001 (P0)**: `BrokerPort` shared port + typed DTOs; `ExecutionEngine`
  no longer requires SimBroker or `tick_order/get_order`; `SimulationDriver`
  owns deterministic scripts; `XtQuantBrokerBridge` is the repository's ONLY
  `order_stock`/`cancel_order_stock` call site (capability scan allowlist: 2
  inside bridge, 0 outside); raw XtQuant objects mapped to TGrid DTOs; tests
  use fakes only.
- **NODEB-002 (P0)**: full chain `ExecutionEngine -> LiveBrokerAdapter ->
  XtQuantBrokerBridge(FakeTrader)` integration tests (idempotency, reservation
  before send, crash-before-send no blind resend, crash-after-accept recovery,
  partial fill reservation semantics, timeout cancel->re-query->reconcile,
  unmatched order -> SAFE_MODE, query failure/ambiguous -> fail closed).
- **NODEB-003 (P0)**: kill switch blocks NEW orders only; cancel /
  `cancel_all_managed_open_orders` / re-query remain available (tests prove).
- **NODEB-004 (P0)**: generic `register_callback` removed; bridge-owned
  `XtQuantCallbackHandler` converts payloads to immutable events and only
  `event_sink.put(event)`; no engine/store/adapter references held.
- **NODEB-005 (P0)**: `DailyExposureLedger` bound to trade_date, durable
  store, startup reconstruction from managed broker orders, monotonic-only
  `roll_day`, no public unconditional reset; restart/same-day-reset tests.
- **NODEB-006 (P0)**: `math.isfinite` rejects NaN/±Inf in policy values and
  limit_price before any arithmetic/broker call (tests included).
- **NODEB-007 (P1)**: enable flags no longer constructor fields; config enable
  via trusted `apply_config_enable(flag)`; token-gated `confirm_runtime(token)`;
  restart always resets runtime-confirmed; callbacks structurally cannot
  enable/confirm.

Evidence: **906 tests OK** (was 865); compileall 0; capability scan PASS
(2 allowlisted bridge call sites, 0 outside); no real order/cancel invoked.
Report: `work/gates/GATE_5_5/CLAUDE_REPORT.md`.

Gate 5 passed independent Audit Node A on 2026-08-15. Gate 6 / Gate 7 remain blocked. `live_trading_allowed=false` remains mandatory.

## Source of Authorization

Read and comply with:

```text
work/gates/GATE_5/NODE_A_FINAL_REVIEW_20260815.md
```

Audit target:

```text
df1cbb53471d8f765c89c4bc644323d5839d0dd6
```

Accepted Gate-5 implementation commit:

```text
5a2e2fd32e21328badd1ceb2c92b973436c4c95a
```

## Objective

Implement Gate 5.5: the real broker execution adapter and its pre-live safety boundary, while **never invoking a real order or real cancel** during this task.

Target architecture:

```text
ExecutionEngine
    -> LiveBrokerAdapter
    -> XtQuantTrader
```

The adapter may contain the broker capability needed for later live execution, but this task ends before the first real invocation.

## Mandatory Requirements

1. `live_trading` defaults false and cannot be enabled implicitly.
2. A second explicit runtime confirmation is required in addition to configuration before broker execution is permitted.
3. Explicit symbol allowlist.
4. Hard per-order quantity limit.
5. Hard per-order and/or per-day cash exposure limit.
6. Kill switch / emergency disable path.
7. Broker callbacks may only enqueue events; callbacks must not directly mutate T-Lots, position state, reservations, DB strategy state, or issue new orders.
8. Reuse Gate-4 idempotent OrderIntent + Reservation-before-send semantics.
9. Partial fills must be modeled explicitly.
10. Timeout path must be `cancel request -> broker re-query -> reconcile`; cancellation acknowledgement must never be interpreted as proof of zero fill.
11. Order/trade reconciliation and restart/crash recovery must be deterministic and fail closed.
12. Exact-type validation must occur before arithmetic or broker calls.
13. No force push / history rewrite.
14. Do not commit account identifiers, balances, holdings, ports, userdata paths, secrets or local runtime configs.

## Mandatory Carry-Forward Fix — NODEB-P0-001

Fix the legacy reconciliation Core mismatch guard before Node B review.

Current issue: `_load_reconciliation_state()` discards an optional legacy `core_qty` before `_check_core_authority()` can inspect it. Therefore a legacy file containing a Core different from `SymbolConfig.core_qty` is silently ignored instead of failing closed.

Required resolution:

- either reject `core_qty` as an unexpected reconciliation-state field; or
- preserve it, require exact equality with `SymbolConfig.core_qty`, then discard it.

Add a loader-to-runner test proving a mismatched legacy Core fails closed before any broker execution capability can be invoked.

## Forbidden During Gate 5.5

- no real order invocation;
- no real cancel invocation;
- no enabling `live_trading_allowed` in canonical state;
- no Gate 6 tiny-capital run;
- no production/live soak claim;
- no bypass of Node B.

## Required Self-Certified Evidence

- full unit regression;
- compileall;
- capability scan identifying every real broker order/cancel call site introduced by Gate 5.5;
- tests for double enable/confirmation;
- allowlist and hard-limit tests;
- callback isolation tests;
- idempotency/reservation tests against the live adapter boundary using mocks/fakes only;
- partial fill / cancel / re-query / uncertain-state tests;
- restart/recovery tests;
- NODEB-P0-001 integration test;
- proof that no real order/cancel was invoked while producing the evidence.

## Stop / Handoff — Audit Node B

When implementation is complete:

1. push normally to GitHub `main`;
2. set canonical state to `AUDIT_READY_PRELIVE`;
3. record exact implementation commit(s), test counts and capability call sites;
4. authorize only `AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`;
5. STOP.

The first real order is prohibited until:

```text
Audit Node B = PASS
AND
explicit user authorization = YES
```
