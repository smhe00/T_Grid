# Current Task — Gate 5.5 Live Broker Adapter (Pre-Live Only)

## Owner

`DSH (DeepSeek Harness)` — single programming Agent, implementation + self-review allowed.

Self-review must be labelled `SELF_CERTIFIED`; it is not an independent pre-live authorization.

## Status

`AUDIT_READY_PRELIVE (ITERATION 6)`（NODEB-RR5-001..004 remediation complete, SELF_CERTIFIED, awaiting Audit Node B re-review）

## Completion Record — Iteration 6 (SELF_CERTIFIED — 2026-08-15)

Node B Iteration-5 audit (`4310247`) returned `CHANGES_REQUIRED`; all 4 findings closed:

- **NODEB-RR5-001 (P0)**: separate strict Gate-5.5 session-binding parser
  (`parse_live_session_binding`) supporting exactly simulation + live,
  reusing runtime-path/account-fingerprint validation; Gate-1
  simulation-only parser untouched; positive fake live-environment lifecycle
  test (live_qmt_path + live binding entry + exact connect/subscribe) and
  unsupported-env fail-closed.
- **NODEB-RR5-002 (P0)**: public `clear_safe_mode()` and
  `clear_safe_mode_after_reconciliation(results)` removed from the public
  API; the only production SAFE_MODE release is `LiveStack.reconcile_and_resume()`
  which itself runs `reconcile_open_intents()` then the internal
  `_clear_safe_mode_after_reconciliation` (empty-with-open-intents and
  fabricated results rejected).
- **NODEB-RR5-003 (P0)**: low-level `bridge.verify_transport()` is transport
  only and does NOT clear the disconnect latch; order capability is restored
  only by `LiveStack.recover_after_disconnect()` orchestration (queue RUNNING
  -> exact connect -> bound account type/OK verify -> subscribe verify ->
  exposure reconstruct -> authoritative reconciliation -> runtime reconfirm
  -> clear latch); FI proves direct transport verify cannot order.
- **NODEB-RR5-004 (P1)**: canonical metadata now records
  `implementation_commit` + `handoff_parent_commit` distinctly with exact
  GitHub SHAs (no self-referential git_head_commit claim).

Evidence: **952 tests OK** (was 950); compileall 0; capability scan PASS
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
