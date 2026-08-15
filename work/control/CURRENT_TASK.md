# Current Task — Gate 5.5 PASS_PRELIVE + Gate 6 Simulation Verification

## Owner

`DSH (DeepSeek Harness)` — single programming Agent, implementation + self-review allowed.

Self-review must be labelled `SELF_CERTIFIED`; it is not an independent pre-live authorization.

## Status

`NODE_B PASS_PRELIVE` — Gate 5.5 pre-live capability independently accepted (`e252847`).
Gate 6 **simulation** verification executed (user-authorized, QMT sim client, 2026-08-15 21:29).
Real-money Gate 6/7 remain BLOCKED until explicit user authorization.

## Completion Record — Node B PASS_PRELIVE (2026-08-15)

- **NODEB-RR6-001/002/003** all PASS; Node B final verdict `PASS_PRELIVE`
  (`work/gates/GATE_5_5/NODE_B_FINAL_PASS_PRELIVE_20260815.md`).
- `PASS_PRELIVE` = adapter + safety boundary accepted for the next gated phase;
  NOT authorization to place a real order.

## Gate 6 Simulation Verification (SELF_CERTIFIED — 2026-08-15 21:29)

User explicitly authorized Gate 6 on the QMT **simulation** trading client
(already started). `scripts/gate6_sim_live.py` executed the full pre-live loop:

1. production `build_live_session(simulation)` — connect/discover/subscribe OK,
   bridge constants SECURITY_ACCOUNT=2 / ACCOUNT_STATUS_OK=0;
2. mandatory recovery + runtime confirmation passed;
3. ONE tiny BUY: 510300.SH qty=100 @ 4.726 (caps: 200 qty / 5000 cash / allowlist /
   exposure gate / EventQueue health);
4. real `order_stock` returned native int broker id `1098907651`;
5. polled to **REJECTED** (sim client rejected the order — Saturday, outside
   trading hours); broker reconcile REJECTED / 0 filled; exposure 472.6 booked
   pre-send;
6. evidence: `work/reports/gate6-sim/gate6-sim-2026-08-15.json` (sanitized).

**Honest limitation**: the sim client rejected the order outside trading hours,
so the FILL and CANCEL paths were NOT exercised. A trading-hours rerun is
required to complete Gate 6 simulation verification (real fill, partial fill,
cancel+re-query, T+1/can_use checks).

## Remaining / BLOCKED

- Real-money Gate 6/7: BLOCKED until explicit user authorization (`f` is never
  trading authorization). `live_trading_allowed=false` remains mandatory.
- Monitor job keeps polling `tgrid-github/main` for any further audit pushes.

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
