# Gate 5.5 Audit Node B — Iteration 6 Final Review — 2026-08-15

## Verdict

`CHANGES_REQUIRED`.

Audit target:

```text
main: faa2e67cffc8bf43d9a20b2475b8e0c183e16890
implementation: ecf77eb5bb96a45794c1dcc2598bc39f7b4aea2b
reference: smhe00/reverse_repo@c9ecc701d9b1c47d6a8d03539b482368741204a3
```

Gate 5 remains independent PASS. Gate 6/7 remain BLOCKED. `live_trading_allowed=false`. No real TGrid order/cancel is authorized.

This review does not reopen frozen BrokerPort, native order-id, strict-query, Reservation/Idempotency, UNKNOWN handling, callback isolation, kill-switch, finite-number hardening, legacy Core guard, durable-date exposure reconstruction, Migration-6 persistence, or the newly accepted live-session parser without a concrete regression.

## Accepted / frozen in Iteration 6

- `NODEB-RR5-001` is accepted: Gate 5.5 now has a separate strict session-binding parser supporting exactly `simulation` and `live`; Gate 1 remains simulation-only. `build_live_session()` uses the new parser and there is a positive fake `environment="live"` lifecycle using `live_qmt_path` and a live binding entry.
- Low-level `verify_transport()` no longer clears the disconnect latch by itself.
- `LiveStack.recover_after_disconnect()` now orchestrates transport verification, re-subscribe, exposure reconstruction, broker/local reconciliation, runtime reconfirmation and latch release in that order.
- Public `clear_safe_mode()` / `clear_safe_mode_after_reconciliation()` names were removed.
- All previously frozen Node-B items remain accepted.

## Remaining blockers

### NODEB-RR6-001 — P0: SAFE_MODE can still be cleared with a fabricated resolved result through exposed `stack.engine`

`ExecutionEngine._clear_safe_mode_after_reconciliation(results)` is private by naming convention but remains directly reachable because `LiveStack.engine` is public. More importantly, the method still trusts caller-supplied result objects. It rejects an empty tuple when open intents exist and rejects explicit unresolved outcomes, but any fabricated object with e.g. `outcome="MATCHED"` and `broker_status="SUBMITTED"` clears `_safe_mode_reason` without executing broker reconciliation.

The Iteration-6 test demonstrates this exact weakness: after asserting the public clear methods are absent, it passes a fabricated `MATCHED/SUBMITTED` object to `_clear_safe_mode_after_reconciliation()` and expects SAFE_MODE to clear. This contradicts the Iteration-5 requirement that `stack.engine` cannot be used to clear SAFE_MODE with an empty/fabricated result and contradicts the DSH report claim that fabricated results are rejected.

Required:

1. No API reachable from the exposed engine may accept caller-supplied reconciliation result objects as authority for clearing SAFE_MODE.
2. If a clear/recovery method is exposed, it must itself execute the authoritative broker/local reconciliation using the engine/store/broker state, or consume an unforgeable/internal capability not constructible by normal callers.
3. `LiveStack.reconcile_and_resume()` must remain the production path and tests must prove fabricated `MATCHED` objects cannot clear SAFE_MODE.
4. Keep unresolved/UNKNOWN broker state fail-closed and preserve reservations.

### NODEB-RR6-002 — P0: disconnect account-health verification still does not implement the pinned reference contract

The pinned `reverse_repo.select_bound_account()` requires account status rows to match both:

```text
account_type == xtconstant.SECURITY_ACCOUNT
status == xtconstant.ACCOUNT_STATUS_OK
```

Current `XtQuantBrokerBridge._verify_bound_account_healthy()` only matches account id and status. It does not verify `account_type` at all. It also stores `account_status_ok` using the bridge constructor default `1`; `build_live_session()` obtains the real `security_type, status_ok` constants for initial account selection but `build_live_stack()` does not pass either value into the bridge, so reconnect verification is not bound to the actual XtQuant constants established by the production session.

Required:

1. Persist the exact expected `SECURITY_ACCOUNT` and `ACCOUNT_STATUS_OK` values resolved during production session construction into the bridge/recovery policy; do not rely on an unverified default.
2. `_verify_bound_account_healthy()` must require account id + account type + account status to match exactly.
3. Add FI for correct id but wrong account type, correct id/type but abnormal status, and success using non-default injected constants.
4. Only after this verification, re-subscribe, exposure reconstruction, authoritative reconciliation and runtime reconfirm may the disconnect latch be cleared.

### NODEB-RR6-003 — P1: canonical `git_head_commit` semantics are still incorrect

At audit time actual `main` is:

```text
faa2e67cffc8bf43d9a20b2475b8e0c183e16890
```

but `WORKFLOW_STATE.yaml` still contains:

```text
git_head_commit: ecf77eb5bb96a45794c1dcc2598bc39f7b4aea2b
implementation_commit: ecf77eb5bb96a45794c1dcc2598bc39f7b4aea2b
```

The metadata child commit `faa2e67...` is therefore still not represented as the current shared head, despite the report claiming the self-referential head problem was removed.

Required: remove `git_head_commit` entirely if it cannot be represented without self-reference, or define non-self-referential fields such as `implementation_commit`, `handoff_parent_commit`, and `handoff_metadata_parent` whose semantics are exact. Do not label the implementation commit as the GitHub branch head after a metadata child exists.

## Evidence limitation

GitHub exposes no CI status/checks for the reviewed implementation/head. DSH reports 952 tests, compileall 0 and capability scan PASS; those remain `SELF_CERTIFIED` execution evidence. This independent verdict is based on direct code/test/control-plane inspection.

## Iteration 7 scope

Iteration 7 is strictly limited to `NODEB-RR6-001..003` and direct regressions caused by those fixes. Do not rework any frozen item, including the live parser, exposure reconstruction, Migration 6, strict queries, order-id handling, callback isolation, Reservation/Idempotency, or Gate-5 behavior.

After fixes: push normally, set `AUDIT_READY_PRELIVE`, authorize only `AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`, keep `live_trading_allowed=false`, and STOP.

First real order remains prohibited until both:

```text
Audit Node B = PASS
AND
explicit user authorization = YES
```
