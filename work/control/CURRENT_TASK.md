# Current Task — qmt-execution-core 0.2.0 Validation (2026-08-16)

## Owner

`DSH (DeepSeek Harness)` — validation only. Self-review evidence is labelled
`SELF_CERTIFIED`.

## Status

`REVIEW_READY` — validation report delivered
(`work/gates/QMT_EXECUTION_CORE/DSH_VALIDATION_REPORT_20260816.md`),
**verdict SELF_CERTIFIED CHANGES_REQUIRED**, handed off for
**AUDIT_QMT_EXECUTION_CORE_0_2_0** independent review.

TGrid migration remains **PAUSED** until the architect reviews this
validation. `live_trading_allowed=false`. No real or simulation QMT
order/cancel was invoked. Neither production codebase was modified.

## Audit target

```text
repository: https://github.com/smhe00/qmt-execution-core
branch:     main
commit:     a1500e724bcfed13efbac65d9fbdce2b2513c817
version:    0.2.0
local:      D:\gitee\miniQMT\qmt-execution-core
request:    work/gates/QMT_EXECUTION_CORE/VALIDATION_REQUEST_20260816.md
report:     work/gates/QMT_EXECUTION_CORE/DSH_VALIDATION_REPORT_20260816.md
```

## Validation summary (SELF_CERTIFIED)

- **V1 identity PASS**: local HEAD exactly `a1500e7...`, tree clean;
  pyproject 0.2.0; **0 `tgrid` imports** (src + tests); xtquant only lazy
  inside `miniqmt/runtime.py::_real_xtquant_dependencies()`; Python 3.12.10 /
  Windows.
- **V2 source tree**: `pytest` = **56 passed / 3 failed**, `compileall` = 0,
  `qmt-execution-core verify` = PASS (50 reachable states / 208 transitions /
  0 unreachable / 0 violations; spec `62e04e05...`, source `67dd05dd...`).
- **V3 wheel**: built `qmt_execution_core-0.2.0-py3-none-any.whl`, installed in
  a clean Python 3.12 venv, `verify` from outside the checkout gives identical
  hashes; missing protected source fails closed (isolated fixture only).
- **V4 static audit**: all sampled controls (V4-A..V4-I) PASS — see report.
- **V5 refinement coverage**: 21/24 committed-test paths; gaps:
  cancel-rejected+re-query, restart-cancel-pending, fill-during-cancel (partial).
- **V6 real MiniQMT read-only smoke PASS**: simulation client (running),
  connect/discover/subscribe/query asset/positions/orders/trades, healthy,
  clean close; **zero order/cancel calls**.
- **V7 independence/reuse PASS**: sufficient public API, evidence injectable
  via `ExecutionGuard`, raw QMT states normalized below the adapter boundary,
  no TGrid filesystem/database dependency.

## Findings (reported, NOT fixed — validation-only task)

- **P1 — Windows execution-mutex release defect**:
  `src/qmt_execution_core/mutex.py` `ExecutionMutex._lock` (pre-lock "0"-byte
  write workaround, lines 73-82) + `acquire` (`truncate`, line 47) + `release`
  (`LK_UNLCK`, line 65): after one complete owner cycle, any subsequent owner
  (same or separate process) cannot `release()` — `PermissionError` at
  `msvcrt.locking(..., LK_UNLCK, 1)`. Deterministic (12/12), cross-process
  reproduced. Breaks 3 committed tests.
- **P2 — committed-test gaps**: cancel-rejected + re-query; restart from
  cancel-pending; fill-during-cancel only partially covered.

## Fix addendum (architect-authorized, 2026-08-16)

The architect authorized fixing the library. **P1 FIXED** in
`qmt-execution-core` 0.2.1 (`2e222e1`, fast-forward `a1500e7..2e222e1`):
`_lock` now seeks to byte 0 and performs a pure `msvcrt.locking`/`flock`
(mirrors reverse_repo/TGrid), removing the "0"-byte write workaround that
poisoned subsequent `LK_UNLCK`. Verified: full suite **61 passed** (the 3
previously-failing tests pass), compileall 0, verifier 50/208/0/0/0 (spec
unchanged, source `a2258423...`), same-process + cross-process repros OK,
wheel 0.2.1 clean-env verify OK. **P2 gaps closed**: added
`test_cancel_rejected_requires_requery` + `test_restart_recovers_cancel_pending`
(V5 matrix 23/24). Report updated with the fix addendum.

## Confirmations

- No real or simulation QMT order/cancel invoked.
- TGrid migration not performed; TGrid execution code untouched.
- `qmt-execution-core` unmodified (tree clean after validation).
- `live_trading_allowed=false` maintained.
