# Current Task — Gate-6.1 Core Simulation Command / Lifecycle Coverage

## Authorization

The user explicitly authorized an additional **QMT simulation-only** validation pass on 2026-08-17 after Gate-6 simulation PASS.

Goal: exercise as much of the real `qmt-execution-core 0.4.1` operator/runtime flow as is naturally usable against the simulation account, without forcing difficult broker corner cases.

This is **not** live/real-money authorization.

Locked baselines:

```text
TGrid implementation : 1790812bb7ef7f6ceb35b2dcc18da49dabfc7451
Core 0.4.1           : a68572decb799bcbbf1b2892fcf58ac321ce9636
Gate-6 simulation    : PASS_GATE6_SIMULATION
```

`live_trading_allowed=false` remains a hard invariant.

## Principle

Test normal Core flows deeply on the real QMT simulation runtime. Do not manufacture rare broker behavior just to tick boxes.

Classify each item as:

```text
PASS      exercised successfully
FAIL      exercised and violated expected semantics
SKIPPED   not naturally/safely constructible in the current simulation environment
```

`SKIPPED` is acceptable for difficult corner cases if the reason is recorded. Do not increase broker side effects merely to force an edge state.

## A. Core CLI — all public commands MUST be exercised

Core 0.4.1 exposes four public CLI subcommands. Run all four:

### A1. `verify`

```text
qmt-execution-core verify
```

Require release formal verification PASS and record the final summary/hashes.

### A2. `create-binding`

Run against the **simulation** QMT account/path only.

- create a fresh temporary fingerprint-only binding;
- compare environment/account_type/account_id_sha256/qmt_path_sha256 with the already accepted simulation binding;
- do not commit plaintext account id or local paths.

### A3. `bootstrap-authority`

Run using the fresh simulation binding.

- existing Authority must resolve to the already established account coordination domain;
- run twice and prove idempotency: same `account_key`, `authority_id`, `coordination_db_uuid`, canonical DB identity;
- it must not create a second coordination domain.

### A4. `hash-token`

Run with a disposable non-secret test string only.

- verify deterministic SHA-256 output;
- do **not** feed the result to any live gate;
- this is CLI coverage only and does not authorize/enable live trading.

## B. Real simulation runtime — MUST exercise no-side-effect flows

Using the production TGrid/Core 0.4.1 shared Runtime-Authority composition:

1. connect/build/open a simulation runtime;
2. confirm the resolved account is the accepted simulation binding;
3. exercise broker/account read paths that are available in the current adapter:
   - `query_asset`;
   - `query_positions`;
   - `query_orders`;
   - `query_trades`;
   - query the known Gate-6 broker order if available;
4. close cleanly and reopen with a fresh strategy runtime;
5. verify session-id lease behavior with two concurrent simulation runtimes if naturally supported:
   - distinct session IDs;
   - closing one does not invalidate the other;
   - no broker order is required for this test;
6. verify Runtime Authority is verify-only on ordinary startup and keeps the same certified DB identity.

Sanitize evidence: do not persist plaintext account id, balances, full local paths or other sensitive broker data. Record only success/failure and safe fingerprints/counts.

## C. Lifecycle coverage with bounded simulation broker side effects

The already accepted Gate-6 evidence covers:

```text
submit -> poll -> FILLED -> reconcile -> RESOLVED resource release
```

Do not repeat that fill only for coverage.

Use at most **two additional** simulation BUY orders total for Gate-6.1, each:

```text
environment : simulation only
symbol      : 510300.SH unless a different allowlisted symbol is strictly required
qty         : 100 shares
cash cap    : <= 5000 CNY per order
```

Maximum new side effects for this task:

```text
simulation order submits <= 2
simulation cancels       <= 2
live/real order/cancel    = 0
```

### C1. Preferred single-order restart/recovery/cancel scenario

If the simulation broker permits a valid non-marketable/working limit order without unsafe guessing:

1. obtain a fresh quote and legal price limits;
2. submit one valid 100-share BUY intended to remain non-terminal briefly;
3. require a real broker order id and observe ACCEPTED/WORKING (or equivalent nonterminal state);
4. while the broker order is still unresolved, close the strategy runtime **without submitting another order**;
5. reopen using the same durable journal / same account Authority;
6. verify recovery/reconciliation finds the existing broker order and does not blind-resend;
7. poll/query it;
8. if still unresolved, call the reviewed cancel path;
9. re-query/reconcile until authoritative terminal state or bounded ambiguity;
10. verify claim/cash reservation release only when finality is RESOLVED.

