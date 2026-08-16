# Architect Audit — TGrid → qmt-execution-core — Iteration 15

Status: **CHANGES_REQUIRED**

Reviewed TGrid commit: `67de19f970a5fc5079df8110ad60fc7c597d600e`
Reviewed public core: `qmt-execution-core 0.3.1 @ 937e6a4a1cbd54df960f9bde3ca2e91d6bc19c79`

No real or simulation QMT order/cancel is authorized. `live_trading_allowed=false`.

## Findings

### P1-1 — Production composition is not closed: two execution authorities are otherwise required

`build_qec_runtime()` constructs a `MiniQmtRuntime`, which already owns its `ExecutionSession`, guard, journal/mutex, sidecar hooks and broker runtime. `ExecutionEngine.__init__()` independently constructs another `ExecutionSession` around a broker and has no supported path to consume the already-owned runtime/session.

This leaves only two bad production choices:

1. call `MiniQmtRuntime.submit/poll/cancel` directly and bypass TGrid `ExecutionEngine` orchestration; or
2. pass the runtime broker into `ExecutionEngine`, creating a second session / second execution authority around the same MiniQMT transport.

Both violate the intended cutover architecture. There must be exactly **one** execution-session authority for the QMT runtime.

Required fix: introduce a production composition surface that binds TGrid orchestration to the **same** session owned by `MiniQmtRuntime`. A recommended TGrid-local solution is a small composite/facade (e.g. `TGridQecStack`) returned by a builder that exposes `runtime` + an `ExecutionEngine`/orchestrator using `runtime.session` rather than creating another session. If `ExecutionEngine` accepts an injected session, it must not create its own journal/mutex/session and must have explicit ownership/close semantics so only the runtime owns final transport/session teardown.

Acceptance tests must prove:

- exactly one `ExecutionSession` instance owns the execution lifecycle for one MiniQMT runtime;
- TGrid `send_buy/send_sell/poll/cancel/recovery` go through that same session;
- TGrid sidecar and evidence source are bound once, not duplicated;
- one fake broker submit produces exactly one broker-side call;
- closing the composite releases the runtime/session exactly once;
- no route exists that accidentally activates both legacy/new authorities (legacy raw bridge is already deleted).

Do not modify the public core for this unless a TGrid-local composition is demonstrably impossible.

### P1-2 — Recoverable public states must never terminalize the TGrid ledger

Iteration 14 fixed `TradeState.UNKNOWN`, but `snapshot_status_to_tgrid()` still maps `TradeState.CANCEL_REJECTED` to terminal TGrid `OrderStatus.UNKNOWN`. In the public state machine, `CANCEL_REJECTED` is explicitly recoverable to WORKING/PARTIAL/CANCELLING/FILLED/CANCELLED/REJECTED/FAILED.

Required invariant:

> Every public-core nonterminal/recoverable state must map to a nonterminal TGrid business status, or `apply_snapshot()` must preserve the last pending status. Only true public terminal outcomes may terminalize the TGrid intent.

At minimum:

- `CANCEL_REJECTED` must not write terminal TGrid UNKNOWN;
- add a dedicated regression: WORKING → cancel request rejected → authoritative query ambiguous/UNKNOWN → later WORKING or FILLED; same intent remains recoverable, submit count stays 1, reservation is held until true terminal and released on FILLED/CANCELLED/REJECTED;
- add a small table-driven invariant test covering all public `TradeState` values against TGrid terminality, so future state additions cannot silently reintroduce this class of bug.

### P1-3 — Gate-6 simulation runners are currently import-broken after Phase D

`scripts/gate6_sim_live.py` still imports deleted `tgrid.integrations.live_session.build_live_session`; the evidence file acknowledges the same issue. `compileall` does not detect missing imports, so the claimed green compile gate is insufficient for the next integration stage.

Required fix:

- rewrite `gate6_sim_live.py` and `gate6_sim_negative.py` onto the new qec production composition from P1-1;
- add import-only / `--help` smoke tests that exercise module imports without connecting to QMT;
- no order/cancel, no QMT simulation execution in Iteration 15;
- preserve `live_trading_allowed=false`.

### P2-1 — Phase D narrowed ExecutionEngine to one active execution globally

The old TGrid execution layer documented a narrower pending-order invariant (not two pending strategy orders for one symbol+direction). The qec-backed `ExecutionEngine` now uses one `ExecutionSession` and explicitly refuses a second send while any order is active.

This may be acceptable for the current personal low-frequency TGrid design, but it is a behavioral narrowing and therefore cannot be silently called full equivalence.

Required action: choose one and record evidence:

A. prove from the current TGrid scheduler/orchestration that one `ExecutionEngine` can never require more than one active order at a time, and declare `single-active-order-per-engine` an explicit accepted design constraint; or

B. if current TGrid behavior requires concurrent active intents, preserve that behavior without weakening public-core safety.

Do **not** start the broader multi-strategy/multi-session public-core roadmap in this iteration. That is a later architectural task.

## Re-run gates

After fixes:

- full TGrid pytest;
- `compileall -q src tests scripts`;
- import smoke for both Gate-6 runners;
- zero raw `order_stock/order_stock_async/cancel_order_stock/cancel_order_stock_async` call sites under TGrid `src/`;
- production-composition fake test proving one and only one `ExecutionSession` authority;
- fill-during-cancel → FILLED regression;
- transient UNKNOWN → recovery → FILLED regression;
- cancel-rejected/ambiguous → later recovery regression;
- evidence negative matrix remains green;
- qmt-execution-core remains exact-pinned to `937e6a4...` unless a separately justified public-core change is required;
- explicit statement: no real or simulation QMT order/cancel invoked.

## Handoff

When complete:

```text
state = REVIEW_READY
owner = architect
authorized_next = [AUDIT_TGRID_QMT_EXECUTION_CORE_INTEGRATION_ITER15]
live_trading_allowed = false
```
