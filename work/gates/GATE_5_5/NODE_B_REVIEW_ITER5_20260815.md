# Gate 5.5 Audit Node B — Iteration 5 Final Production-Glue Review — 2026-08-15

## Verdict

`CHANGES_REQUIRED`.

Audit target:

```text
main: a3909505895afb8c4b7f5b7b170dbcd22ce628c3
implementation: 4c894c14c05ad9c742b9e6002b1ca38b1f863daf
reference: smhe00/reverse_repo@c9ecc701d9b1c47d6a8d03539b482368741204a3
```

Gate 5 remains independent PASS. Gate 6/7 remain BLOCKED. `live_trading_allowed=false`. No real TGrid order/cancel is authorized.

This review does not reopen frozen BrokerPort, native order-id, strict-query, Reservation/Idempotency, UNKNOWN handling, callback isolation, kill-switch, NaN/Inf, legacy Core guard, durable-date exposure reconstruction, or Migration-6 persistence without a concrete regression.

## Accepted / frozen in Iteration 5

- Daily exposure reconstruction now joins broker orders to durable `OrderIntent.created_at` and no longer depends on raw QMT `order_time`; unassignable managed orders are counted conservatively.
- `daily_exposure` is Migration 6 and the production session opens a persistent DB path from TGrid config; `SqliteExposureStore` no longer creates an ad-hoc table.
- The XtQuant strict-query contract remains aligned with the pinned reference.
- Mandatory startup reconciliation remains in `LiveStack.activate()`.
- EventQueue lifecycle health gating remains accepted.
- Existing live execution call sites remain confined to the single XtQuant bridge.

## Remaining blockers

### NODEB-RR5-001 — P0: production `environment="live"` is still impossible

`build_live_session()` still calls `load_gate1_config(gate1_config_path)`. The current `parse_gate1_config()` still explicitly accepts only `environment == "simulation"` and raises `only the simulation environment is authorized` for `live`.

The new positive test is therefore not a live-QMT construction test: it builds the QMT binding with `environment="simulation"`, passes `environment="simulation"`, then only sets `RootConfig.global.live_trading=True`.

Required:

1. Preserve the Gate-1 simulation-only parser unchanged for Gate 1.
2. Add/extract a separate strict QMT session-binding parser usable by Gate 5.5 that explicitly supports exactly `simulation` and `live` and reuses the same runtime-path/account-fingerprint validation.
3. Add a positive fake production test with QMT binding `environment="live"`, `live_qmt_path`, a live binding entry, exact connect/subscribe success and `RootConfig.global.live_trading=True`.
4. Wrong/mismatched environment must still fail closed.

### NODEB-RR5-002 — P0: SAFE_MODE still has public caller-supplied bypasses

`LiveStack.engine` is public. `ExecutionEngine.clear_safe_mode()` remains public and directly sets `_safe_mode_reason=None`.

Even `clear_safe_mode_after_reconciliation(results)` is not authoritative: it trusts arbitrary caller-provided objects, and an empty tuple clears SAFE_MODE without running broker reconciliation.

Required:

1. Remove the unrestricted public `clear_safe_mode()` from the production API (rename any test-only raw reset to a private/internal helper if truly needed).
2. Do not expose a public method that accepts caller-supplied reconciliation results as proof. The production path must itself execute `reconcile_open_intents()` and only then invoke an internal/private state transition.
3. Add FI proving `stack.engine` cannot be used to clear SAFE_MODE with an empty/fabricated result and that only `LiveStack.reconcile_and_resume()` after authoritative reconciliation resumes execution.

### NODEB-RR5-003 — P0: disconnect reconnect can restore order capability before full recovery

`XtQuantBrokerBridge.reconnect()` clears `_disconnected` and restores callback health after `connect()==0` and after merely seeing the bound account id in `query_account_status()`.

Problems:

- it does not require the account to be the expected securities account type and `ACCOUNT_STATUS_OK`;
- it does not re-subscribe/verify subscribe result;
- most importantly, it clears execution health before broker/local order reconciliation. The current test explicitly calls `bridge.reconnect()` and then immediately places a new order.

Required:

1. Make low-level reconnect transport establishment insufficient to restore new-order capability.
2. Production disconnect recovery must be orchestrated by `LiveStack` (or equivalent): EventQueue RUNNING -> exact connect success -> exact bound account type/status verification -> subscribe/verification as required -> exposure reconstruction -> authoritative broker/local reconciliation -> explicit runtime reconfirmation -> only then clear the disconnect execution latch.
3. Add FI proving direct bridge reconnect cannot be followed by a new order before reconciliation, abnormal account status fails, and unresolved broker/local state keeps execution blocked.

### NODEB-RR5-004 — P1: canonical head metadata still claims the wrong SHA

At audit time actual `main` is:

```text
a3909505895afb8c4b7f5b7b170dbcd22ce628c3
```

but `WORKFLOW_STATE.yaml` records `git_head_commit` as implementation commit:

```text
4c894c14c05ad9c742b9e6002b1ca38b1f863daf
```

and `CLAUDE_REPORT.md` claims these are distinct metadata/implementation heads. They are not recorded distinctly.

Required: avoid a self-referential `git_head_commit` field or explicitly record `implementation_commit` and `handoff_parent_commit`/`metadata_commit` with exact GitHub SHAs. Do not claim the implementation SHA is current main after a metadata child has been pushed.

## Evidence limitation

GitHub exposes no CI status/checks for the reviewed implementation/head. DSH reports 950 tests, compileall 0 and capability scan PASS; those remain `SELF_CERTIFIED` execution evidence. This independent verdict is based on direct code/test/control-plane inspection.

## Iteration 6 scope

Iteration 6 is strictly limited to NODEB-RR5-001..004 and direct regressions caused by those fixes. Do not rework frozen items.

After fixes: push normally, set `AUDIT_READY_PRELIVE`, authorize only `AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`, keep `live_trading_allowed=false`, and STOP.

First real order remains prohibited until both:

```text
Audit Node B = PASS
AND
explicit user authorization = YES
```
