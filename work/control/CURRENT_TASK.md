# Current Task — qmt-execution-core 0.2.1 Independent Audit

## Status

`PASS_FOR_MIGRATION_AWAIT_USER`

The reusable execution library has passed independent audit for use as the future TGrid execution-core dependency:

```text
repository: https://github.com/smhe00/qmt-execution-core
version:    0.2.1
commit:     2e222e16731bd8ce232ffba78c697245472c2094
local:      D:\gitee\miniQMT\qmt-execution-core
```

Independent audit:

```text
work/gates/QMT_EXECUTION_CORE/ARCHITECT_AUDIT_0_2_1_20260816.md
```

DSH validation/fix evidence:

```text
work/gates/QMT_EXECUTION_CORE/DSH_VALIDATION_REPORT_20260816.md
```

## Independent conclusion

- 0.2.0 had a real Windows P1 mutex-release defect and is NOT an acceptable migration target.
- 0.2.1 fixes that defect with symmetric byte-0 lock/unlock semantics and passes DSH Windows regression, repeated same-process/cross-process lock probes, installed-wheel verification, and GitHub CI.
- Full DSH Windows suite: 61 passed; compileall PASS.
- Formal verifier: 50 reachable abstract states / 208 transitions / 0 unreachable / 0 no-terminal-path / 0 invariant violations.
- Real MiniQMT simulation read-only smoke passed; no order/cancel APIs were invoked.
- Dedicated fill-during-cancel race test remains a P2 pre-live requirement, but the runtime/model path already maps `CANCELLING + FILLED -> FILLED`, so this does not block code migration.

## Migration state

**PAUSED by explicit user instruction.**

Do not start TGrid migration until the user explicitly says to resume/start it. `f` / fetch alone is not migration authorization.

When resumed, migrate in stages:

1. depend on qmt-execution-core 0.2.1 / exact commit `2e222e1`;
2. preserve TGrid-specific Core/T-Lot/ledger/daily exposure/strategy risk;
3. adapt TGrid requests/evidence into `ExecutionRequest` + `ExecutionGuard`;
4. prove fake/shadow behavioral equivalence before deleting the old TGrid execution stack;
5. cut QMT execution authority over to `MiniQmtRuntime` only after equivalence tests;
6. independently audit the integrated path.

## Safety boundary

`live_trading_allowed=false`.

Before first real-money execution, still require:

- dedicated fill-during-cancel regression;
- integrated QMT simulation evidence for FILL, PARTIAL+CANCEL+REQUERY, restart recovery, and SUBMIT_UNKNOWN recovery;
- independent audit of the integrated TGrid + qmt-execution-core path;
- explicit user authorization for real-money Gate 6.
