# Current Task — Core 0.4.1 Runtime Authority → TGrid Iteration 16 Closure

## Owner

`DSH (DeepSeek Harness)` — implementation + self-review. Independent architect audit is required before any Core merge or TGrid acceptance.

## Status

`CHANGES_REQUIRED` — TGrid Iter16 functional integration at `bef47b3f4828937ad7dbda519d70d3df24a19657` is retained as the regression baseline, but production acceptance is blocked by coordination-domain uniqueness.

Authoritative architect audit:

```text
work/gates/QMT_EXECUTION_CORE/ARCHITECT_AUDIT_ITER16_RUNTIME_AUTHORITY_20260816.md
```

Public Core authoritative delta:

```text
docs/CORE_0_4_1_RUNTIME_AUTHORITY_SPEC.md
docs/IMPLEMENTATION_TASK_V0_4_1_RUNTIME_AUTHORITY.md
```

Core runtime baseline remains:

```text
qmt-execution-core 0.4.0
acf20d9fe5cf2aede3cc0ad0e8936ecb0c5b2692
```

`live_trading_allowed=false`. Do not invoke real or simulation QMT order/cancel APIs.

## P1 — Implement Core 0.4.1 first

Do not solve Runtime Authority as TGrid-local business logic.

Implement in public `qmt-execution-core` on a separate branch/PR:

```text
actual account identity
→ stable account_key
→ canonical per-account Runtime Authority
→ Authority-certified dedicated DB path + DB UUID
→ DB identity verification
→ SQLiteExecutionCoordinator
```

Required properties:

- one canonical Authority file per account identity;
- Authority filename derived from `account_key`, not chosen by strategy;
- Authority certifies canonical DB path, persistent `db_uuid`, and `authority_id`;
- dedicated DB metadata binds `account_key + db_uuid + authority_id`;
- per-account OS-backed authority lock;
- atomic concurrent bootstrap;
- mismatch/corruption/recreated DB fails closed;
- normal strategy runtime must not silently create/adopt a second coordination domain;
- production shared runtime must not trust arbitrary caller `coordination_path` as uniqueness proof;
- preserve Core 0.4 formal/refinement/shared-cash/finality/session-id/live-gate semantics;
- Python >=3.9 and Windows safety gates remain green.

Expected release is `0.4.1`. If compatibility requires a minor version, stop and escalate rather than silently relabel.

## P1 — Independent Core audit before merge

After implementation, hand back for independent audit. Do not merge Core until architect verdict is PASS.

Required evidence includes:

- full Core pytest;
- compileall;
- wheel clean install;
- installed `qmt-execution-core verify`;
- Python 3.9/3.11/3.12 CI;
- Windows authority-lock/bootstrap tests;
- cross-process same-account authority convergence;
- DB UUID/path/account mismatch fail-closed matrix;
- zero real/simulation QMT order/cancel.

## P1 — TGrid follow-up only after reviewed Core merge

After Core 0.4.1 is independently audited and merged:

1. pin TGrid to the exact reviewed Core merge SHA;
2. switch production TGrid composition to Runtime Authority resolution;
3. remove production `coordination_path` selection;
4. remove Gate-6 `--coordination-db` normal selection knob;
5. retain test-only injection only where explicitly isolated;
6. preserve the accepted Iter16 913-test functional baseline.

New TGrid tests must prove:

- same-account strategies resolve the same Authority and certified DB instance without independently receiving the DB path;
- different accounts resolve different Authority/DB instances;
- Authority/DB UUID mismatch prevents runtime construction before broker side effect;
- recreated DB at the same path is rejected;
- corrupted/missing Authority does not silently create fallback coordination;
- three runtimes/different symbols can still be WORKING concurrently;
- same-symbol exclusion/shared-cash/quarantine invariants remain green.

## Accepted Iter16 regression baseline

Do not regress:

- exact Core 0.4 semantics and one runtime-owned session authority;
- coordinate -> TGrid sidecar -> broker ordering;
- explicit CashRequirementEstimator;
- UNKNOWN/CANCEL_REJECTED/FAILED+QUARANTINED non-resend/non-release;
- safe journal cutover;
- 3-runtime distinct-symbol concurrency;
- same-symbol exclusion;
- shared-cash non-overcommit;
- quarantine and cross-account isolation;
- bounded session-id leasing;
- zero raw QMT order/cancel call sites in TGrid `src/`.

## Handoff

When Core 0.4.1 implementation is review-ready:

```text
state = REVIEW_READY
owner = architect
authorized_next = [AUDIT_QMT_EXECUTION_CORE_0_4_1_RUNTIME_AUTHORITY]
live_trading_allowed = false
```
