# TGrid → qmt-execution-core 0.4 Integration Plan

> Date: 2026-08-16  
> Status: AUTHORIZED FOR IMPLEMENTATION  
> TGrid baseline: `bf6cb86814da359544ba734ffc8ae9a82a9d9047`  
> Locked public Core 0.4: `acf20d9fe5cf2aede3cc0ad0e8936ecb0c5b2692`  
> Core PR: `smhe00/qmt-execution-core#3` — merged  
> Core architecture audit: PASS  
> Core 3-process formal verification: PASS

## 1. Objective

Migrate the already-cut-over TGrid execution composition from qmt-execution-core 0.3.1 to the independently audited Core 0.4 release baseline without reintroducing duplicate execution authority.

The resulting deployment must support the account model:

```text
same broker account
+ shared cash pool
+ exclusive owner per symbol
+ independent strategy processes may execute different symbols concurrently
```

TGrid itself remains one-active-execution-at-a-time per `ExecutionEngine`/runtime. Cross-strategy concurrency comes from multiple independent Core runtimes/sessions, not a TGrid multi-order engine.

## 2. Locked dependency

Update the exact git pin from:

```text
937e6a4a1cbd54df960f9bde3ca2e91d6bc19c79
```

to exactly:

```text
acf20d9fe5cf2aede3cc0ad0e8936ecb0c5b2692
```

Do not pin a branch, tag, moving ref, or local absolute path.

## 3. Production composition invariant

Preserve Iteration 15:

```text
exactly one MiniQmtRuntime
→ exactly one runtime-owned ExecutionSession
→ TGrid ExecutionEngine binds to runtime.session
```

For Core 0.4 the runtime session is expected to be `CoordinatedExecutionSession` whenever account coordination is enabled. Do not wrap it in a second `ExecutionSession`.

Required identity test:

```python
engine.session is runtime.session
```

and one TGrid submit must still produce exactly one broker submit call.

## 4. Account-level coordination

### 4.1 Canonical coordination DB

Production/shared mode must receive one explicit **account-level** `coordination_path` that is common to every strategy process sharing that broker account.

Do not default it to a strategy-specific journal/database path.
Do not create one independent coordination DB per strategy.
Do not silently run shared mode without a coordinator.

The path/configuration is a safety-critical deployment invariant. Deleting/splitting/recreating this DB while unresolved orders exist is not automatic recovery.

### 4.2 Runtime mode

Production multi-process-capable composition must use:

```text
runtime_lock_mode = "shared"
coordination_path = canonical account-level DB
```

The previous qmt-path-wide exclusive runtime lock must not globally block another valid strategy/runtime on a different owned symbol.

Existing `exclusive` mode may remain available for explicitly single-writer test/compatibility use, but must not be mistaken for the final multi-strategy deployment mode.

### 4.3 Symbol claim

Core owns the cross-process `(account_key, symbol)` claim.

TGrid must not duplicate or override this with another reusable execution lock.

Acceptance:

```text
TGrid-A / symbol X WORKING
TGrid-B / symbol X submit -> local REJECTED, broker call 0

TGrid-A / symbol X WORKING
Other strategy / symbol Y submit -> may reach WORKING concurrently
```

## 5. Shared cash

Core 0.4 owns the final cross-process account-level BUY cash reservation gate.

TGrid must provide an explicit conservative `CashRequirementEstimator`; no implicit `qty * price` fallback is allowed for coordinated BUY.

At minimum configure/document:

- order notional;
- expected transaction cost buffer;
- market/account-specific temporary withholding if applicable;
- FX/rounding buffer if applicable;
- safety buffer.

Every BUY must use Core's fresh authoritative broker asset query before atomic reservation.

### TGrid business reservation remains local

TGrid's existing SQLite `OrderIntent + Reservation + DailyExposure` remains the TGrid business ledger and is still persisted by the project sidecar.

It is **not** the cross-project shared-cash authority.

Final ordering must be:

```text
Core durable execution intent
→ Core account-level symbol/cash coordination COMMIT
→ TGrid OrderIntent/Reservation/DailyExposure sidecar COMMIT
→ broker submit
```

Both layers may retain reservations for different purposes; neither may manufacture available cash. Core account-level reservation is the final cross-process authorization gate.

## 6. State/finality mapping

Use Core 0.4 `ExecutionFinality` semantics explicitly.

TGrid business ledger must preserve recoverability for every non-resolved Core execution:

