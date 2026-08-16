# TGrid → Core 0.4.1 Runtime Authority — Final Integration Evidence (Iteration 16)

> Date: 2026-08-16
> Task: `TGRID-QEC-CORE-0.4.1-RUNTIME-AUTHORITY-INTEGRATION-ITER16`
> Author: DSH (implementation + self-review). Evidence SELF_CERTIFIED until
> independent architect audit (`AUDIT_TGRID_CORE_0_4_1_RUNTIME_AUTHORITY_INTEGRATION_ITER16`).

## 0. Locked baseline

| Item | Value |
| --- | --- |
| Public Core | qmt-execution-core 0.4.1, merged after PR #4 audit PASS |
| TGrid pin | `a68572decb799bcbbf1b2892fcf58ac321ce9636` (exact merge SHA, no branch/tag) |
| TGrid `requires-python` | `>=3.9` (retained; ast 3.9 parse NONE failed) |
| `live_trading_allowed` | `false` throughout |

## 1. Production composition switch (P1-2 / P1-3)

`build_tgrid_qec_stack` / `build_qec_runtime` now:

- default `runtime_lock_mode="shared"`;
- call `MiniQmtRuntime.connect(...)` with **neither** `coordinator=` nor
  `authority=` override and **no** `coordination_path`/`authority_root`
  configuration (Core 0.4.1 production config no longer accepts them);
- rely on Core's OS-derived canonical per-account Runtime Authority,
  verify-only (`bootstrap=False`), certifying the dedicated coordination DB
  by canonical path + `db_uuid` + `authority_id`;
- retain an explicit conservative `CashRequirementEstimator`.

Removed production DB-selection surface: builder `coordination_path` /
`coordinator` params, Gate-6 `--coordination-db` CLI option (both
`gate6_sim_live.py` / `gate6_sim_negative.py`), and the previous
`default_coordination_path` derivation. No TGrid-specific Authority
path/root option replaced them.

Acceptance 1 (no override) is proven structurally:
`inspect.signature(build_tgrid_qec_stack)` / `build_qec_runtime` contain no
`coordination_path` / `authority_root` / `coordinator` / `authority`
parameter.

## 2. Explicit operator bootstrap prerequisite (P1-4)

Normal TGrid runtime never bootstraps. First-use lifecycle:

```text
qmt-execution-core bootstrap-authority --binding <binding-file>
        ↓
start TGrid shared strategy runtime
```

Missing/corrupt Authority or a replaced/mismatched certified DB fails closed
before any broker order/cancel side effect; TGrid adds no automatic
delete/recreate/adopt recovery path.

## 3. Acceptance matrix (all fake XtQuant / fake BrokerPort — zero QMT calls)

| # | Acceptance | Result |
| --- | --- | --- |
| 1 | production composition has no DB/root override | PASS (signature scan) |
| 2 | missing Authority -> normal runtime fails closed, no replacement, broker 0 | PASS |
| 3 | same-account two runtimes resolve the same Authority-backed DB | PASS |
| 4 | different accounts -> different Authority/DB instances | PASS |
| 5 | recreated DB at certified path -> construction fails closed before broker | PASS |
| 6 | same account, three distinct symbols -> concurrent WORKING | PASS |
| 7 | same-symbol second writer rejected before broker | PASS |
| 8 | shared cash cannot overcommit (100: 60+50 rejected, 60+40 exact) | PASS |
| 9 | QUARANTINED: claim + Core cash + business reservation held; other symbol proceeds | PASS |
| 10 | old hash-bound journal rejected (never silently migrated) | PASS |
| 11 | zero raw QMT order/cancel authority in TGrid `src/` | PASS |

## 4. Regression baseline preserved

The earlier Iter16 functional baseline (`bef47b3f`, 913-test self-certified)
remains green: one runtime/session authority per strategy process,
coordinate -> TGrid sidecar -> broker ordering, explicit
`CashRequirementEstimator`, UNKNOWN/CANCEL_REJECTED/FAILED+QUARANTINED
non-resend/non-release, safe journal cutover, three-runtime distinct-symbol
concurrency, same-symbol exclusion, shared-cash non-overcommit,
quarantine/account isolation, bounded session-id leasing.

## 5. Gates

```text
full TGrid pytest           : 915 passed, 17 subtests   (was 913; +2 startup-matrix)
compileall -q src tests scripts : 0
exact Core pin              : a68572decb799bcbbf1b2892fcf58ac321ce9636
capability scan             : ZERO raw QMT order/cancel call sites in src/
Gate-6 import/--help        : OK; --coordination-db removed from both runners
installed/pinned Core verify: PASS (release_formal_verification PASS,
                              3-process 433,489 states / 4,461,994 edges / 0)
ast.parse(feature_version=(3,9)) on src/tests/scripts : NONE failed
```

## 6. Files changed (production + tests)

```text
pyproject.toml                        pin -> a68572d (Core 0.4.1)
src/tgrid/integrations/qec_runtime.py production = Authority-only (no
                                      coordination_path/coordinator params)
scripts/gate6_sim_live.py             remove --coordination-db + docstring
scripts/gate6_sim_negative.py         remove --coordination-db + docstring
tests/unit/test_qec_iter15.py         test-only authority injection helper
tests/unit/test_qec_iter16.py         authority-root test helper; fail-closed
                                      builder signature test; startup matrix
                                      (missing authority, DB replacement);
                                      journal rejection via production builder
tests/unit/test_qec_runtime.py        test-only authority injection helper
```

## 7. Explicit safety statement

- `live_trading_allowed=false` throughout.
- No real or simulation QMT order/cancel API was invoked during
  implementation or validation (fake XtQuant / fake BrokerPort only).
- Gate-6 scripts were only import/`--help` smoke-tested; the integrated QMT
  simulation run remains a separate user-authorized step.
