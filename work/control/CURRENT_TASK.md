# Current Task — Gate 5.5 Node B Iteration 6 Final Pre-Live Fix

## Owner

`DSH (DeepSeek Harness)` — implementation + SELF_CERTIFIED self-review only.

## Status

`AUTHORIZED_FOR_FIXES_ONLY (ITERATION 6)`

## Audit source

Read first:

```text
work/gates/GATE_5_5/NODE_B_REVIEW_ITER5_20260815.md
```

Golden QMT reference remains pinned:

```text
smhe00/reverse_repo@c9ecc701d9b1c47d6a8d03539b482368741204a3
```

## Scope — ONLY NODEB-RR5-001..004

### RR5-001 — real live QMT binding path

- Keep Gate-1 simulation-only parser unchanged.
- Add/extract a separate strict Gate-5.5 QMT session-binding parser that supports exactly `simulation` and `live`.
- Production `build_live_session(... environment="live")` must be reachable with `live_qmt_path`, live binding fingerprint, unique normal securities account, exact connect/subscribe success, and validated `RootConfig.global.live_trading`.
- Add positive fake test using actual `environment="live"`; a simulation environment with `live_trading=True` is not a substitute.

### RR5-002 — eliminate SAFE_MODE public bypass

- Remove/privatize raw `clear_safe_mode()` from production API.
- Caller-supplied/empty/fabricated reconciliation results must not be accepted as proof for SAFE_MODE release.
- `LiveStack.reconcile_and_resume()` must run authoritative reconciliation internally and only then invoke an internal transition.
- Tests: direct engine API cannot clear unresolved SAFE_MODE; empty fabricated result cannot clear; resolved authoritative reconciliation can.

### RR5-003 — disconnect recovery must include reconciliation before health release

- Low-level connect must not itself restore new-order capability.
- Verify EventQueue RUNNING, exact connect success, bound securities account type + OK status, and subscription/required broker session health.
- Then reconstruct exposure and run authoritative broker/local reconciliation.
- Require explicit runtime reconfirmation.
- Only after all of the above may the disconnect execution latch be released.
- Tests: direct bridge reconnect cannot immediately place order; abnormal account status fails; unresolved state blocks; full driven recovery succeeds.

### RR5-004 — exact metadata semantics

- Do not set `git_head_commit` to the implementation SHA after a metadata child is pushed.
- Prefer explicit fields such as `implementation_commit`, `audit_base_commit`, `handoff_parent_commit`; avoid self-referential current-head claims.
- Exact full GitHub SHAs only.

## Frozen — DO NOT REWORK

Unless a direct regression is introduced by RR5 fixes, do not reopen:

- Gate 5 Node A PASS behavior;
- BrokerPort / LiveBrokerAdapter / single XtQuant order-cancel bridge;
- native int order ids;
- strict query / None retry contract;
- Reservation + OrderIntent + idempotency;
- UNKNOWN/duplicate-match handling;
- callback/EventQueue isolation and worker-state health gate;
- kill switch;
- NaN/Inf exact-type hardening;
- Core authority guard;
- daily exposure durable-date reconstruction;
- Migration 6 / persistent production DB path.

## Forbidden

- no real order;
- no real cancel;
- no Gate 6 run;
- no live soak claim;
- `live_trading_allowed` remains false;
- no force push/history rewrite.

## Evidence and stop condition

Run the full existing regression plus focused RR5 FI, compileall and capability scan. Label execution evidence `SELF_CERTIFIED`.

When complete:

1. push normally to `main`;
2. set state `AUDIT_READY_PRELIVE`;
3. authorize only `AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`;
4. record exact implementation SHA and audit base without pretending a metadata child is the implementation head;
5. STOP.

Gate 6 remains blocked until independent Node B PASS plus explicit user authorization.
