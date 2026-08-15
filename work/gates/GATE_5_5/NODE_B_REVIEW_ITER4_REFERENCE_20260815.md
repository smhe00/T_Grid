# Gate 5.5 Audit Node B — Iteration 4 Reference-Conformance Review — 2026-08-15

## Verdict

`CHANGES_REQUIRED` — final pre-live correction remains narrowly scoped to production wiring defects introduced/left open in Iteration 4. This review does **not** reopen already-frozen BrokerPort, native order-id, strict-query, Reservation/Idempotency, UNKNOWN handling, callback isolation, kill-switch, NaN/Inf, or Gate-5 behavior without a concrete regression.

Audit target:

```text
main: 082a109b343db1e662842c2768ba8a18413604cc
implementation: 7f3c667fa13fa6bb3e470b22000492aab0705b57
reference: smhe00/reverse_repo@c9ecc701d9b1c47d6a8d03539b482368741204a3
```

Gate 5 remains independent PASS. Gate 6/7 remain BLOCKED. `live_trading_allowed=false`. No real TGrid order/cancel is authorized.

## Accepted / frozen in Iteration 4

The following material items are accepted and must not be reworked without a regression:

- `XtQuantBrokerBridge` strict bounded broker queries: `None`/transient exceptions never become empty success; exact native `query_stock_order` is preferred and all-orders fallback is unique-match/fail-closed.
- `LiveStack.activate()` now always invokes startup order/intent recovery; unresolved/ambiguous recovery blocks activation.
- actual `EventQueue` FAILED/STOPPING/STOPPED lifecycle is read by the new-order health gate, including worker failure with no subsequent callback.
- concrete `SqliteExposureStore` exists and restart tests exercise a file-backed SQLite database.
- previous canonical SHA typo (`cb7aeb660...`) is corrected and the pinned `reverse_repo` reference is recorded.
- all earlier frozen Node-B items remain accepted: BrokerPort live chain, native int order-id boundary, UNKNOWN -> reconciliation failure/SAFE_MODE, duplicate-match rejection, immutable EventQueue callbacks, kill-switch cancellation, Reservation+OrderIntent before send, idempotency, pre-send BUY exposure reservation, finite-number hardening, legacy Core guard, single XtQuant order/cancel bridge.

## Remaining blockers

### NODEB-RR4-001 — P0: the new production `build_live_session()` is not actually a valid live-QMT construction path

The newly added production factory currently reuses `load_gate1_config()`. That parser is intentionally Gate-1 read-only and explicitly rejects every environment other than `simulation`. `build_live_session()` itself also defaults to `environment="simulation"`. Therefore a true live session cannot be built through this audited factory.

The runtime lifecycle is also ordered incorrectly relative to the pinned `reverse_repo` path: `_select_bound_account()` calls `query_account_infos()` / `query_account_status()` **before** `trader.start()` and `trader.connect()`. The reference starts and connects first, verifies connect result, then performs account discovery. After selection, the new factory calls `trader.connect()` and `trader.subscribe()` but ignores their return codes.

Finally, the factory does not wire TGrid's validated `RootConfig.global_config.live_trading` into the adapter. It calls `build_live_stack(..., config_live_enabled=False)` unconditionally, while taking `LiveBrokerPolicy`, `db_conn`, and the runtime confirmation token from arbitrary caller arguments. Thus there is no single audited production path from trusted TGrid configuration to the double-enable gate; callers would have to mutate `adapter.apply_config_enable(True)` outside the factory.

Required:

1. Build one true production live-session entry point that consumes validated TGrid live configuration plus the separate QMT account/path binding; do not reuse the simulation-only Gate-1 parser as if it were a live parser.
2. Preserve default OFF: `global.live_trading` missing/false must leave execution disabled.
3. Real/fake lifecycle must follow the established reference sequence: construct trader -> `start` -> `connect` (exact plain-int success) -> strict account info/status discovery -> exactly-one bound normal securities account -> `subscribe` (exact plain-int success) -> assemble bridge/adapter -> mandatory recovery -> runtime confirmation.
4. Wrong environment/path/account, nonzero or wrong-type connect/subscribe result, zero/multiple account matches must fail before any order-capable stack becomes ready.
5. Add a positive production-shaped fake test that proves the full live sequence succeeds with `live_trading=true`; the current live-session tests only prove failure cases.

### NODEB-RR4-002 — P0: reconciliation/connection safety states still have naked reset bypasses

Two low-level public state flips remain reachable from the production `LiveStack`:

