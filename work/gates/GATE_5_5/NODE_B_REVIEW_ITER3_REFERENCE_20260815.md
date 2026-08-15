# Gate 5.5 Audit Node B — Iteration 3 Reference-Conformance Review — 2026-08-15

## Verdict

`CHANGES_REQUIRED` — but the review scope is now deliberately narrowed to deviations from the already validated miniQMT live reference implementation.

Audit target TGrid `main` snapshot:

```text
2146f09e689ed2fc07c943e2bf7cd2a7609a8a2e
```

Iteration-3 implementation commit:

```text
469116c83ca94d4b93a0f0aefb50ec687450d15d
```

Golden QMT reference repository:

```text
https://github.com/smhe00/reverse_repo
reference commit: c9ecc701d9b1c47d6a8d03539b482368741204a3
```

The independent auditor initially reviewed part of Iteration 3 against the TGrid Gate-1 boundary plus XtQuant interface documentation. The user then identified `smhe00/reverse_repo` as the actual production miniQMT reference. This review supersedes any broader speculative findings from that partial review. From this point forward, QMT execution semantics should be compared against the pinned reference implementation first, not rediscovered from scratch.

Gate 5 remains independently PASS. Gate 6 / Gate 7 remain BLOCKED. `live_trading_allowed=false` remains mandatory. No real TGrid order/cancel invocation is authorized.

## Iteration-3 items independently accepted / frozen

The following previous Node-B findings are materially closed and should not be reopened unless a regression appears:

1. **Native XtQuant order-id contract** — fake XtQuant ids are now positive native ints; TGrid serialization is string; the bridge performs validated decimal string -> native int conversion before cancel/query. This aligns with `reverse_repo`, whose `OrderView.order_id` and live `order_stock/cancel_order_stock` flow use native ints.
2. **UNKNOWN broker status** — `ExecutionEngine.poll_order()` now raises reconciliation error and enters SAFE_MODE instead of silently retaining SUBMITTED; startup recovery rejects UNKNOWN and multiple key/remark candidates.
3. **Basic callback isolation** — the concrete XtQuant callback path now emits immutable data-only events into the real TGrid `EventQueue`; no engine/store/order-capable adapter is held by the callback handler.
4. **BUY daily exposure pre-reservation** — submitted BUY notional is booked before broker send, closing the specific broker-accepted / ledger-not-yet-written crash window.
5. **Core finite-number hardening** — executor price/cash/reservation NaN/Inf rejection now occurs before durable OrderIntent/Reservation mutation.
6. **BrokerPort architecture, kill-switch cancellation behavior, Reservation-before-send, idempotency, legacy Core guard and the single audited XtQuant order/cancel bridge** remain accepted from earlier iterations.

These fixes are real. Iteration 4 must not rewrite them merely to create another review cycle.

## Why reference conformance matters

`reverse_repo` already contains the miniQMT execution behaviors TGrid is trying to reproduce safely:

- strict broker-query retry semantics where `None` never becomes an empty success;
- native integer order ids at the QMT boundary;
- all known/unknown order-status classification;
- exact environment + QMT-path + account fingerprint binding and retrying account discovery;
- durable intent/journal before submission and deterministic restart recovery;
- callbacks used only as wake/update signals while broker queries remain authoritative;
- current-session/trading-date validation before live execution;
- a real small-cap live certification path.

The remaining Node-B work is therefore not open-ended hardening. It is a finite conformance pass against these established patterns.

## Remaining reference-conformance blockers

### NODEB-RR-001 — P0: production live bootstrap bypasses the validated account/environment binding path

Current TGrid `build_live_stack()` accepts arbitrary injected `trader` and `account` objects and labels the result production-shaped. This is useful for tests, but it is not yet a production live construction path.

The reference implementation does more before any trade-capable path becomes usable:

- instantiate/connect the trader from the selected QMT userdata path;
- distinguish live vs simulation path;
- validate the configured QMT-path fingerprint;
- discover account infos/statuses through strict queries;
- select exactly one normal securities account whose account fingerprint matches the binding;
- subscribe that exact account;
- persist only non-sensitive account label/environment verification, never plaintext account ids.

