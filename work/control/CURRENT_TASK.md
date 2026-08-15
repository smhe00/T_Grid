# Current Task — Gate 5.5 Node B Final Reference-Conformance Remediation

## Owner

`DSH (DeepSeek Harness)` — implementation + SELF_CERTIFIED review only.

## Status

`CHANGES_REQUIRED (ITERATION 4)`

This is a **finite reference-conformance pass**, not another open-ended hardening cycle.

## Independent audit source

Read first:

```text
work/gates/GATE_5_5/NODE_B_REVIEW_ITER3_REFERENCE_20260815.md
```

Audit target:

```text
2146f09e689ed2fc07c943e2bf7cd2a7609a8a2e
```

Reviewed Iteration-3 implementation:

```text
469116c83ca94d4b93a0f0aefb50ec687450d15d
```

## Golden QMT reference — mandatory

Repository:

```text
https://github.com/smhe00/reverse_repo
```

Pinned reference commit:

```text
c9ecc701d9b1c47d6a8d03539b482368741204a3
```

Read at minimum:

```text
scripts/repo_execution_core.py
scripts/gc001_live_daily_90pct_093042.py
tests/test_repo_execution_core.py
```

Also reuse TGrid's existing hardened Gate-1 runtime/account-binding implementation. Do not rediscover or independently reinvent QMT semantics that these references already establish.

## Accepted / frozen — do not reopen without a concrete regression

- BrokerPort architecture and live injection into ExecutionEngine.
- XtQuant bridge is the only real order/cancel call boundary.
- Native XtQuant int order-id handling at cancel/query boundary.
- Reservation + OrderIntent before send and duplicate client-key idempotency.
- UNKNOWN status -> reconciliation error + SAFE_MODE.
- Multiple key/remark recovery candidates rejected.
- Callback payloads are immutable/data-only and use the real TGrid EventQueue.
- Kill switch blocks new orders but allows cancel/query/cancel-all.
- BUY daily exposure is durably reserved before broker send.
- Executor and adapter reject NaN/Inf before persistence/arithmetic/broker calls.
- Legacy Core authority guard.
- No real order/cancel invocation so far.

## Authorized fixes only

### NODEB-RR-001 — production QMT session/account binding

Keep dependency injection for tests if useful, but add one production construction path that reuses established account/environment/QMT-path binding:

- verified live/simulation environment;
- verified QMT userdata path/fingerprint;
- exactly one normal securities account matching the account fingerprint;
- account subscription succeeds;
- no arbitrary raw account object can enter the production order-capable path.

Prefer extracting/reusing Gate-1 / `reverse_repo` logic rather than copying a new variant.

### NODEB-RR-002 — strict broker-query contract

Reuse/port the `reverse_repo.strict_query` behavior:

- bounded retries;
- exception or `None` => ambiguous, never empty success;
- typed failure after retries;
- empty list remains a valid empty success;
- exact order query uses the native int order id where available;
- all-order fallback must still be strict + uniquely matched.

Cover order/orders/trades and all live startup/recovery queries.

### NODEB-RR-003 — mandatory startup recovery / reconciliation-only SAFE_MODE release

Production activation must never skip order/intent recovery.

- remove optional recovery from the production activate path;
- runtime confirmation comes last;
- UNKNOWN, query ambiguity, duplicate match, UNMATCHED_BROKER_ORDER and unresolved INTENT_ONLY block activation;
- do not allow an unrestricted production `clear_safe_mode()` flag flip;
- SAFE_MODE release must be the result of successful authoritative reconciliation.

### NODEB-RR-004 — concrete durable exposure journal + trusted session date

- provide one concrete durable production store, preferably SQLite/ExecutionStore-backed;
- production bootstrap constructs it; test fakes remain test-only;
- no reset/day-roll from an arbitrary caller-provided future date;
- production rollover must bind to a trusted current session/trading date;
- avoid safety-critical dependence on an assumed string format of raw QMT `order_time`; use durable local trade-date state or explicitly normalized/tested native timestamps.

### NODEB-RR-005 — EventQueue / broker execution health

- new-order health gate must observe actual EventQueue lifecycle, not only whether the last enqueue raised;
- queue FAILED/STOPPING/STOPPED blocks new orders even if no subsequent callback arrives;
- broker disconnect marks execution unhealthy immediately;
- explicit reconnect + reconciliation is required before health returns.

Callbacks remain enqueue-only.

### NODEB-RR-006 — exact control metadata

Correct the previous-audit SHA typo:

```text
wrong: cb7aeb660661811673b873171b76957aa5af1f07
right: cb7aeb600661811673b873171b76957aa5af1f07
```

Record the pinned `reverse_repo` repository + commit in the handoff/report.

## Required SELF_CERTIFIED evidence

1. Full unit regression.
2. `compileall`.
3. Capability scan: exactly the audited bridge order/cancel call sites, none elsewhere.
4. A short reference-conformance matrix mapping pinned `reverse_repo` behavior to TGrid code/tests.
5. Wrong account/environment/path FI.
6. Strict-query `None`, transient exception->success, persistent exception, empty-success FI.
7. Mandatory-recovery and reconciliation-only SAFE_MODE-release FI.
8. Concrete durable exposure restart + trusted-session rollover FI.
9. EventQueue FAILED with no subsequent callback + broker disconnect FI.
10. No real order/cancel invocation.
11. `live_trading_allowed=false`.
12. Exact implementation SHA + metadata consistency.

## Forbidden

- real TGrid order invocation;
- real TGrid cancel invocation;
- Gate 6 tiny-capital run;
- enabling `live_trading_allowed`;
- broad refactor outside NODEB-RR-001..006;
- cosmetic work that delays Node B.

## Stop / handoff

After fixes:

1. push normally to `main`;
2. set state `AUDIT_READY_PRELIVE`;
3. record exact implementation/evidence SHA;
4. authorize only `AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`;
5. STOP.

First real TGrid order remains prohibited until:

```text
Audit Node B = PASS
AND
explicit user authorization = YES
```
