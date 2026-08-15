# Current Task — TGrid Migration to qmt-execution-core — Iteration 13

## Owner

`DSH (DeepSeek Harness)` — implementation + self-review. All DSH evidence remains `SELF_CERTIFIED` until independent audit.

## Status

`IN_PROGRESS` — the user explicitly resumed migration on 2026-08-16.

Migration specification:

```text
work/gates/QMT_EXECUTION_CORE/TGRID_MIGRATION_REQUEST_ITER13_20260816.md
```

Reviewed public-core baseline:

```text
repository: https://github.com/smhe00/qmt-execution-core
version:    0.2.1
commit:     2e222e16731bd8ce232ffba78c697245472c2094
local:      D:\gitee\miniQMT\qmt-execution-core
architect:  PASS_FOR_MIGRATION
```

This authorization is for **code migration only**. `live_trading_allowed=false`. Do not invoke any real or simulation QMT order/cancel API during this task.

## Architectural objective

TGrid must stop owning reusable QMT execution infrastructure and instead consume the independently audited public execution core.

Public core owns:

```text
execution state machine
journal / mutex / UNKNOWN recovery
BrokerPort lifecycle
QMT status normalization
MiniQMT account/session/callback/runtime safety
strict broker query semantics
```

TGrid retains:

```text
Core / StrategicExtra / T-Lot accounting
SQLite business ledger
TGrid OrderIntent / Reservation / daily exposure
Core-floor / can_use / T+1 / strategy risk
signals / anchor / VWAP / sizing / scheduling
```

## Mandatory Phase A — close the durable-ledger integration seam

Do NOT directly cut over to `MiniQmtRuntime` yet.

The public core generic journal records its own intent/reservation, while TGrid separately requires its SQLite `OrderIntent + Reservation + daily exposure` to commit before any broker side effect. Current public `MiniQmtRuntime.connect()` has no clean project-side lifecycle seam between generic durable intent and `BrokerPort.place_order()`.

Required invariant:

```text
TGrid SQLite OrderIntent + Reservation + pre-send exposure committed
BEFORE
qmt-execution-core reaches actual MiniQMT order_stock side effect
```

Preferred solution: add a broker-neutral, backward-compatible sidecar/lifecycle hook to `qmt-execution-core`, injected through `ExecutionSession` / `MiniQmtRuntime`, with a no-op default. The critical pre-submit hook executes after core durable intent and before broker submit. A pre-cancel hook may be added for TGrid cancel-intent accounting.

Rules:

- hook runs synchronously on the execution thread, never callback thread;
- pre-submit hook failure proves broker submit was not invoked and fails closed;
- no hook may create UNKNOWN -> blind retry;
- do not place durable side effects inside `ExecutionGuard.verify()`;
- do not duplicate/fork `MiniQmtRuntime` implementation inside TGrid;
- no TGrid strategy/Core/T-Lot logic may enter the public repository;
- if the public API changes, bump public-core version and record exact commit;
- re-run public-core full tests, compileall, verifier, installed-wheel verify and Windows mutex probes before TGrid depends on the new public commit.

An alternative design is allowed only if it is demonstrably equivalent or stronger and is documented in the handoff.

## Python / dependency baseline

TGrid currently declares Python `>=3.9`, while public core requires `>=3.11`.

Migration must:

1. move TGrid runtime baseline to Python `>=3.11`;
2. pin qmt-execution-core to an exact reviewed commit in repository dependency metadata;
3. never commit `D:\gitee\miniQMT\qmt-execution-core` as an absolute dependency path;
4. document the local editable-install workflow separately.

## Phase B — TGrid adapter with legacy path retained temporarily

Implement a thin TGrid integration layer that:

- translates TGrid execution decisions to `ExecutionRequest`;
- supplies `SessionEvidence` / `PrecheckEvidence` through a TGrid `ExecutionGuard`;
- performs TGrid durable pre-submit OrderIntent + Reservation + daily-exposure persistence through the approved sidecar seam;
- maps public execution snapshots/normalized observations back to existing TGrid ledger/T-Lot reconciliation;
- preserves native-int broker IDs and callback isolation;
- does not expose QMT raw status values above the public adapter boundary.

Legacy execution code may remain temporarily only for fake/shadow equivalence. Old and new execution authorities must never simultaneously own the same QMT session.

## Phase C — equivalence and cutover

Using fake broker/fake trader only, prove the old and new paths preserve every accepted TGrid safety invariant. Then route production-shaped simulation/shadow construction to the public-core path.

After cutover, TGrid production code must have zero raw production call sites for:

```text
order_stock
order_stock_async
cancel_order_stock
cancel_order_stock_async
```

Those calls must exist only in qmt-execution-core.

The dedicated **fill-during-cancel race -> FILLED** test is required in this migration, not deferred.

## Phase D — remove duplicate reusable infrastructure

Only after equivalence is green, remove/reduce TGrid copies of the generic state machine, execution journal/mutex, generic BrokerPort/recovery, raw XtQuant bridge/status mapping, and generic live-session/callback runtime code.

Do not delete TGrid-specific accounting/risk/strategy code.

## Required evidence

Minimum integrated regression matrix and detailed acceptance criteria are in the migration request. At handoff provide:

- exact final qmt-execution-core version + commit;
- public-core tests/compileall/verifier/wheel verification;
- TGrid full regression + compileall;
- old-module -> public-core/retained-module mapping table;
- fake/shadow equivalence evidence including fill-during-cancel;
- capability scan proving zero TGrid production raw QMT order/cancel call sites;
- dependency/Python compatibility evidence;
- explicit statement that no QMT simulation or real order/cancel was invoked.

## Handoff

When complete:

```text
state = REVIEW_READY
owner = architect
authorized_next = [AUDIT_TGRID_QMT_EXECUTION_CORE_INTEGRATION]
live_trading_allowed = false
```

Do not run integrated QMT simulation orders until the independent integration audit passes and a separate simulation authorization is present.
