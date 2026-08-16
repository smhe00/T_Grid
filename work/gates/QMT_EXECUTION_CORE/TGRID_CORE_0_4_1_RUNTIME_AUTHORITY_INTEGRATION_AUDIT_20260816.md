# TGrid → Core 0.4.1 Runtime Authority Integration — Independent Audit — 2026-08-16

## Verdict

`PASS_PRELIVE`.

Audit target:

```text
TGrid implementation: 1790812bb7ef7f6ceb35b2dcc18da49dabfc7451
TGrid parent/control baseline: 889f3f6aa8cf89ea08a649a448ecb554c17af5e8
Core production baseline: smhe00/qmt-execution-core@a68572decb799bcbbf1b2892fcf58ac321ce9636
```

Iteration 16 Core 0.4.1 Runtime Authority integration is accepted for the next gated phase. `live_trading_allowed=false`. This audit does not authorize any real or simulation QMT order/cancel.

## Findings

### P1-1 — Exact reviewed Core pin — PASS

`pyproject.toml` pins `qmt-execution-core` to the exact reviewed and merged Core 0.4.1 SHA:

```text
a68572decb799bcbbf1b2892fcf58ac321ce9636
```

No branch/tag/latest dependency is used.

### P1-2 — Production composition is Authority-only — PASS

`src/tgrid/integrations/qec_runtime.py` exposes no production `coordination_path`, `authority_root`, `coordinator`, or `authority` parameter. `build_qec_runtime()` builds `MiniQmtRuntimeConfig(runtime_lock_mode="shared")` without caller-selected coordination state and calls `MiniQmtRuntime.connect(...)` with neither `coordinator=` nor `authority=`.

Therefore production shared mode inherits Core 0.4.1's canonical account Runtime Authority path and DB identity verification rather than creating a TGrid-specific coordination domain.

Low-level injection remains confined to isolated tests and is not part of the production builder.

### P1-3 — Old DB-selection surface removed — PASS

Both Gate-6 runners no longer expose `--coordination-db`. Repository code search on the reviewed default branch finds no `coordination_path`, `authority_root`, `coordination-db`, `coordinator=`, or `authority=` production route.

No TGrid-specific replacement Authority root/path knob was introduced.

### P1-4 — Explicit bootstrap / fail-closed startup — PASS

The TGrid production builder does not bootstrap Runtime Authority. Core 0.4.1 resolves Authority with `bootstrap=False` before constructing/connecting the XtQuant trader in shared mode.

Consequently:

- missing/corrupt/mismatched Authority fails startup;
- recreated/mismatched certified DB fails startup;
- no replacement Authority/DB is silently adopted;
- order/cancel capability is not reached before Authority/DB identity verification.

The documented first-use lifecycle remains:

```text
qmt-execution-core bootstrap-authority --binding <binding-file>
        ↓
start TGrid shared strategy runtime
```

### P1-5 — Core/TGrid responsibility split and ordering — PASS

Core remains authoritative for coordination-domain identity, `(account_key, symbol)` claims, shared BUY cash reservation and execution finality. TGrid retains its business ledger and project risk semantics.

The accepted submit ordering remains:

```text
Core durable execution intent
→ Core symbol/cash coordination COMMIT
→ TGrid durable sidecar COMMIT
→ broker submit
```

Conflict paths stop at Core coordination before the TGrid sidecar and broker.

## Concurrency / failure semantics retained

The reviewed tests preserve the Iter16 functional invariants:

- three independent runtimes on one account, distinct symbols, can all reach WORKING;
- same account/same symbol second writer is rejected before broker submit;
- shared cash reservation prevents overcommit;
- different accounts remain isolated;
- UNKNOWN / CANCEL_REJECTED / unresolved FAILED do not grant resend/release permission;
- FAILED + unresolved broker reality maps to QUARANTINED and retains symbol claim + Core cash + TGrid business reservation;
- unrelated symbol may proceed if remaining cash permits;
- bounded MiniQMT session-id leasing remains intact;
- old hash-bound journals are rejected rather than silently migrated.

## Raw broker authority — PASS

Repository code search on the reviewed default branch finds no direct `order_stock(` or `cancel_order_stock(` call in TGrid production code. The public Core runtime remains the execution side-effect authority.

## Evidence classification

DSH reports the following execution evidence as `SELF_CERTIFIED`:

```text
full TGrid pytest                         : 915 passed, 17 subtests
compileall -q src tests scripts          : exit 0
raw QMT capability scan                  : zero production call sites
Gate-6 import/--help                     : PASS; --coordination-db absent
installed pinned qmt-execution-core verify: PASS
Core formal gate                         : 433,489 states / 4,461,994 edges / 0 violations
Python 3.9 AST parse                     : NONE failed
```

GitHub exposes no independent CI status/checks for TGrid implementation commit `1790812b...`; therefore the execution counts remain self-certified rather than independently re-run evidence. Independent audit directly inspected the production composition, dependency pin, Core connection ordering, startup-failure tests, concurrency/cash/quarantine tests, and repository capability surface. This is sufficient for the code-level `PASS_PRELIVE` verdict.

## Non-blocking observations

1. `tests/unit/test_qec_iter16.py` still has an opening docstring referring to Core 0.4 / `acf20d9`; the actual imports, production pin and final integration tests target Core 0.4.1. This is editorial debt only and does not alter runtime semantics.
2. The implementation handoff left `WORKFLOW_STATE.yaml: implementation_commit` blank. The audit control update must bind the reviewed implementation explicitly to `1790812bb7ef7f6ceb35b2dcc18da49dabfc7451`.

## Authorization boundary

`PASS_PRELIVE` means the Core 0.4.1 Authority integration is accepted. It is not permission to place an order in QMT simulation or live mode.

The shorthand `f` means fetch/audit only and does not authorize trading side effects.

Until the user explicitly authorizes the next Gate-6 execution step:

```text
live_trading_allowed = false
simulation QMT order/cancel = NOT AUTHORIZED
real QMT order/cancel       = NOT AUTHORIZED
```
