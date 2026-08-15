# Current Task — Gate 5.5 Live Broker Adapter (Pre-Live Only)

## Owner

`DSH (DeepSeek Harness)` — implementation + self-review allowed; self-review must remain `SELF_CERTIFIED`.

## Status

`AUTHORIZED_FOR_FIXES_ONLY (ITERATION 7)`

Gate 5 remains independent PASS. Gate 5.5 remains `CHANGES_REQUIRED`. Gate 6/7 remain `BLOCKED`. `live_trading_allowed=false` remains mandatory.

## Source of Authorization

Independent review:

```text
work/gates/GATE_5_5/NODE_B_REVIEW_ITER6_20260815.md
```

Reviewed target:

```text
main: faa2e67cffc8bf43d9a20b2475b8e0c183e16890
implementation: ecf77eb5bb96a45794c1dcc2598bc39f7b4aea2b
reference: smhe00/reverse_repo@c9ecc701d9b1c47d6a8d03539b482368741204a3
```

## Iteration 7 — ONLY Authorized Fixes

### NODEB-RR6-001 — P0: remove fabricated-result SAFE_MODE authority

Current `_clear_safe_mode_after_reconciliation(results)` remains reachable through public `LiveStack.engine` and accepts fabricated resolved result objects.

Required:

- no engine API reachable from production may accept caller-supplied reconciliation result objects as proof for clearing SAFE_MODE;
- production release must itself perform authoritative broker/local reconciliation, or consume an internal capability not forgeable by ordinary callers;
- `LiveStack.reconcile_and_resume()` remains the production transition;
- add FI proving fabricated `MATCHED/SUBMITTED` objects cannot clear SAFE_MODE;
- UNKNOWN/unresolved state keeps SAFE_MODE and reservations.

### NODEB-RR6-002 — P0: reconnect must bind exact account type + status constants

Current reconnect health verification checks account id + status only and relies on bridge default `account_status_ok=1`. The production session already resolves real XtQuant `SECURITY_ACCOUNT` and `ACCOUNT_STATUS_OK` constants but does not pass them into the bridge.

Required:

- propagate exact production `security_account_type` and `account_status_ok` values into the bridge/recovery boundary;
- require exact account id + account type + status match;
- add FI: correct id/wrong type fails; correct id/type/bad status fails; injected non-default constants succeed;
- keep low-level transport reconnect insufficient for execution recovery;
- keep order recovery sequence: queue RUNNING -> connect -> account type/status verify -> subscribe -> exposure reconstruct -> authoritative reconciliation -> runtime reconfirm -> latch clear.

### NODEB-RR6-003 — P1: remove misleading canonical head field

Current shared main is metadata child `faa2e67...`, while state labels implementation `ecf77eb5...` as `git_head_commit`.

Required:

- remove `git_head_commit` if exact current-head self-reference cannot be represented safely; or replace it with non-self-referential fields whose semantics are explicit;
- keep exact `implementation_commit` and handoff parent/base SHA fields;
- do not claim implementation SHA is current branch head after metadata commit.

## Frozen — DO NOT Rework Without Direct Regression

The following are accepted and frozen:

- true Gate-5.5 `simulation`/`live` session parser and positive live-environment fake lifecycle;
- Gate-1 simulation-only parser;
- BrokerPort / LiveBrokerAdapter / XtQuant bridge architecture;
- native int order-id conversion;
- strict-query `None`/exception fail-closed behavior;
- Reservation + OrderIntent-before-send + idempotency;
- UNKNOWN/duplicate recovery fail-closed;
- real EventQueue callback isolation/lifecycle health;
- kill switch and finite-number hardening;
- durable OrderIntent-date daily-exposure reconstruction;
- Migration 6 / persistent production database lifecycle;
- legacy Core authority guard;
- Gate 5 Node A PASS behavior.

## Forbidden

- no real order invocation;
- no real cancel invocation;
- no Gate 6 run;
- no enabling `live_trading_allowed`;
- no production/live-soak claim;
- no force push/history rewrite;
- no broad refactor outside RR6-001..003.

## Stop / Handoff

After fixes and self-certified regression evidence:

1. push normally to `main`;
2. set state to `AUDIT_READY_PRELIVE`;
3. record exact implementation commit and non-self-referential handoff metadata;
4. authorize only `AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`;
5. STOP.

First real order remains prohibited until:

```text
Audit Node B = PASS
AND
explicit user authorization = YES
```
