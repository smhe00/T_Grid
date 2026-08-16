# Current Task — TGrid → qmt-execution-core — Iteration 15

## Owner

`DSH (DeepSeek Harness)` — implementation + self-review. All implementation evidence remains SELF_CERTIFIED until architect audit.

## Status

`IN_PROGRESS` — architect review of `67de19f970a5fc5079df8110ad60fc7c597d600e` returned **CHANGES_REQUIRED**.

Authoritative review:

```text
work/gates/QMT_EXECUTION_CORE/ARCHITECT_AUDIT_ITER15_20260816.md
```

Public core remains pinned to:

```text
qmt-execution-core 0.3.1
commit 937e6a4a1cbd54df960f9bde3ca2e91d6bc19c79
```

`live_trading_allowed=false`. Do not invoke real or simulation QMT order/cancel APIs.

## Required work

### P1-1 Close the production composition

`MiniQmtRuntime` already owns an `ExecutionSession`; `ExecutionEngine` must not create a second execution authority around the same runtime/broker.

Implement a TGrid-local production composition/facade so TGrid orchestration uses the **same `runtime.session`** owned by `MiniQmtRuntime`. Explicitly define session/transport close ownership. Prove one fake submit causes exactly one broker call and there is exactly one execution-session authority.

### P1-2 Preserve recoverability of every nonterminal public state

`TradeState.CANCEL_REJECTED` is recoverable in qmt-execution-core and must never terminalize the TGrid business ledger as `OrderStatus.UNKNOWN`.

Add the dedicated regression:

```text
WORKING
→ cancel request rejected
→ authoritative query ambiguous / public UNKNOWN
→ later WORKING or FILLED
```

Same intent must remain recoverable; broker submit count remains 1; reservation remains held until a true terminal outcome and releases on FILLED/CANCELLED/REJECTED. Add a table-driven public-state/TGrid-terminality invariant test.

### P1-3 Repair Gate-6 runners after Phase D

Rewrite:

```text
scripts/gate6_sim_live.py
scripts/gate6_sim_negative.py
```

onto the new qec production composition. They currently import deleted `build_live_session`.

Iteration 15 permits only import/`--help` smoke tests. Do not connect for order execution and do not send/cancel any simulation or live order.

### P2-1 Resolve the single-active-order compatibility question

Phase D now makes one `ExecutionEngine` one-active-execution-at-a-time. Either:

- prove the current TGrid scheduler guarantees this and document it as an accepted design constraint; or
- preserve the prior required concurrent-intent behavior without weakening public-core safety.

Do not start the broader multi-strategy/multi-session/async roadmap in this iteration.

## Required verification

- full TGrid pytest;
- `compileall -q src tests scripts`;
- import/`--help` smoke for both Gate-6 runners;
- zero raw QMT order/cancel calls in TGrid `src/`;
- exactly one production `ExecutionSession` authority per MiniQMT runtime;
- fill-during-cancel → FILLED;
- transient UNKNOWN → recovery → FILLED;
- cancel-rejected/ambiguous → later recovery;
- evidence negative matrix remains green;
- qec exact pin remains `937e6a4...` unless separately justified;
- explicit evidence that no real or simulation QMT order/cancel was invoked.

## Handoff

When all items pass:

```text
state = REVIEW_READY
owner = architect
authorized_next = [AUDIT_TGRID_QMT_EXECUTION_CORE_INTEGRATION_ITER15]
live_trading_allowed = false
```
