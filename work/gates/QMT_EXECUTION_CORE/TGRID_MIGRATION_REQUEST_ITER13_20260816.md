# TGrid → qmt-execution-core Migration Request — Iteration 13

## Authority

User explicitly resumed the previously paused migration on 2026-08-16.

Target reusable core baseline entering this iteration:

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

---

## Phase A0 — Python 3.9 compatibility gate (MUST RUN FIRST)

TGrid currently declares Python `>=3.9`. qmt-execution-core 0.2.1 declares `>=3.11`, but independent source inspection has not identified a known 3.11-only semantic dependency. Therefore **do not raise TGrid to 3.11 by default**.

First establish the real compatibility boundary from evidence.

### Required Python 3.9 checks on qmt-execution-core

Use the public-core local checkout:

```text
D:\gitee\miniQMT\qmt-execution-core
```

and verify the exact starting baseline `2e222e16731bd8ce232ffba78c697245472c2094` before changes.

On a real **Windows Python 3.9** interpreter, run at minimum:

1. source import and full `pytest`;
2. `python -m compileall -q src tests`;
3. `qmt-execution-core verify`;
4. wheel build;
5. install wheel into a clean Python 3.9 venv;
6. run installed-wheel verifier outside the checkout;
7. same-process repeated ExecutionMutex owner cycles;
8. cross-process ExecutionMutex contention/acquire/release;
9. QMT userdata runtime-mutex contention test;
10. if the installed MiniQMT/xtquant environment is usable from Python 3.9, perform the same **read-only** MiniQMT smoke: connect/discover/subscribe/query asset/positions/orders/trades/clean close.

Explicitly scan for any actual Python >3.9 dependency, including syntax, stdlib APIs and packaging requirements. Do not infer incompatibility from the current `requires-python` declaration alone.

### If Python 3.9 PASS

Then update the public core as a compatibility release:

```text
version: 0.2.2
requires-python: >=3.9
CI matrix: 3.9, 3.11, 3.12
```

Requirements:

- public API semantics unchanged except for compatibility/integration changes explicitly authorized below;
- all existing 0.2.1 safety tests remain green;
- GitHub CI must include Python 3.9;
- Windows Python 3.9 evidence must be recorded because Linux CI cannot substitute for `msvcrt` verification;
- installed-wheel verifier must pass on Python 3.9;
- if read-only MiniQMT smoke can run on Python 3.9, it must pass with **zero order/cancel calls**.

TGrid should then remain `requires-python >=3.9`.

### If Python 3.9 FAIL

Do not immediately raise TGrid to 3.11. Record the **exact failing feature/API/dependency** and determine the minimum real compatible Python version. Only then may the TGrid baseline be changed, and that decision must be explicit in the handoff.

If a Python 3.9 interpreter is unavailable locally, do not silently declare PASS. Add 3.9 CI/static evidence where possible and report the missing Windows-runtime evidence for architect review.

---

## Critical integration gap to close after A0

The audited public core persists its own generic intent/reservation journal, but TGrid also has a durable SQLite `OrderIntent + Reservation + daily exposure` business ledger. The current `MiniQmtRuntime.connect()` constructs `MiniQmtBrokerAdapter + ExecutionSession` internally and exposes no safe project-side lifecycle seam between generic durable intent and the actual broker `place_order()` side effect.

TGrid invariant remains:

```text
TGrid durable OrderIntent + Reservation + pre-send daily exposure
MUST COMMIT BEFORE any broker order_stock side effect.
```

### Phase A1 — reusable sidecar seam

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
- do not put durable side effects inside `ExecutionGuard.verify()`;
- no TGrid strategy/Core/T-Lot logic may enter the public repository;
- no TGrid raw QMT call may bypass the public core;
- hook implementation/source becomes protected by the public-core source manifest where applicable;
- tests cover exact ordering, hook failure before broker side effect, crash/failure semantics, idempotency and no-op backward compatibility.

If A0 passes and A1 changes the public API in the same cycle, use **one new public-core version** (normally `0.2.2`) and record the final exact commit after all public-core changes and verification.

Forbidden shortcuts:

- do not put durable side effects inside `ExecutionGuard.verify()`;
- do not duplicate/fork `MiniQmtRuntime` internals inside TGrid;
- do not let TGrid call raw `order_stock` / `cancel_order_stock` outside the public core;
- do not weaken UNKNOWN, strict-query, account-binding, mutex, journal or live-gate semantics.

If an alternative design is used, document why it is equivalent or stronger before cutover.

---

## Dependency policy

After the public-core Phase A work is complete:

1. pin the public core to the exact reviewed commit in repository-level dependency metadata;
2. never commit the local absolute path `D:\gitee\miniQMT\qmt-execution-core` as a dependency;
3. document the local editable-install workflow separately;
4. keep TGrid at Python `>=3.9` if A0 proves 3.9 compatibility; otherwise use the minimum version proven necessary by evidence.

---

## Phase B — TGrid adapter, old path retained

Create a thin TGrid adapter layer which:

- translates TGrid execution plans to public `ExecutionRequest`;
- implements TGrid `ExecutionGuard` evidence from existing TGrid risk/account/position/quote checks;
- uses the public sidecar seam to durably persist existing TGrid SQLite OrderIntent + Reservation + daily exposure before broker submit;
- maps public execution snapshots/normalized broker observations back into the existing TGrid ledger/T-Lot reconciliation path;
- keeps all QMT raw status values below the public adapter boundary;
- preserves native-int broker order IDs;
- keeps callback isolation intact.

Legacy TGrid execution code may remain temporarily for equivalence tests, but the old and new execution authorities must never both own the same live/simulation session simultaneously.

## Phase C — behavioral equivalence + cutover

Using fake broker/fake trader only, demonstrate old-vs-new equivalence for all safety-critical TGrid cases. Then route TGrid production-shaped simulation/shadow construction to the public-core path.

At cutover, TGrid production code must contain **zero direct production call sites** for:

```text
order_stock
order_stock_async
cancel_order_stock
cancel_order_stock_async
```

All such QMT side effects belong to `qmt-execution-core` only.

## Phase D — remove duplicated reusable execution infrastructure

Only after equivalence passes, remove or reduce the TGrid copies of reusable infrastructure such as:

- generic execution state machine;
- execution journal/mutex;
- generic BrokerPort/recovery logic;
- XtQuant raw bridge/status normalization;
- generic live-session/bootstrap mechanics;
- generic callback/event-queue execution infrastructure.

Do **not** delete TGrid-specific ledger/risk/strategy/accounting functionality.

---

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
22. pre-submit sidecar failure proves broker side effect count remains zero;
23. crash after TGrid reservation but before broker return remains recoverable/fail-closed;
24. duplicate client_order_id/order_remark remains idempotent across cycles;
25. kill switch blocks new orders while query/cancel semantics remain safe;
26. QMT-path cross-process runtime mutex remains effective;
27. Python 3.9 public-core compatibility evidence, if 3.9 is retained.

## Evidence required before handoff

- exact final public-core version + commit;
- Python compatibility decision with concrete evidence;
- public-core full tests + compileall + verifier + wheel verify;
- Windows mutex regression evidence on the minimum supported Python version;
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
