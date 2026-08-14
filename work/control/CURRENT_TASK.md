# Task G2-T006 — Offline Position Reconciliation Decision Engine

## Goal

Implement a **pure offline, fail-closed position reconciliation decision layer** for one symbol. It compares the externally supplied broker position with the local expected decomposition and returns an immutable reconciliation decision. Any unexplained mismatch must result in `SAFE_MODE`; the component must never guess that a delta is Strategic, T-Lot, or a user trade.

This task is deliberately a decision engine only. It does not connect to QMT, does not query SQLite, does not persist SAFE_MODE, and does not implement startup orchestration.

## Architectural Intent

Design §21 requires startup reconciliation before strategy start and requires:

```text
BrokerPosition ?= LocalExpectedPosition
mismatch -> SAFE_MODE
```

Design §22.1 / INV-016 requires unknown manual/external position changes to enter symbol SAFE_MODE instead of being silently classified.

G2-T006 establishes that safety decision as a deterministic offline primitive before later tasks wire authoritative broker/ledger readers around it.

## In Scope

Add a new position-domain reconciliation module with a minimal public API equivalent to:

```python
reconcile_position(
    symbol_config,
    *,
    symbol,
    broker_position,
    strategic_extra,
    open_t_lot_position,
) -> PositionReconciliationResult
```

The exact function name may differ only if clearly justified in the report; semantics must not differ.

### Required result

Return a frozen/data-only result containing at least:

- `symbol`
- `decision`: exactly `RECONCILED` or `SAFE_MODE`
- `reason`: exactly one of `MATCH`, `CORE_FLOOR_BREACH`, `BROKER_POSITION_MISMATCH`
- `broker_position`
- `local_expected_position`
- `delta = broker_position - local_expected_position`
- the validated local components needed to audit the decision (`core_qty`, `strategic_extra`, `open_t_lot_position`)

### Local expected position

Core must come only from the existing frozen `SymbolConfig.core_qty`; there must be no second caller-supplied core value.

```text
LocalExpectedPosition = CoreQty + StrategicExtra + OpenTLotPosition
```

### Decision priority

1. Invalid/untrusted inputs -> fail closed with the existing position-domain project error layer; no result and no side effect.
2. If `broker_position < core_qty` -> `SAFE_MODE / CORE_FLOOR_BREACH`.
3. Else if `broker_position != local_expected_position` -> `SAFE_MODE / BROKER_POSITION_MISMATCH`.
4. Else -> `RECONCILED / MATCH`.

No positive or negative delta may be auto-reclassified.

## Deliberate Boundary

The caller supplies `strategic_extra` and `open_t_lot_position`. G2-T006 does **not** define how those values are loaded from SQLite or broker state. It only validates them as plain non-negative integers and makes the reconciliation decision.

This task therefore does not yet claim full startup Reconciliation or Crash Recovery. Later tasks will supply authoritative read models/orchestration.

## Out of Scope

- SQLite/T-Lot queries, CRUD, migrations, Audit Log writes, status transitions.
- QMT/XtQuant connection, account/asset/position/order/trade queries.
- Event Queue/startup orchestration, persistence of SAFE_MODE, crash recovery.
- Manual-trade classification UI/workflow or automatic Strategic/T-Lot reclassification.
- OrderIntent, Reservation, order state machine, partial fills, cancel/reject handling.
- Corporate Action adjustment.
- Any order/cancel/download/subscribe/live or dry-run trading execution.

## Reuse Direction

- Reuse existing `SymbolConfig`; core quantity must be obtained only from `SymbolConfig.core_qty`.
- Reuse the existing position/risk exception hierarchy, preferably `PositionInvariantError`; do not create an unrelated exception root.
- Do not modify or weaken the already-PASS `PositionSnapshot` / `CorePositionGuard` behavior in `manager.py`.
- Do not use `PositionSnapshot` to hide a mismatch: that type intentionally enforces equality and cannot represent a reconciliation discrepancy.

## Allowed Files

- `src/tgrid/position/reconciliation.py` (new)
- `src/tgrid/position/__init__.py` (only minimal exports for this task)
- `tests/unit/test_position_reconciliation.py` (new)
- `work/reports/tests/G2-T006-test-output.txt` (new)
- `work/gates/GATE_2/CLAUDE_REPORT.md`
- `work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md`
- `work/handoff/claude_to_architect/TEST_REPORT.md`
- `work/handoff/claude_to_architect/QUESTIONS.md` (only if genuinely needed)
- `work/control/WORKFLOW_STATE.yaml`

A local Lease may be used according to protocol but must never be staged/committed.