TGrid Gate 1 already implemented closely related account-binding logic. The new live bootstrap currently bypasses it.

Required:

1. Keep dependency-injected `build_live_stack()` as a test/internal assembly helper if useful.
2. Add one **production live-session factory** that reuses the hardened Gate-1 / `reverse_repo` account-binding semantics rather than accepting an arbitrary raw account object.
3. The production factory must bind environment, QMT path and exactly one normal securities account before returning any order-capable stack.
4. Production order capability must be unreachable if account/path/environment verification fails or is ambiguous.
5. Tests must prove wrong environment, wrong QMT path fingerprint, zero/multiple bound accounts and abnormal account status fail before any order capability is enabled.

Do not reimplement account binding from scratch if existing Gate-1/reference code can be safely shared or extracted.

### NODEB-RR-002 — P0: strict QMT query semantics from the reference implementation were not reused

`reverse_repo` has a single `strict_query()` pattern: exceptions and `None` are retried; after the bounded attempts the result is `BrokerQueryAmbiguous`. `query_all_orders_strict()` explicitly calls `query_stock_orders(account, False)`, and `query_order_strict()` uses native integer `query_stock_order(account, order_id)`.

Current TGrid `XtQuantBrokerBridge` directly calls `query_stock_orders()` / `query_stock_trades()` and then iterates the result. A `None` result can therefore escape as an untyped Python iteration failure instead of the already-proven bounded fail-closed query contract.

Required:

1. Port/reuse one strict-query helper with bounded retry semantics matching the reference behavior.
2. `None` must never mean empty success.
3. `query_order`, `query_orders`, `query_trades` and any account/recovery query used by the live path must surface a typed broker ambiguity/disconnection failure after bounded retries.
4. Prefer the native exact-order query for `query_order` where available; otherwise an all-orders scan must itself be strict and uniquely matched.
5. Add FI for `None`, transient exception -> success, persistent exception, empty-list success, and duplicate/ambiguous match.

This is not a new policy invention; it is a regression relative to the pinned reference behavior.

### NODEB-RR-003 — P0: startup order recovery is optional and SAFE_MODE can be cleared without proving reconciliation

Current `LiveStack.activate()` accepts `reconcile_open_intents=None`. The Iteration-3 positive activation test calls `activate(token=...)` with no order/intent reconciliation at all. Therefore exposure reconstruction + runtime token can activate new-order capability even when restart recovery was skipped.

Also `ExecutionEngine.clear_safe_mode()` is an unrestricted public state flip. A caller can clear UNKNOWN/ambiguous SAFE_MODE without first proving the broker/local state is resolved.

The reference implementation does not treat restart recovery as optional: an existing nonterminal journal re-enters a recovery state, broker state is queried, unresolved submission outcomes remain unresolved/safe-halted, and state-machine transitions — not a naked boolean clear — control recovery.

Required:

1. Production `activate()` must always perform order/intent recovery; it must not accept a `None` recovery path.
2. Runtime confirmation must occur only after recovery is complete.
3. `UNKNOWN`, duplicate matches, query ambiguity, `UNMATCHED_BROKER_ORDER`, and unresolved `INTENT_ONLY` must block activation until explicitly reconciled.
4. Replace unrestricted `clear_safe_mode()` on the production path with a reconciliation-driven transition/capability that can clear SAFE_MODE only after a successful authoritative broker/local reconciliation.
5. Add restart tests proving activation cannot skip recovery and cannot resume simply by flipping a flag.

### NODEB-RR-004 — P0: daily-exposure persistence/session binding is still an abstract convention, not a production-proven journal

Iteration 3 improved the exposure algorithm but the production persistence boundary is still incomplete:

- `exposure_store` is an arbitrary object; tests use `_DictStore`, which is in-memory and not durable;
- there is no audited concrete SQLite/file-backed production exposure store in the live bootstrap;
- `roll_day(new_trade_date, session_date=None)` still permits an arbitrary valid future date when the optional trusted session argument is omitted;
- exposure reconstruction depends on broker `order_time` formatting, while the already-proven reference uses its own durable trade-date journal/remark namespace instead of relying on a string prefix representation of broker timestamps.