- `UNKNOWN` -> nonterminal TGrid status;
- `CANCEL_REJECTED` -> nonterminal;
- `FAILED + unresolved_order=True / QUARANTINED` -> must not release TGrid business reservation as if broker absence were proven;
- only actual/proven Core `RESOLVED` outcomes may release account-level Core resources.

Add a table-driven Core-state/finality → TGrid business-terminality test.

At minimum retain the existing:

```text
WORKING
→ cancel rejected
→ UNKNOWN
→ WORKING
→ FILLED
```

one-submit/no-resend regression.

Add:

```text
UNKNOWN
→ recovery failure
→ FAILED / QUARANTINED
```

and assert symbol/account-level cash claim remains held.

## 7. Journal migration

Do not bypass qmt-execution-core journal source/spec hashes.

0.3.1 journal files must not be opened as 0.4 journals by disabling hash checks.

Migration procedure:

1. authoritative broker query/reconciliation under the old deployment;
2. prove no unresolved old execution remains before planned cutover;
3. archive the old 0.3.1 journal;
4. configure a new 0.4 journal path;
5. initialize/use the canonical Core 0.4 coordination DB;
6. only then start the 0.4 runtime.

Automated tests must prove an old hash-bound journal is rejected rather than silently migrated.

## 8. Session-id / runtime concurrency

Do not expose MiniQMT session-id management to strategy business code.

Use Core 0.4 bounded session-id leasing/fallback.

TGrid tests must prove, with fake XtQuant only:

- two shared runtimes on the same qmt path acquire different session ids;
- closing one runtime does not close/corrupt the other;
- one runtime restart/recovery does not mutate the other's journal/session;
- exact session-id collision fails closed or bounded fallback succeeds as specified by Core.

## 9. Required TGrid integration tests

Add production-composition tests with fake Broker/Fake XtQuant only.

### 9.1 Three independent runtime composition

Instantiate three independent TGrid/Core stacks sharing one coordination DB and account binding.

Prove:

```text
P0 symbol A -> WORKING
P1 symbol B -> WORKING
P2 symbol C -> WORKING
```

simultaneously, with three independent runtime/session authorities and no global qmt-path execution mutex blocking them.

### 9.2 Same-symbol exclusion

Two independent stacks, same account/symbol:

```text
first active
second submit rejected before broker
second broker submit count = 0
```

### 9.3 Shared-cash race

Use deterministic fake fresh broker cash = 100:

```text
P0 BUY reserve 60
P1 BUY reserve 50
```

Only one may be authorized such that account-level active reservations cannot exceed 100.

### 9.4 Quarantine isolation

One strategy becomes UNKNOWN/QUARANTINED on symbol A.

Assert:

- symbol A remains blocked;
- its Core cash reservation remains held;
- another strategy may continue on symbol B if remaining shared cash permits;
- there is no blind resend.

### 9.5 Account isolation

Same symbol on two distinct account bindings may both proceed; coordination state must not cross-contaminate.

## 10. Gate-6 / live boundary

Iteration 16 validation permits only import/help/static/fake-runtime tests.

Do **not** invoke actual MiniQMT/QMT simulation order/cancel APIs.
Do **not** invoke live order/cancel APIs.

Gate-6 scripts may be updated to accept/pass the new Core 0.4 coordination/runtime configuration, but running an integrated QMT simulation remains a separate user-authorized step.

`live_trading_allowed=false` throughout this iteration.

## 11. Capability / regression gates

Required before REVIEW_READY:

- exact Core pin = `acf20d9fe5cf2aede3cc0ad0e8936ecb0c5b2692`;
- TGrid `requires-python >=3.9` retained;
- full TGrid pytest passes;
- `compileall -q src tests scripts` passes;
- Gate-6 import/`--help` smoke passes;
- zero raw QMT submit/cancel call sites in production `src/`;
- exactly one runtime-owned execution-session authority per stack;
- coordinated sidecar ordering is proven;
- 3 independent stacks/different symbols can be active concurrently;
- same-symbol second writer is rejected before broker;
- shared cash cannot overcommit;
- UNKNOWN/CANCEL_REJECTED/QUARANTINED are non-resend/non-release states;
- fill-during-cancel -> FILLED remains green;
- disconnect/reconnect evidence gates remain green;
- no real or simulation QMT order/cancel side effect occurred.

## 12. Handoff

When complete:

```text
state = REVIEW_READY
owner = architect
authorized_next = [AUDIT_TGRID_QMT_EXECUTION_CORE_V0_4_ITER16]
live_trading_allowed = false
```

Evidence should be recorded under:

```text
work/gates/QMT_EXECUTION_CORE/TGRID_CORE_0_4_INTEGRATION_EVIDENCE_20260816.md
```
