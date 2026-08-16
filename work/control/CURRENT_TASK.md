# Current Task — TGrid Migration to qmt-execution-core — Iteration 13

## Owner

`DSH (DeepSeek Harness)` — implementation + self-review. All DSH evidence remains `SELF_CERTIFIED` until independent audit.

## Status

`IN_PROGRESS` — migration resumed by the user.

Migration specification:

```text
work/gates/QMT_EXECUTION_CORE/TGRID_MIGRATION_REQUEST_ITER13_20260816.md
```

Reviewed public-core starting baseline:

```text
repository: https://github.com/smhe00/qmt-execution-core
version:    0.2.1
commit:     2e222e16731bd8ce232ffba78c697245472c2094
local:      D:\gitee\miniQMT\qmt-execution-core
architect:  PASS_FOR_MIGRATION
```

This authorization is for **code migration and public-core compatibility/integration fixes only**. `live_trading_allowed=false`. Do not invoke any real or simulation QMT order/cancel API.

## Do this first — Phase A0 Python 3.9 compatibility

TGrid currently supports Python `>=3.9`. Do **not** raise it to 3.11 unless actual evidence proves 3.9 incompatible.

On Windows Python 3.9, test qmt-execution-core starting from exact `2e222e1`:

```text
pytest full suite
compileall
CLI formal verifier
wheel build
clean Python 3.9 wheel install
installed-wheel verifier outside checkout
same-process repeated mutex owner cycles
cross-process mutex contention/acquire/release
QMT-path runtime mutex contention
read-only MiniQMT smoke if xtquant is usable under Python 3.9
```

Read-only MiniQMT smoke is limited to connect/discover/subscribe/query/close. Zero `order_stock*` / `cancel_order_stock*` calls.

Also perform a static compatibility audit for actual >3.9 syntax/stdlib/packaging dependencies.

### If Python 3.9 passes

Update the public core as the next patch release, normally:

```text
qmt-execution-core 0.2.2
requires-python = ">=3.9"
CI = Python 3.9 + 3.11 + 3.12
```

Keep TGrid `requires-python >=3.9`.

### If Python 3.9 fails

Record the exact failing language/API/dependency and determine the minimum supported version from evidence. Do not silently raise the TGrid baseline.

## Phase A1 — close the durable-ledger integration seam

Do not cut over TGrid directly to `MiniQmtRuntime` yet.

Required invariant:

```text
TGrid SQLite OrderIntent + Reservation + pre-send daily exposure committed
BEFORE
any actual MiniQMT broker submit side effect
```

Add a **generic, broker-neutral, backward-compatible** public-core lifecycle/sidecar seam (or a demonstrably stronger equivalent):

```text
core durable intent persisted
→ project before_broker_submit(request) sidecar
→ BrokerPort.place_order()
```

Optional analogous pre-cancel seam is allowed.

Requirements:

- no-op default;
- synchronous execution-thread hook;
- failure before broker submit proves broker side-effect count is zero;
- no durable side effects hidden in `ExecutionGuard.verify()`;
- no UNKNOWN blind retry;
- no TGrid strategy/Core/T-Lot logic in the public repository;
- public-core source/spec verification updated where needed;
- public-core tests prove exact ordering and failure semantics;
- record final public-core version + exact commit after A0/A1.

## Phase B — TGrid adapter, legacy path retained temporarily

Implement only a thin project adapter:

- TGrid plan → public `ExecutionRequest`;
- TGrid checks → `SessionEvidence` / `PrecheckEvidence` through `ExecutionGuard`;
- TGrid SQLite intent/reservation/exposure → approved sidecar seam;
- public snapshots/normalized observations → existing TGrid ledger/T-Lot reconciliation.

Keep TGrid-specific Core/T-Lot/SQLite/daily exposure/settlement/risk/signals local.

Old and new execution authorities must never own the same QMT runtime simultaneously.

## Phase C — fake/shadow equivalence + cutover

Using fake broker/fake trader only, prove behavioral equivalence before deleting old code.

Mandatory dedicated test:

```text
cancel requested
→ fill arrives before cancel terminal
→ final state FILLED
```

After cutover, TGrid production code must have zero raw production call sites for:

```text
order_stock
order_stock_async
cancel_order_stock
cancel_order_stock_async
```

## Phase D — remove duplicated reusable infrastructure

Only after equivalence is green, remove/reduce TGrid copies of generic:

```text
state machine
execution journal/mutex
BrokerPort/recovery
QMT status normalization/raw bridge
generic live runtime/callback execution infrastructure
```

Do not delete TGrid business accounting/risk/strategy code.

## Dependency rules

- never commit `D:\gitee\miniQMT\qmt-execution-core` as a repository dependency;
- local editable install may use that path and should be documented separately;
- repository dependency must pin an exact public-core commit/version;
- retain Python >=3.9 if A0 proves compatibility.

## Required handoff evidence

- Python compatibility decision and exact evidence;
- final qmt-execution-core version + commit;
- public-core tests / compileall / verifier / wheel verification;
- Windows mutex probes on minimum supported Python;
- TGrid full regression + compileall;
- old-module → public-core/retained-module mapping;
- fake/shadow equivalence including fill-during-cancel;
- zero TGrid production raw QMT order/cancel call sites;
- explicit statement that no real or simulation QMT order/cancel was invoked.

## Handoff

When complete:

```text
state = REVIEW_READY
owner = architect
authorized_next = [AUDIT_TGRID_QMT_EXECUTION_CORE_INTEGRATION]
live_trading_allowed = false
```

Do not run integrated QMT simulation orders until independent integration audit passes and a separate simulation authorization exists.
