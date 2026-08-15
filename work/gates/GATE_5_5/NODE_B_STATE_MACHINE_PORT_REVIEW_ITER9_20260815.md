# Gate 5.5 Extension Audit — reverse_repo State Machine Port — Iteration 9 — 2026-08-15

## Verdict

`CHANGES_REQUIRED` for the **new state-machine / formal-verification extension**.

This verdict does **not** revoke the previously accepted Gate 5.5 baseline:

```text
baseline PASS_PRELIVE: e252847ecab2c5cb122af23091cd41680f901ccd
current audit head:     bf261835f70cbd56fa75b1ea2dc86447d22dcadb
reviewed implementation:f1e918ed474c9c107b03ab7ddcd3ad101783cce7
reference:               smhe00/reverse_repo@c9ecc701d9b1c47d6a8d03539b482368741204a3
```

The user explicitly authorized the reverse_repo state-machine + verifier port. That architectural direction is accepted. The purpose of this review is therefore not to reject the direction, but to ensure the port becomes a true production execution authority rather than a test-only model that can diverge from the live path.

`live_trading_allowed=false`. Real-money Gate 6/7 remain BLOCKED. Existing QMT-simulation evidence is retained, but it does not certify the new state-machine extension because the current production session/runner does not enable that extension.

## Accepted direction

The following design choices are accepted in principle and should be preserved:

- explicit TGrid execution lifecycle with NEW/PREFLIGHT/RECOVERY/WAIT_TRIGGER/SNAPSHOT/READY/INTENT/SUBMIT_UNKNOWN/ORDER_ACTIVE/CANCEL_PENDING/RECONCILE/terminal states;
- SafetyFacts-style abstract invariants and exhaustive explicit-state reachability verification;
- durable machine journal with code/spec binding;
- SUBMIT_UNKNOWN recovery that forbids blind retry;
- RESTART -> RECOVERY crash semantics;
- cross-process execution mutex;
- the earlier Gate 5.5 BrokerPort / LiveBrokerAdapter / XtQuant bridge safety boundary accepted at `e252847`.

The remaining work is implementation-to-model refinement and production wiring.

## Blockers

### NODEB-SM9-001 — P0: the new state machine, journal and mutex are not on the production `build_live_session()` path

`build_live_stack()` gained optional `journal_path` and `execution_lock_path`, but `build_live_session()` exposes neither parameter and does not pass either value. Therefore the production QMT construction path still creates an engine with `machine=None`, `journal=None`, and no execution mutex.

`scripts/gate6_sim_live.py` also calls `build_live_session()` without any state-machine/journal/mutex binding. The QMT simulation `order_stock` evidence therefore validates the previously accepted baseline execution chain, not the new state-machine extension.

Required:

1. Make the new execution-state authority part of the trusted production factory. For the new architecture, `build_live_session()` must construct a persistent journal and execution mutex from trusted/derived runtime paths and pass them into the stack.
2. The production simulation/live path must not have a silent opt-out that returns an order-capable stack with `machine is None` or no mutex. Low-level `build_live_stack()` may retain optional hooks for isolated unit tests only.
3. Add a production-shaped fake lifecycle test proving `build_live_session(environment="simulation")` and `build_live_session(environment="live")` both return a stack with the state machine, journal binding and execution mutex active.
4. Only after this wiring is accepted should Gate 6 simulation FILL/CANCEL verification be re-run using the new path.

### NODEB-SM9-002 — P0: mutex ownership does not currently protect journal creation and can be released while the stack remains order-capable

`ExecutionJournal.__init__()` calls `load_or_initialize()` and writes a new journal immediately when the path does not exist. `build_live_stack()` creates/loads that journal before the `ExecutionMutex` object is used, while the actual mutex is acquired later in `LiveStack.activate()`.

This creates a real race: process A and B can both observe a missing journal; one process can acquire the execution lock and begin advancing the journal while the other process is still completing pre-lock journal initialization and can overwrite the journal with an empty initial payload.

This differs materially from the pinned reverse_repo lifecycle, where journal load/initialization occurs inside the `with ExecutionMutex(...)` execution scope.

A second issue is that `release_execution_lock()` simply unlocks the file but does not close/disable the already activated stack. A caller can therefore release the lock early and continue using `stack.engine` while another process acquires the same lock, violating the claimed single-executor guarantee.

Required:

1. Acquire the execution mutex before any journal load/create/write and before any machine transition.
2. Journal initialization must be lazy or otherwise occur strictly under mutex ownership.
3. If an execution-capable stack releases its mutex, it must become irreversibly closed/unhealthy for new orders; no order path may remain usable after loss of lock ownership.
4. Add cross-process FI using the same lock + journal path proving the losing process cannot create/overwrite the journal and cannot mutate execution state.
5. Add FI proving a stack cannot place a new order after its execution lock has been released.

### NODEB-SM9-003 — P0: implementation-to-model event refinement is incomplete

The abstract state graph is internally consistent, but several runtime event mappings do not implement that graph correctly.

**A. Snapshot facts are self-certified by `send_*`.** `_drive_machine_to_submission()` automatically drives `WAIT_TRIGGER -> TRIGGER -> SNAPSHOT_OK -> READY`. `SNAPSHOT_OK` sets `cash_verified=True` and `quote_verified=True`, but the engine did not itself verify exchange trading day/time, quote freshness, broker cash snapshot, or other trusted snapshot evidence before emitting that event. The Gate 6 runner performs some checks externally, but the state machine is not cryptographically or structurally bound to those results.

