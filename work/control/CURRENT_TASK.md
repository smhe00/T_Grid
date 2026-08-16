# Current Task — TGrid → qmt-execution-core 0.4 — Iteration 16

## Owner

`DSH (DeepSeek Harness)` — implementation + self-review. All implementation evidence remains SELF_CERTIFIED until architect audit.

## Status

`IN_PROGRESS` — Core 0.4 has passed formal verification + independent architecture/code audit and is merged to public-core `main`.

Locked Core dependency:

```text
qmt-execution-core 0.4.0
commit acf20d9fe5cf2aede3cc0ad0e8936ecb0c5b2692
```

Authoritative Iter16 plan:

```text
work/gates/QMT_EXECUTION_CORE/CORE_0_4_TGRID_INTEGRATION_PLAN_20260816.md
```

TGrid implementation baseline:

```text
bf6cb86814da359544ba734ffc8ae9a82a9d9047
```

Iteration 15 single-authority composition, recoverable CANCEL_REJECTED handling, Gate-6 import surface, and one-active-order-per-TGrid-engine constraint are accepted as the starting baseline and must not regress.

`live_trading_allowed=false`. Do not invoke real or simulation QMT order/cancel APIs.

## Required work

### P1-1 Pin and compose Core 0.4 exactly

Update the exact qmt-execution-core git pin to:

```text
acf20d9fe5cf2aede3cc0ad0e8936ecb0c5b2692
```

Preserve one execution authority:

```text
MiniQmtRuntime owns runtime.session
ExecutionEngine uses exactly runtime.session
```

No second ExecutionSession/journal/mutex authority may be constructed around the same runtime/broker.

### P1-2 Enable shared runtime/account coordination

Wire Core 0.4 shared mode through the TGrid production composition:

```text
runtime_lock_mode = "shared"
coordination_path = explicit canonical account-level coordination DB
```

All strategy processes sharing the account must use the same coordination domain. Do not default to a strategy-specific DB path and do not silently run shared mode without coordination.

Use Core's bounded MiniQMT session-id leasing. Strategy business code must not manage session IDs directly.

### P1-3 Wire account-level shared BUY cash safely

Provide an explicit conservative Core `CashRequirementEstimator` to coordinated BUY execution.

Core account-level cash reservation is the cross-process authorization gate. Existing TGrid `OrderIntent + Reservation + DailyExposure` remains the TGrid business ledger and sidecar.

Required order:

```text
Core durable intent
→ Core symbol/cash coordination COMMIT
→ TGrid business sidecar COMMIT
→ broker submit
```

Do not add Settlement Pending local cash credit/accounting.

### P1-4 Preserve finality/recovery across the business ledger

Use Core 0.4 `ExecutionFinality` semantics.

`UNKNOWN`, `CANCEL_REJECTED`, and `FAILED + unresolved_order=True / QUARANTINED` must not become blind-resend or premature-release permission in TGrid.

Add a table-driven state/finality → TGrid business-terminality test and an UNKNOWN → recovery-failed → QUARANTINED regression.

### P1-5 Safe journal cutover

Do not bypass public-core source/spec hash binding.

Tests/documentation must establish:

```text
old 0.3.1 journal -> rejected under 0.4 hash
planned cutover -> reconcile old execution -> archive old journal -> new 0.4 journal path
```

No in-place silent journal migration.

### P1-6 Prove three independent strategy runtimes

With fake XtQuant only, create three independent TGrid/Core stacks sharing one account-level coordination DB.

Required evidence:

- A/B/C on different symbols can all be `WORKING` concurrently;
- same-account/same-symbol second writer is rejected before broker call;
- shared-cash race cannot overcommit;
- one strategy UNKNOWN/QUARANTINED does not globally block another symbol except through its held cash;
- same symbol on different accounts is independent;
- runtime/session IDs are distinct as required;
- closing/restarting one stack does not close or mutate another stack.

## Required verification

- full TGrid pytest;
- `compileall -q src tests scripts`;
- Gate-6 import/`--help` smoke;
- exact qec pin `acf20d9...`;
- Python baseline remains `>=3.9`;
- zero raw QMT order/cancel calls in TGrid production `src/`;
- one runtime-owned execution-session authority per stack;
- shared coordination before TGrid sidecar before broker;
- 3-process/different-symbol concurrency;
- same-symbol exclusion;
- shared-cash non-overcommit;
- recoverable/quarantined state retention;
- fill-during-cancel → FILLED;
- disconnect/recovery evidence gates;
- explicit evidence that no real or simulation QMT order/cancel was invoked.

## Handoff

When all items pass:

```text
state = REVIEW_READY
owner = architect
authorized_next = [AUDIT_TGRID_QMT_EXECUTION_CORE_V0_4_ITER16]
live_trading_allowed = false
```

Write evidence to:

```text
work/gates/QMT_EXECUTION_CORE/TGRID_CORE_0_4_INTEGRATION_EVIDENCE_20260816.md
```
