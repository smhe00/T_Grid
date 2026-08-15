# Current Task — State Machine Production Refinement — Iteration 10

## Owner

`DSH (DeepSeek Harness)` — implementation + self-review. Self-review evidence must remain labelled `SELF_CERTIFIED`.

## Status

`CHANGES_REQUIRED`

The user-authorized reverse_repo state-machine + explicit-state verifier direction is accepted. The previously independent Gate 5.5 baseline remains `PASS_PRELIVE` at:

```text
e252847ecab2c5cb122af23091cd41680f901ccd
```

The current extension is not yet accepted for first real-money execution.

## Audit target

```text
main: bf261835f70cbd56fa75b1ea2dc86447d22dcadb
implementation: f1e918ed474c9c107b03ab7ddcd3ad101783cce7
reference: smhe00/reverse_repo@c9ecc701d9b1c47d6a8d03539b482368741204a3
review: work/gates/GATE_5_5/NODE_B_STATE_MACHINE_PORT_REVIEW_ITER9_20260815.md
fix: work/gates/GATE_5_5/FIX_REQUEST_STATE_MACHINE_ITER10_20260815.md
```

## Objective

Turn the new abstract state machine / journal / mutex from an optional test-level capability into the authoritative, correctly refined production execution path without weakening the previously accepted Gate 5.5 safety boundary.

## Authorized work

Only the following findings are authorized:

1. `NODEB-SM9-001`: production `build_live_session()` must bind state machine + journal + execution mutex; no production bypass.
2. `NODEB-SM9-002`: mutex must cover journal creation/load/write and remain an execution-health prerequisite for the lifetime of the active stack.
3. `NODEB-SM9-003`: correct implementation-to-model refinement: trusted TRIGGER/SNAPSHOT_OK evidence, state-aware cancel/poll events, definitive rejection vs ambiguous submission, and fail-closed recovery multiplicity.
4. `NODEB-SM9-004`: persisted intent remark is the sole unknown-submission recovery authority.
5. `NODEB-SM9-005`: protected source hash is fail-closed and covers all safety-critical production execution sources.

## Allowed implementation files

- `src/tgrid/execution/statemachine.py`
- `src/tgrid/execution/execution_journal.py`
- `src/tgrid/execution/execution_mutex.py`
- `src/tgrid/execution/executor.py`
- `src/tgrid/execution/recovery.py` only for direct refinement fixes
- `src/tgrid/execution/store.py` only if needed for protected-source/refinement wiring
- `src/tgrid/integrations/live_bootstrap.py`
- `src/tgrid/integrations/live_session.py`
- `src/tgrid/integrations/live_broker_adapter.py` only if needed for verified snapshot/session-lock gating
- `src/tgrid/integrations/daily_exposure.py` / `exposure_store.py` only if needed for source-manifest binding
- relevant `tests/unit/`
- `scripts/gate6_sim_live.py` only to wire the new authoritative path; do not invoke QMT during this fix
- DSH-owned reports/control metadata for the handoff

Do not modify unrelated strategy, Core-position, Gate-5 market-data or historical accepted behavior.

## Required evidence

- full unit regression;
- `compileall`;
- `verify_state_machines()` output;
- protected execution-source manifest and hash;
- FI for missing protected source;
- engine-level refinement tests for submit accepted/rejected/ambiguous, poll active/terminal, cancel pending/terminal, recovery multiplicity and wrong recovery remark;
- cross-process shared journal+lock race FI;
- post-lock-release new-order rejection FI;
- production-shaped fake `build_live_session()` for `simulation` and `live` proving machine+journal+mutex are mandatory;
- capability scan proving real XtQuant order/cancel call sites remain confined to the accepted bridge.

Execution counts remain `SELF_CERTIFIED` until independently re-run/verified.

## Forbidden

- no real-money order or cancel;
- no QMT simulation order/cancel during this fix iteration;
- no `live_trading_allowed=true` in canonical state;
- no widening symbol allowlists, qty/cash caps, Core floor or trading authorization;
- no force push/history rewrite;
- no claim that the abstract verifier alone proves the Python implementation.

## Stop / Handoff

After the fixes are pushed normally to `main`:

```text
state: REVIEW_READY
owner: architect
iteration: 10
authorized_next:
  - AUDIT_NODE_B_STATE_MACHINE_PORT
live_trading_allowed: false
```

Then STOP. Do not run the next trading-hours Gate 6 simulation FILL/CANCEL verification until the state-machine extension receives independent acceptance.