**B. Cancel polling emits events from the wrong state family.** `timeout_order()` first advances `CANCEL_REQUESTED`, moving the machine to `CANCEL_PENDING`, then calls `poll_order()`. `poll_order()` emits `ORDER_STILL_ACTIVE` or `ORDER_TERMINAL` for SUBMITTED/PARTIAL/FILLED outcomes, but `CANCEL_PENDING` only accepts `CANCEL_STILL_PENDING` / `CANCEL_TERMINAL` (plus failure events). A normal asynchronous cancel therefore can raise `InvalidTransition`. `CANCELED` is also always mapped to `CANCEL_TERMINAL`, which is invalid when a cancellation is observed while the machine is still `ORDER_ACTIVE`.

**C. Recovery multiplicity is collapsed.** `_advance_recovery_outcome()` selects ACTIVE if any active match exists, else CANCEL_PENDING, else TERMINAL. A single-machine model cannot faithfully represent multiple simultaneously unresolved matched orders; the pinned reverse_repo explicitly treats multiple owned unresolved orders as ambiguous. A mixed/multiple unresolved result set must not be collapsed to one boolean machine state.

**D. Definitive local/pre-broker rejection is currently folded into `SUBMIT_EXCEPTION`.** The model contains `SUBMIT_REJECTED`, but `_send()` maps all `BrokerError` cases to `SUBMIT_EXCEPTION`, even when the adapter rejected before any broker invocation. This weakens the correspondence between model events and execution facts.

Required:

1. `send_buy/send_sell` in state-machine mode must require the machine already be `READY`; they must not manufacture `TRIGGER` or `SNAPSHOT_OK` themselves.
2. A trusted orchestrator/preflight layer must emit `TRIGGER` and `SNAPSHOT_OK` only after the actual trading-day/window, authoritative broker snapshot/cash and fresh quote checks succeed. Evidence must be structurally tied to the transition, not just performed elsewhere in a script.
3. Make poll/cancel event emission state-aware. In `CANCEL_PENDING`, pending/active broker status must map to `CANCEL_STILL_PENDING` and terminal outcomes to `CANCEL_TERMINAL`; in `ORDER_ACTIVE`, terminal outcomes use `ORDER_TERMINAL`.
4. Distinguish definitive pre-broker/local rejection (`SUBMIT_REJECTED`) from ambiguous submission exceptions (`SUBMIT_EXCEPTION`).
5. Recovery must fail closed on multiple/mixed unresolved orders that the single machine cannot represent, or the model must be explicitly extended to represent them.
6. Add refinement tests through the real `ExecutionEngine` methods, not only direct calls to `advance()`, covering every order/cancel/recovery broker outcome relevant to the model.

### NODEB-SM9-004 — P0: unknown-submission recovery still allows caller authority over the durable remark

`ExecutionEngine.recover_unknown_submission(client_order_key, ..., remark=None)` defaults to the durable `OrderIntent.order_remark`, but a caller can supply a different `remark`. If another broker order has that remark and the same symbol/side, the method can bind that broker order id to the local intent.

That contradicts the stated reverse_repo semantic: recovery is by the **persisted intent remark**, not an arbitrary caller-provided selector.

Required:

1. Remove the public `remark` override, or require exact equality with `intent.order_remark` before any broker query.
2. The durable intent remains the sole authority for recovery identity.
3. FI: attempting recovery with a different caller-provided remark cannot query/bind another broker order.

### NODEB-SM9-005 — P1: verifier source binding is fail-open for missing files and does not cover all safety-critical execution sources

The pinned reverse_repo `execution_source_sha256()` reads every declared protected source file and therefore fails if a protected file is missing. The TGrid port instead does:

```python
if not path.exists():
    continue
```

so a missing declared source silently changes the source set rather than failing closed.

In addition, the TGrid manifest currently binds seven files but omits safety-critical files that directly determine properties the journal is supposed to trust, including at least `live_broker_adapter.py`, `live_session.py`, `execution/store.py`, `daily_exposure.py`, and `exposure_store.py`. A change to double-enable, risk caps, account/session construction, durable intent/reservation, or daily exposure can therefore leave the journal verification hash unchanged.

Required:

1. Missing protected execution files must raise/fail verification, matching the reference fail-closed behavior.
2. Expand the execution-source manifest to cover every safety-critical source that can alter pre-submit authorization, durable intent/reservation, account binding, broker state mapping, recovery, exposure, state transitions or journal/mutex behavior.
3. Add a manifest integrity test proving omission/deletion of a protected file fails verification.
4. Describe `verify_state_machines()` accurately as exhaustive explicit-state verification of the abstract model. Claim implementation assurance only together with the refinement/integration tests above.

## Gate interpretation

The existing baseline `e252847` remains the accepted pre-extension Gate 5.5 implementation. The current main includes an unaudited execution extension, so the **current head** is not cleared for first real-money execution until this extension passes its independent review.

Gate 6 simulation evidence already collected is retained as useful baseline-channel evidence. It must not be represented as verification of the state-machine extension because the current runner did not enable the new journal/mutex path.

## Iteration 10 scope

Iteration 10 is strictly limited to NODEB-SM9-001..005 and direct regressions from those fixes. Do not reopen the old PASS_PRELIVE baseline without a concrete regression.

During this fix iteration:

- no real-money order/cancel;
- no additional QMT simulation order/cancel is needed; use fakes for the refinement fixes;
- keep `live_trading_allowed=false`;
- do not widen allowlists, order limits, cash limits, Core authority or trading authorization;
- preserve pinned reference `reverse_repo@c9ecc701d9b1c47d6a8d03539b482368741204a3`.

After fixes, hand off only for `AUDIT_NODE_B_STATE_MACHINE_PORT`. A later Gate 6 simulation rerun should use the integrated state-machine path and exercise FILL + PARTIAL/CANCEL + restart/unknown-submission behavior before any real-money Gate 6 authorization.