- `LiveStack.engine` exposes `ExecutionEngine.clear_safe_mode()`. A caller can therefore bypass `LiveStack.reconcile_and_resume()` and clear an UNKNOWN/ambiguous SAFE_MODE without proving authoritative reconciliation.
- `XtQuantBrokerBridge.mark_connected()` simply writes the callback handler's private `_healthy=True`. It performs no `trader.connect()`, no account-status verification, no subscribe verification, and no reconciliation. The current test explicitly calls `bridge.mark_connected()` after a disconnect and then demonstrates a new order is allowed.

Required:

1. Production SAFE_MODE release must require a reconciliation capability/result that cannot be substituted by an unrestricted public flag clear. Keep any raw reset only as a test-internal/private hook.
2. Broker disconnect recovery must be an authoritative reconnect flow: verified connect + bound-account/session health + EventQueue RUNNING + recovery/reconciliation before execution health can return true.
3. A naked `mark_connected()`/equivalent must not make a disconnected production stack order-capable.

### NODEB-RR4-003 — P0: daily-exposure reconstruction still depends on raw QMT `order_time` and can undercount

`BrokerOrder.order_time` is populated by `XtQuantBrokerBridge` as `str(raw.order_time)`, i.e. it remains broker-reported data. `DailyExposureLedger.reconstruct_from_orders()` then does:

```text
if order_time is a non-empty string and not startswith(current_trade_date):
    continue
```

This directly contradicts the RR-004 requirement/comment that an unrecognized broker timestamp must be counted conservatively rather than dropped. With the native QMT integer timestamp representation serialized to a decimal string, the value will not start with `YYYY-MM-DD`, so managed broker BUY orders can be skipped during reconstruction.

Required:

1. Do not derive the safety-critical trade date from raw broker `order_time` formatting.
2. Reconstruct today's exposure from durable TGrid intent/journal dates (`OrderIntent.created_at` / explicit trade-date field) joined to authoritative broker orders by broker id / client key / remark; persisted pre-send exposure remains the lower bound.
3. If a managed broker order cannot be safely assigned to a day, fail closed or count it conservatively; never silently skip it because timestamp formatting is unknown.
4. Add FI using native integer-like QMT `order_time`, non-ISO strings, empty values, terminal orders, and broker/local matched intents proving no undercount after restart.

### NODEB-RR4-004 — P1: production durability is not yet bound to the validated database lifecycle

`SqliteExposureStore` is concrete, but `build_live_session()` still accepts an arbitrary `db_conn`; an in-memory SQLite connection is therefore still a valid input to the purported production factory. The store also creates `daily_exposure` ad hoc with `CREATE TABLE IF NOT EXISTS` instead of through TGrid's migration/version lifecycle.

Required:

- the real production entry point should derive/open the database from validated TGrid config (or require an explicitly initialized persistent database capability that cannot be `:memory:`), rather than accepting an arbitrary connection;
- integrate `daily_exposure` into the normal schema migration/verification path, or document and test an equally strict lifecycle invariant;
- retain dependency-injected/in-memory assembly only for tests/internal helpers, clearly separate from the production factory.

### NODEB-RR4-005 — P1: canonical head metadata still names the implementation parent, not current `main`

At audit time actual `main` is:

```text
082a109b343db1e662842c2768ba8a18413604cc
```

but `WORKFLOW_STATE.yaml` records `git_head_commit` as implementation commit `7f3c667...`. Keep `implementation_commit=7f3c667...`, but canonical `git_head_commit` must identify the exact pushed metadata/handoff head (or use clearly named separate fields). Final state/task/docs/report must agree.

## Iteration 5 — final production-glue correction only

DSH is authorized only to close `NODEB-RR4-001..005` and regressions directly caused by those fixes. Do not reopen frozen Node-B work. Use the pinned `reverse_repo` implementation as the lifecycle oracle and TGrid's existing validated `RootConfig` / Gate-1 account-binding primitives as reusable components.

Required evidence:

- positive + negative production-session lifecycle tests using fakes only;
- connect/subscribe exact-result FI;
- trusted `global.live_trading` double-enable wiring test (default false + explicit true path);
- SAFE_MODE cannot be cleared without successful reconciliation;
- disconnect cannot be cleared without authoritative reconnect/recovery;
- exposure restart FI with native QMT-style integer `order_time` and durable local intent dates;
- persistent DB/migration lifecycle test;
- full regression, compileall, capability scan;
- no real order/cancel; `live_trading_allowed=false`.

Stop at `AUDIT_READY_PRELIVE` and authorize only `AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`.

First real TGrid order remains prohibited until independent Node B PASS **and** explicit user authorization.
