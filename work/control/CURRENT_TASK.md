# Current Task — Gate 5.5 Node B Iteration 5 Final Production-Glue Fix

## Owner

`DSH (DeepSeek Harness)` — implementation + self-review. Self-review must remain `SELF_CERTIFIED`.

## Status

`CHANGES_REQUIRED` after independent Node B Iteration-4 review of:

```text
main: 082a109b343db1e662842c2768ba8a18413604cc
implementation: 7f3c667fa13fa6bb3e470b22000492aab0705b57
```

Golden QMT reference remains pinned:

```text
https://github.com/smhe00/reverse_repo
c9ecc701d9b1c47d6a8d03539b482368741204a3
```

## Scope — ONLY NODEB-RR4-001..005

### RR4-001 — true production live session

Fix `build_live_session()` so it is actually usable for live QMT and follows the reference lifecycle:

```text
validated TGrid RootConfig (global.live_trading default false)
+ QMT runtime/account/path binding
-> construct trader
-> start
-> connect (plain-int success required)
-> strict account infos/status discovery
-> exactly-one bound normal securities account
-> subscribe (plain-int success required)
-> EventQueue/bridge/adapter
-> mandatory startup reconciliation
-> runtime confirmation
```

Do NOT reuse the simulation-only Gate-1 config parser as the live environment parser. Reuse/extract its hardened account/path fingerprint primitives instead.

Production config enable must come from validated `RootConfig.global_config.live_trading`; no out-of-band `adapter.apply_config_enable(True)` requirement.

### RR4-002 — no naked safety-state reset

- Production SAFE_MODE may clear only after successful authoritative reconciliation.
- Remove/privatize/gate raw `ExecutionEngine.clear_safe_mode()` for production reachability.
- Broker disconnect recovery must perform authoritative reconnect/account/session verification + reconciliation before health can become true.
- A direct `mark_connected()` flag flip must not restore production order capability.

### RR4-003 — exposure reconstruction must not parse raw QMT time as ISO

Current code skips non-ISO broker `order_time`; native QMT integer timestamps therefore can undercount.

Use durable TGrid intent/journal trade dates (`OrderIntent.created_at` or explicit trade-date field) joined to broker orders. Unknown-date managed orders must fail closed or count conservatively, never be silently skipped.

### RR4-004 — bind exposure persistence to production DB lifecycle

- Real production factory must use validated persistent TGrid database lifecycle, not arbitrary `db_conn` / `:memory:`.
- Prefer normal migration/versioned schema for `daily_exposure` rather than ad-hoc table creation.
- Keep in-memory/test injection only in clearly internal/test assembly helpers.

### RR4-005 — exact canonical head metadata

Keep implementation SHA separate from actual pushed head. Final state must use exact GitHub SHAs and all control docs must agree.

## Frozen — DO NOT REOPEN WITHOUT REGRESSION

- Gate 5 independent PASS.
- BrokerPort live execution chain.
- single XtQuant order/cancel bridge.
- native int order-id conversion.
- strict bounded broker queries / None fail-closed.
- UNKNOWN -> reconciliation failure/SAFE_MODE.
- duplicate-match recovery rejection.
- mandatory startup reconciliation logic itself.
- immutable real EventQueue callback path.
- EventQueue lifecycle FAILED/STOPPING/STOPPED health read.
- kill switch blocks new orders but allows cancel/query.
- Reservation + OrderIntent before send + idempotency.
- pre-send BUY exposure reservation.
- executor/adapter finite-number hardening.
- legacy Core authority guard.

## Required SELF_CERTIFIED evidence

1. Positive production-shaped fake live-session lifecycle test.
2. Wrong env/path/account + zero/multiple account + connect/subscribe failure/wrong-type FI.
3. `global.live_trading` false-by-default and explicit-true wiring tests.
4. SAFE_MODE cannot clear without successful reconciliation.
5. disconnect cannot clear without verified reconnect/recovery.
6. durable exposure restart with native QMT-style integer `order_time`; no undercount.
7. production persistent DB/migration lifecycle test.
8. full unit regression + compileall + capability scan.
9. no real order/cancel invocation.

## Boundary

```text
live_trading_allowed=false
Gate 6=BLOCKED
Gate 7=BLOCKED
```

No real TGrid order or cancel. No live-soak claim.

## Stop / Handoff

After fixes:

```text
state = AUDIT_READY_PRELIVE
authorized_next = AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER
```

Push normally and STOP. First real order still requires independent Node B PASS + explicit user authorization.
