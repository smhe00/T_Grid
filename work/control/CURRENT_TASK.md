# Current Task — Gate 5.5 Live Broker Adapter (Pre-Live Only)

## Owner

`DSH (DeepSeek Harness)` — single programming Agent, implementation + self-review allowed.

Self-review must be labelled `SELF_CERTIFIED`; it is not an independent pre-live authorization.

## Status

`AUDIT_READY_PRELIVE (ITERATION 4)`（NODEB-RR-001..006 remediation complete, SELF_CERTIFIED, awaiting Audit Node B re-review）

## Completion Record — Iteration 4 (SELF_CERTIFIED — 2026-08-15)

Node B Iteration-3 reference-conformance audit (`3b0d53f`) returned
`CHANGES_REQUIRED`; all 6 findings closed (baseline = reverse_repo pinned
`c9ecc701d9b1c47d6a8d03539b482368741204a3`):

- **NODEB-RR-001 (P0)**: production `build_live_session()` factory reuses
  Gate-1/reverse_repo account-env-QMT-path binding (environment match, QMT-path
  fingerprint, strict account infos/statuses queries, exactly one normal
  securities account matching the fingerprint, opaque-bound subscribe); order
  capability unreachable on failure/ambiguity (FI tests).
- **NODEB-RR-002 (P0)**: strict-query bounded-retry contract ported to the
  bridge — None/exception retried 3x then `BrokerQueryAmbiguous`; `None` never
  means empty success; `query_order` prefers native `query_stock_order` with
  unique-match fallback; FI: None, transient→success, persistent, empty-list
  success, duplicate match.
- **NODEB-RR-003 (P0)**: `LiveStack.activate()` recovery is MANDATORY (no None
  path); UNMATCHED/INTENT_ONLY/UNKNOWN/ambiguous block activation and engage
  SAFE_MODE; `reconcile_and_resume()` is the reconciliation-driven SAFE_MODE
  release (clear only after successful authoritative reconciliation);
  restart tests prove activation cannot skip recovery or flip a flag.
- **NODEB-RR-004 (P0)**: concrete `SqliteExposureStore` durable journal built
  by the production bootstrap (callers cannot substitute an in-memory fake);
  `roll_day` requires `session_date` on the reset path and it must equal the
  new date; reconstruction not keyed on raw QMT `order_time` format; restart
  tests use the concrete durable store.
- **NODEB-RR-005 (P0)**: `execution_healthy` reads the ACTUAL EventQueue
  lifecycle (FAILED/STOPPING/STOPPED reject orders even without a next
  callback); `on_disconnected` marks unhealthy immediately; `mark_connected()`
  explicit recovery; tests: worker-failure-without-callback, disconnect-then-
  immediate-order rejected, explicit recovery restores.
- **NODEB-RR-006 (P1)**: fixed `git_base_commit` SHA typo
  (`cb7aeb6006…` not `cb7aeb6606…`); recorded pinned reference repo/commit.

Evidence: **943 tests OK** (was 929); compileall 0; capability scan PASS
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
