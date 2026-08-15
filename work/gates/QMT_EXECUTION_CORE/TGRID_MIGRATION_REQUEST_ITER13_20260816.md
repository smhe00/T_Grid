# TGrid → qmt-execution-core Migration Request — Iteration 13

## Authority

User explicitly resumed the previously paused migration on 2026-08-16.

Target reusable core baseline:

```text
repository: https://github.com/smhe00/qmt-execution-core
version:    0.2.1
commit:     2e222e16731bd8ce232ffba78c697245472c2094
local:      D:\gitee\miniQMT\qmt-execution-core
architect audit: PASS_FOR_MIGRATION
```

`live_trading_allowed=false` remains mandatory. This migration authorization is **code-migration authority only**; it is not simulation-order authority and is not real-money authority.

## Goal

Make `qmt-execution-core` the sole reusable QMT execution-state/runtime authority used by TGrid, while preserving TGrid-specific business semantics:

- CorePosition / StrategicExtra / T-Lot accounting;
- SQLite business ledger;
- TGrid OrderIntent / Reservation / daily exposure;
- Core-floor / can_use / settlement / strategy risk;
- strategy signals, anchor/VWAP logic, sizing and scheduling.

Do **not** copy the public-core implementation back into TGrid.

## Critical integration gap to close first

The audited public core persists its own generic intent/reservation journal, but TGrid also has a durable SQLite `OrderIntent + Reservation + daily exposure` business ledger. The current `MiniQmtRuntime.connect()` constructs `MiniQmtBrokerAdapter + ExecutionSession` internally and exposes no safe project-side lifecycle seam between generic durable intent and the actual broker `place_order()` side effect.

TGrid invariant remains:

```text
TGrid durable OrderIntent + Reservation + pre-send daily exposure
MUST COMMIT BEFORE any broker order_stock side effect.
```

### Required Phase A — reusable sidecar seam

Before TGrid cutover, provide a generic, broker-neutral extension seam in `qmt-execution-core` (preferred) or an equally safe design that meets every invariant below.

Preferred design characteristics:

- backward-compatible no-op default;
- injected through public `ExecutionSession` / `MiniQmtRuntime` API;
- synchronous `before_broker_submit(request)` hook executed:
  1. after core durable intent is committed,
  2. before `BrokerPort.place_order()` is invoked;
- optional synchronous `before_broker_cancel(order_id)` hook executed after core durable cancel-intent persistence and before broker cancel side effect;
- hook execution occurs on the execution thread, never a QMT callback thread;
- pre-submit hook failure proves broker submit was not called and fails closed;
- no hook may create a blind retry path from UNKNOWN;
- hook implementation/source becomes protected by the public-core verification/source manifest where applicable;
- public-core tests cover ordering, crash/failure semantics and no-op backward compatibility;
- bump public-core version for the new public integration API and record the exact resulting commit.

Forbidden shortcuts:

- do not put durable side effects inside `ExecutionGuard.verify()`;
- do not duplicate/fork `MiniQmtRuntime` internals inside TGrid;
- do not let TGrid call raw `order_stock` / `cancel_order_stock` outside the public core;
- do not weaken UNKNOWN, strict-query, account-binding, mutex, journal or live-gate semantics.

If an alternative design is used, document why it is equivalent or stronger before cutover.

## Python/dependency compatibility

Current TGrid declares Python `>=3.9`; qmt-execution-core requires `>=3.11`.

Migration must:

1. move TGrid runtime baseline to Python `>=3.11`;
2. pin the public core to an exact reviewed commit in repository-level dependency metadata;
3. never commit the local absolute path `D:\gitee\miniQMT\qmt-execution-core` as a dependency;
4. document local developer override/editable installation separately.

## Migration phases

### Phase A — public-core integration seam

Implement and validate the generic pre-broker sidecar seam described above if required. Run full public-core suite, compileall, formal verifier, wheel install/verify and Windows mutex probes. No QMT order/cancel invocation.

### Phase B — TGrid adapter, old path retained

Create a thin TGrid adapter layer which:

- translates TGrid execution plans to public `ExecutionRequest`;
- implements TGrid `ExecutionGuard` evidence from existing TGrid risk/account/position/quote checks;
- uses the public sidecar seam to atomically persist existing TGrid SQLite OrderIntent + Reservation + daily exposure before broker submit;
- maps public execution snapshots/normalized broker observations back into the existing TGrid ledger/T-Lot reconciliation path;
- keeps all QMT raw status values below the public adapter boundary;
- preserves native-int broker order IDs;
- keeps callback isolation intact.

Legacy TGrid execution code may remain temporarily for equivalence tests, but the old and new execution authorities must never both own the same live/simulation session simultaneously.

### Phase C — behavioral equivalence + cutover

Using fake broker/fake trader only, demonstrate old-vs-new equivalence for all safety-critical TGrid cases. Then route TGrid production-shaped simulation/shadow construction to the public-core path.

At cutover, TGrid production code must contain **zero direct production call sites** for:

```text
order_stock
order_stock_async
cancel_order_stock
cancel_order_stock_async
```

All such QMT side effects belong to `qmt-execution-core` only.

### Phase D — remove duplicated reusable execution infrastructure

Only after equivalence passes, remove or reduce the TGrid copies of reusable infrastructure such as:

- generic execution state machine;
- execution journal/mutex;
- generic BrokerPort/recovery logic;
- XtQuant raw bridge/status normalization;
- generic live-session/bootstrap mechanics;
- generic callback/event-queue execution infrastructure.

Do **not** delete TGrid-specific ledger/risk/strategy/accounting functionality.

## Required regression matrix

Minimum integrated fake/refinement coverage:

1. submit accepted;
2. definitive submit rejected;
3. submit ambiguous / UNKNOWN, no blind resend;
4. zero-match and duplicate-match recovery fail closed;
5. working;
6. partial fill;
7. full fill;
8. cancel pending;
9. cancel rejected + authoritative re-query;
10. partial fill + cancel;
11. **dedicated fill-during-cancel race → FILLED**;
12. cancel confirmed;
13. restart from active order;
14. restart from cancel pending;
15. broker query `None` ambiguous, not empty;
16. unknown/unrecognized QMT raw status → UNKNOWN;
17. disconnect immediately blocks new orders;
18. reconnect without full reconcile remains blocked;
19. full reconnect/reconcile restores only when every gate passes;
20. Core floor/can_use/T+1 constraints preserved;
21. TGrid pre-send Reservation + daily exposure committed before broker side effect;
22. crash after TGrid reservation but before broker return remains recoverable/fail-closed;
23. duplicate client_order_id/order_remark remains idempotent across cycles;
24. kill switch blocks new orders while query/cancel semantics remain safe;
25. QMT-path cross-process runtime mutex remains effective.

## Evidence required before handoff

- public-core exact version/commit used after any Phase-A API extension;
- public-core full tests + compileall + verifier + wheel verify;
- TGrid full regression suite + compileall;
- dependency/import checks;
- capability scan proving no TGrid raw QMT order/cancel production call sites after cutover;
- mapping table: old TGrid module/function → public-core component or retained TGrid-specific component;
- fake/shadow equivalence evidence;
- explicit statement: no real or simulation QMT order/cancel invoked during migration;
- DSH report labelled `SELF_CERTIFIED`.

## Handoff

When complete:

```text
state = REVIEW_READY
owner = architect
authorized_next = [AUDIT_TGRID_QMT_EXECUTION_CORE_INTEGRATION]
live_trading_allowed = false
```

Do not run integrated QMT simulation orders until the independent integration audit passes and a separate simulation authorization is present.