This one order should, when possible, cover:

```text
submit
poll
close/restart
open/recovery
reconcile existing order
cancel
post-cancel query/reconcile
resource finality
```

If the order unexpectedly FILLS before restart/cancel, record PASS for the portions actually exercised. A second 100-share order may be used **only once** to try the missing normal cancel path. Do not keep retrying to force it.

### C2. `next_cycle`

After an authoritative terminal lifecycle, exercise the Core/TGrid next-cycle path with no new order:

- machine returns to the allowed next-cycle state;
- used client/order identity protection remains intact;
- no implicit broker submit occurs.

### C3. Same-symbol coordination while a real simulation order is unresolved

If C1 obtains a stable unresolved order, opportunistically open a second strategy runtime for the same simulation account and attempt the same symbol through the normal TGrid/Core path.

Expected:

```text
second request rejected before broker submit
first broker order remains the only broker order for that attempt
```

This is optional if C1 cannot maintain a stable unresolved state. Do not create extra broker orders merely to force this condition.

## D. Best-effort runtime flows — do not force

Attempt only when a clean/safe mechanism exists in the local simulation environment:

- `recover_after_disconnect` after a controlled transport disconnect;
- partial fill followed by cancel/reconcile;
- broker cancel rejection followed by later recovery;
- UNKNOWN/ambiguous observation recovery;
- active-order crash/restart beyond the clean close/reopen scenario.

If the only way to create these states is to tamper with QMT, race the broker, repeatedly place orders, corrupt files, or modify production code, mark them `SKIPPED` with reason.

Do not deliberately corrupt the established Runtime Authority or coordination DB for this task. Identity mismatch behavior is already covered by Core/TGrid automated tests.

## E. Evidence matrix

Produce one Gate-6.1 evidence document containing at least:

| Area | Case | Result | Broker side effect | Evidence |
|---|---|---|---|---|
| CLI | verify | PASS/FAIL | none | summary |
| CLI | create-binding | PASS/FAIL | none | fingerprint match |
| CLI | bootstrap-authority x2 | PASS/FAIL | none | idempotent identity |
| CLI | hash-token | PASS/FAIL | none | deterministic hash |
| Runtime | connect/open/close/reopen | PASS/FAIL | none | lifecycle |
| Runtime | asset/position/order/trade queries | PASS/FAIL | none | sanitized |
| Runtime | session-id coexistence | PASS/FAIL/SKIPPED | none | lease evidence |
| Lifecycle | prior Gate-6 submit/poll/FILLED | PASS | already consumed | reference existing evidence |
| Lifecycle | working/restart/reconcile/cancel | PASS/FAIL/SKIPPED | bounded | trace |
| Lifecycle | next_cycle | PASS/FAIL | none | state trace |
| Coordination | same-symbol second writer | PASS/FAIL/SKIPPED | expected zero second submit | trace |
| Best effort | disconnect recovery | PASS/FAIL/SKIPPED | none or bounded | reason |
| Best effort | partial/unknown/cancel-reject | PASS/FAIL/SKIPPED | bounded | reason |

Also record totals:

```text
new simulation order submits
new simulation cancel calls
cumulative live/real calls = 0
production src changes     = 0
```

## F. Change boundary

- Do not modify `src/tgrid/` or the pinned Core implementation to make a test pass.
- A new/updated validation script under `scripts/` is allowed if needed, provided it does not create a production bypass and is included in the handoff diff.
- Documentation/evidence/control updates are allowed.
- If a real production defect is found, STOP the execution sequence, record the defect, set `CHANGES_REQUIRED`, and return for independent code review before resuming any broker-side-effect test.

## Handoff

When coverage is complete or no further natural cases are available:

```text
state = REVIEW_READY
owner = architect
authorized_next = [AUDIT_GATE6_1_CORE_SIMULATION_COMMAND_COVERAGE]
live_trading_allowed = false
```

Provide the exact command transcript summary, lifecycle matrix, new order/cancel counts, SKIPPED reasons, final Core claim/reservation state, and confirmation of zero live/real-money calls.
