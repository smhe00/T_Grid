# Architect Independent Audit — qmt-execution-core 0.2.1

Date: 2026-08-16

## Scope

Independent review of the reusable execution library after DSH validation/fix.

- repository: `smhe00/qmt-execution-core`
- reviewed commit: `2e222e16731bd8ce232ffba78c697245472c2094`
- version: `0.2.1`
- prior baseline: `a1500e724bcfed13efbac65d9fbdce2b2513c817` (`0.2.0`)
- TGrid migration: PAUSED by user during this audit
- live trading: NOT authorized

## Verdict

**PASS_FOR_MIGRATION**

`qmt-execution-core 0.2.1` is acceptable as the execution-core dependency for a later TGrid migration. This verdict does **not** authorize real-money trading and does **not** resume the paused migration by itself.

## Independent findings

### A. DSH found a real blocker in 0.2.0

DSH reproduced a Windows-only P1 in `ExecutionMutex`: after one owner cycle, a subsequent owner could acquire but failed `LK_UNLCK` with `PermissionError`. The issue broke restart/runtime-mutex tests and made 0.2.0 unsuitable for migration on the target Windows environment.

### B. 0.2.1 mutex fix is technically sound

At `2e222e1`, `_lock()` now:

1. seeks explicitly to byte 0;
2. performs only `msvcrt.locking(... LK_NBLCK, 1)` on Windows or `flock(... LOCK_EX|LOCK_NB)` on POSIX;
3. removes the pre-lock read/write `"0"` workaround that interacted badly with truncate/write ownership metadata.

`release()` seeks to the same byte 0 before `LK_UNLCK`. This restores lock/unlock offset symmetry and matches the mature reverse_repo/TGrid pattern.

DSH reports same-process repeated cycles and cross-process probes passing after the fix. GitHub push CI for `2e222e1` also completed successfully.

### C. Cancel/restart refinement gaps materially improved

0.2.1 adds committed regression tests for:

- cancel request rejected -> mandatory broker re-query; rejection is not treated as terminal cancellation;
- restart while cancel is pending -> authoritative query restores `CANCELLING`, then confirmed broker cancellation reaches `CANCELLED`.

Implementation inspection confirms:

- `ExecutionSession.cancel()` persists cancel intent before the broker cancel call and always calls `poll()` afterward;
- `CANCEL_REJECTED` is a recovery state, not a terminal order state;
- `event_for_observation()` maps state-aware broker observations into recovery/cancel events.

### D. Fill-during-cancel dedicated race test remains incomplete, but implementation path exists

There is not yet a dedicated committed race test where a cancel is in-flight and the broker reports a final fill afterward. This is retained as a **P2 pre-live test requirement**, not a migration blocker, because both model and runtime mapping explicitly support:

`CANCELLING + BrokerOrderStatus.FILLED -> ORDER_FILLED -> FILLED`.

This path must be covered before first real-money authorization.

### E. Library validation status

DSH evidence for 0.2.1:

- full Windows suite: **61 passed**;
- compileall: PASS;
- abstract verifier: **50 reachable abstract states / 208 transitions / 0 unreachable / 0 no-terminal-path / 0 invariant violations**;
- transition spec hash unchanged (`62e04e05...`);
- installed 0.2.1 wheel verifies outside checkout;
- real MiniQMT simulation client read-only smoke passed (connect/discover/subscribe/query asset/positions/orders/trades);
- zero QMT order/cancel calls during validation.

GitHub Actions push CI for exact commit `2e222e1` is `success`.

## Migration conditions

When the user explicitly resumes migration, TGrid should consume **0.2.1 or exact commit `2e222e1`**, not 0.2.0.

Migration should be staged:

1. add dependency/import adapter without deleting TGrid execution code;
2. map TGrid Core/T-Lot/daily-exposure/risk evidence into `ExecutionRequest` + `ExecutionGuard`;
3. run fake/shadow equivalence tests against the current accepted TGrid baseline;
4. cut production QMT execution authority over to `MiniQmtRuntime`;
5. only after equivalence, delete duplicate TGrid broker/state-machine/journal/mutex code.

TGrid-specific Core/T-Lot/ledger/daily-exposure/strategy semantics remain in TGrid.

## Pre-live requirements retained

Before any first real-money order:

- add dedicated fill-during-cancel race regression;
- integrated TGrid + qmt-execution-core QMT simulation must cover FILL, PARTIAL+CANCEL+REQUERY, restart recovery, and SUBMIT_UNKNOWN recovery;
- independent audit must pass the integrated path;
- user must explicitly authorize real-money Gate 6.

`f` / fetch does not constitute real-money authorization.

## Final state

- qmt-execution-core 0.2.1: **PASS_FOR_MIGRATION**
- TGrid migration: **PAUSED / AWAIT_USER_RESUME**
- `live_trading_allowed=false`
