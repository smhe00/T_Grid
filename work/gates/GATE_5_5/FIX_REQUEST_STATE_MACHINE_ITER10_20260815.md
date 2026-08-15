# FIX REQUEST — reverse_repo State Machine Port — Iteration 10

Status: `CHANGES_REQUIRED`

Baseline Gate 5.5 `PASS_PRELIVE` at `e252847ecab2c5cb122af23091cd41680f901ccd` remains accepted. This fix request applies only to the user-authorized state-machine / formal-verification extension currently on main.

Audit target:

```text
main: bf261835f70cbd56fa75b1ea2dc86447d22dcadb
implementation: f1e918ed474c9c107b03ab7ddcd3ad101783cce7
reference: smhe00/reverse_repo@c9ecc701d9b1c47d6a8d03539b482368741204a3
```

## Required fixes

### SM9-001 — production wiring

Wire journal + state machine + execution mutex into the trusted `build_live_session()` path. Production simulation/live construction under the new architecture must not return an order-capable stack that bypasses the state machine or mutex. Add production-shaped fake tests for both environments.

### SM9-002 — lock/journal lifetime

Acquire the mutex before journal create/load/write. Prevent a losing process from touching the shared journal. Releasing the execution lock must permanently disable/close that stack for new orders. Add cross-process shared journal+lock FI and post-release-order rejection FI.

### SM9-003 — refinement mapping

Do not synthesize `TRIGGER/SNAPSHOT_OK` inside `send_*`; only trusted verified preflight/snapshot results may advance the machine to READY. Make ORDER_ACTIVE vs CANCEL_PENDING poll events state-aware. Distinguish definitive local rejection from ambiguous submission. Fail closed when recovery has multiple/mixed unresolved orders not representable by the single machine. Add engine-level refinement tests.

### SM9-004 — durable remark authority

Remove the caller-controlled recovery remark selector or require exact equality with the persisted intent remark. A caller must never be able to associate an intent with another broker order by supplying a different remark.

### SM9-005 — verification source integrity

Missing protected files must fail instead of being skipped. Expand the protected execution-source manifest to include all safety-critical production authorization/persistence sources (at minimum live session, live broker adapter, execution store, daily exposure and exposure store in addition to the current files). Add manifest-integrity tests.

## Constraints

- No real-money order/cancel.
- No QMT simulation order/cancel is required during this fix; use fakes.
- `live_trading_allowed=false` remains mandatory.
- Do not modify old frozen Gate-5.5 behavior except where necessary to wire/refine the new extension.
- Do not widen risk or trading authorization.
- Keep `reverse_repo` pinned at `c9ecc701d9b1c47d6a8d03539b482368741204a3`.

## Required handoff

After fixes:

```text
state = REVIEW_READY
owner = architect
iteration = 10
authorized_next = [AUDIT_NODE_B_STATE_MACHINE_PORT]
live_trading_allowed = false
```

Report exact implementation SHA, source-manifest contents/hash, verifier output, full regression count, compileall, refinement FI results, and capability scan. Do not claim PASS before independent review.