## Forbidden Files

- `src/tgrid/position/manager.py` and its existing tests.
- all `src/tgrid/persistence/**`, schema/migration/database/writer/policy files.
- Architect-owned `CURRENT_TASK.md`, `REVIEW.md`, `FIX_REQUEST.md`, Gate result/task files, design/protocol files.
- `work/control/CLAUDE_HEARTBEAT.md`.
- integrations/adapters/probes/risk implementations, models/config/scripts/docs/README.
- reverse_repo and any real/local DB, account, QMT userdata, logs, or secrets.

## Invariants

1. Core source is single-authority `SymbolConfig.core_qty`; no alternate core argument/override.
2. All quantities are exact plain non-negative `int`; reject bool, float, string, bytes, containers, int subclasses, and arbitrary objects before arithmetic.
3. Symbol is an exact plain non-empty `str`; reject subclasses and whitespace-only values.
4. Unknown objects must not have `str/repr/bool/iter/__eq__/__int__/__index__` invoked during rejection.
5. A mismatch never mutates or reclassifies `strategic_extra` or `open_t_lot_position`.
6. `broker_position < core_qty` has priority and always returns SAFE_MODE/CORE_FLOOR_BREACH.
7. Any other non-zero delta returns SAFE_MODE/BROKER_POSITION_MISMATCH, regardless of magnitude or whether it equals a plausible `t_unit`.
8. Exact equality returns RECONCILED/MATCH.
9. Result is frozen/data-only and contains no callable, connection, cursor, client, config mutator, or external capability.
10. No QMT, SQLite, filesystem/network, order/cancel/download/subscribe capability; no Python `assert` used as a safety mechanism.
11. `live_trading_allowed=false` remains binding.

## Acceptance Criteria

- `Broker=600, Core=600, Strategic=0, OpenT=0` -> `RECONCILED/MATCH`, expected=600, delta=0.
- `Broker=700, LocalExpected=600` -> `SAFE_MODE/BROKER_POSITION_MISMATCH`, delta=+100; no auto classification.
- `Broker=600, LocalExpected=700` -> `SAFE_MODE/BROKER_POSITION_MISMATCH`, delta=-100; no auto repair.
- `Broker < CoreQty` -> `SAFE_MODE/CORE_FLOOR_BREACH` even if another mismatch reason could also apply.
- Mixed valid holdings (Core + Strategic + OpenT) reconcile only on exact equality.
- A positive delta equal to common T-unit-like values is still mismatch/SAFE_MODE; no inference from quantity pattern.
- Exact-type and malicious-object tests prove invalid inputs are rejected without user dunder/secret leakage.
- Result immutability and exact field semantics are tested.
- Existing 618-test baseline remains passing; new tests are additive.
- AST/capability scan confirms no sqlite/xtquant/order/cancel/download/subscribe/filesystem/network and no `assert` in the new module.

## Required Tests / Failure Injection

- happy-path exact equality: zero-only, core+strategic, core+T, mixed.
- positive and negative broker deltas across boundaries 1, typical t-unit-like value, and large values.
- broker below core floor priority.
- zero values where legal; negative values rejected.
- bool/float/str/bytes/list/dict/int-subclass and arbitrary malicious quantity objects.
- malicious symbol object / str subclass; secret-bearing dunders must not execute and project exception graph must not expose secret.
- exact `SymbolConfig` required; fake/subclass objects rejected without reading arbitrary attributes.
- frozen result mutation attempt fails.
- deterministic proof that input components remain unchanged and no mutation/repair callback exists.
- AST forbidden-capability scan + full unittest + compileall + `git diff --check` + Allowed Files diff-check.

## Deliverables

- offline reconciliation decision primitive + frozen result.
- comprehensive unit/FI tests and raw output artifact.
- Implementation/Test/Claude reports must state explicitly:
  - decision/reason matrix;
  - Core source authority;
  - mismatch non-reclassification evidence;
  - Failure Injection results;
  - no SQLite/QMT/startup orchestration/SAFE_MODE persistence implemented.

## Stop Condition

After implementation/tests, fetch GitHub `main` again. If remote head is unchanged from the authorized baseline, publish a new unique handoff with `handoff_seq + 1`, `state=REVIEW_READY`, `owner=architect`, `task_id=G2-T006`, `iteration=1`, `authorized_next=[]`, and correct GitHub provenance; normal non-force push only.

If remote changed, worktree ownership is unclear, or the task cannot be completed without touching forbidden files, STOP WRITE. No force/rebase/merge/reset/stash/cherry-pick/blind retry.