The reference executable binds its journal to the command trade date, requires the requested trade date to equal the current local calendar date, checks the exchange trading calendar, persists intent before submission, and reconstructs from journal + broker orders.

Required:

1. Provide one concrete durable production exposure persistence implementation, preferably backed by TGrid's existing SQLite/ExecutionStore rather than a second ad-hoc store.
2. The production bootstrap must construct that store itself; callers must not be able to substitute an in-memory fake in the real path.
3. Day rollover/reset must be derived from a trusted current session/trading date. `session_date` must not be optional on any reset-capable production path.
4. Do not key safety-critical same-day reconstruction on an assumed string format of raw QMT `order_time`; use TGrid durable intent/journal dates, or explicitly normalize and test the native QMT representation.
5. Add restart tests using the concrete durable store, not `_DictStore` only.

### NODEB-RR-005 — P0: EventQueue health can still be stale after worker failure or broker disconnect

The callback wiring itself is accepted, but the health gate is incomplete.

`XtQuantBrokerBridge.execution_healthy` currently depends on `XtQuantCallbackHandler.healthy`. The handler flips unhealthy only when a callback enqueue attempt raises. If the TGrid EventQueue worker has already transitioned to FAILED after consuming an earlier event and no new callback arrives, handler health can remain true and a new order can pass the health check.

Similarly, `on_disconnected()` currently emits a disconnect event but does not itself mark the execution channel unhealthy before returning.

Required:

1. The live order gate must read the actual EventQueue lifecycle state (or an audited health adapter) in addition to callback-handler enqueue health.
2. Queue FAILED / STOPPING / STOPPED must reject new orders immediately, even without another callback.
3. Broker disconnect must mark execution unhealthy immediately; reconnection/recovery must be explicit before new orders resume.
4. Order/cancel error events remain data-only; they must not issue orders from callbacks.
5. Add tests for worker failure with **no subsequent callback**, disconnect followed immediately by attempted order, and explicit recovery/reconnect before health is restored.

### NODEB-RR-006 — P1: canonical SHA metadata contains a typo

`WORKFLOW_STATE.yaml` records:

```text
git_base_commit: cb7aeb660661811673b873171b76957aa5af1f07
```

but the actual previous independent audit commit is:

```text
cb7aeb600661811673b873171b76957aa5af1f07
```

Use exact GitHub SHAs only. Also record the pinned reference repository/commit in the next handoff so DSH does not lose the source of truth.

## Iteration-4 policy: final reference-conformance pass

This remediation is intentionally finite. DSH must first read the pinned `reverse_repo` reference, especially:

```text
scripts/repo_execution_core.py
scripts/gc001_live_daily_90pct_093042.py
tests/test_repo_execution_core.py
```

and TGrid's existing hardened Gate-1 runtime/account-binding code.

DSH should **reuse/extract established patterns** instead of creating parallel QMT semantics.

No new broad refactor is authorized. No cosmetic polish should delay Node B. Fix only NODEB-RR-001..006 and regressions directly caused by those fixes.

## Required self-certified evidence for Iteration 4

- full unit regression + compileall + capability scan;
- reference-conformance matrix (`reverse_repo` pinned commit -> TGrid implementation/test);
- production account/environment/QMT-path binding FI;
- strict-query `None`/retry/exception tests;
- mandatory startup recovery + reconciliation-only SAFE_MODE release tests;
- concrete durable exposure restart tests + trusted-session rollover tests;
- EventQueue FAILED-without-next-callback and broker-disconnect health tests;
- no real TGrid order/cancel invocation;
- `live_trading_allowed=false`;
- exact implementation/evidence SHA and canonical control state.

## Stop condition

After these fixes DSH must push normally, set state to `AUDIT_READY_PRELIVE`, authorize only `AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`, and STOP.

The next independent review will treat the pinned `reverse_repo` commit as the QMT behavior baseline and will not reopen already-frozen Node-B items without a concrete regression.

First real TGrid order remains prohibited until:

```text
Audit Node B = PASS
AND
explicit user authorization = YES
```
