# Architect Review — TGrid → qmt-execution-core Migration — Iteration 14

Date: 2026-08-16

## Reviewed baseline

- TGrid main reviewed at `06c26cfb5f70ffd9422c963c94bbc57f716a2458`.
- qmt-execution-core dependency: `0.3.1`, commit `937e6a4a1cbd54df960f9bde3ca2e91d6bc19c79`.
- Phase A0/A/B/C evidence is accepted as useful progress but **not yet integration-audit PASS**.
- `live_trading_allowed=false`; this task authorizes code/test work only. No real or simulation QMT order/cancel calls.

## Required fixes before destructive Phase D cleanup

### P1 — production builder must not self-certify ExecutionGuard evidence

`src/tgrid/integrations/qec_runtime.py::build_qec_runtime()` currently constructs `TGridExecutionGuard` with constant evidence such as `environment_verified=lambda: True`, `account_verified=lambda: True`, `position_verified=lambda: True`, `cash_verified=lambda: True`, `quote_verified=lambda: True`, `kill_switch_active=lambda: False`, and `exposure_ready=lambda: True`.

This is not acceptable for the production-shaped cutover path. The builder must consume real current TGrid evidence sources; it must not manufacture readiness.

Required shape:

- introduce a small TGrid-specific evidence-source object/dataclass or explicit required callables;
- at minimum supply live callables for environment/account/broker-snapshot/position/cash/quote/kill-switch/exposure-ready/exposure-used;
- no permissive defaults for safety-critical evidence in the production builder;
- fake tests may pass explicit `_ok` callables, but production construction must fail closed when evidence sources are absent/unhealthy;
- preserve the public core as the broker/session authority; do not duplicate `MiniQmtRuntime` internals in TGrid.

Add negative tests proving each critical false/unavailable evidence blocks a submit before TGrid sidecar/broker side effects.

### P1 — do not terminalize public-core recoverable UNKNOWN in the TGrid ledger

The public core defines `TradeState.UNKNOWN` as a recoverable execution state. TGrid's legacy `OrderStatus.UNKNOWN` is terminal. Current `snapshot_status_to_tgrid()` maps public UNKNOWN to TGrid UNKNOWN and `apply_snapshot()` refuses to update an existing TGrid UNKNOWN intent. That can permanently prevent a later authoritative public-core recovery (`UNKNOWN -> WORKING/PARTIAL/FILLED/CANCELLED`) from reaching the business ledger.

Fix this at the new qec adapter boundary; do **not** broadly rewrite the legacy state machine unless needed.

Required semantics:

- a transient public `TradeState.UNKNOWN` must not irreversibly terminalize the TGrid business intent;
- keep the last durable pending TGrid status (e.g. SUBMITTED/PARTIAL/CANCEL_REQUESTED) or introduce an explicitly recoverable migration-only representation with proven DB/state compatibility;
- only a public-core terminal/final recovery failure may map to terminal TGrid `UNKNOWN` if that remains the chosen business semantic;
- after a transient UNKNOWN, a later public `WORKING`, `PARTIALLY_FILLED`, `FILLED` or `CANCELLED` observation must be able to update the same intent;
- reservations must remain conservative while execution is unresolved and release only on true terminal outcomes according to TGrid rules.

Add dedicated regression: `SUBMITTED -> public UNKNOWN -> authoritative recovery WORKING -> FILLED`, with the TGrid intent ending FILLED and reservation released, and no second broker submit.

## Then execute Phase D

After both P1 items and their full regressions are green, remove/reduce duplicated reusable execution infrastructure from TGrid:

- generic execution state machine and verifier port;
- execution journal/mutex;
- generic BrokerPort/status DTO/recovery copies;
- raw XtQuant order/cancel/status bridge used by production;
- generic live-session/bootstrap/callback-event infrastructure now owned by qmt-execution-core.

Retain TGrid-specific:

- `ExecutionStore`, `OrderIntent`, `Reservation`, daily exposure;
- Core / StrategicExtra / T-Lot accounting;
- settlement/T+1/can_use/Core-floor and strategy risk;
- signal/anchor/VWAP/sizing/scheduling;
- SimBroker/test fakes where still useful.

`execution/executor.py` may remain only to the extent it contains TGrid-specific orchestration; generic broker lifecycle/state/recovery must delegate to qmt-execution-core.

## Acceptance gates

Before handoff:

1. Full TGrid regression passes after Phase D.
2. `compileall -q src tests scripts` passes.
3. qmt-execution-core remains pinned to exact reviewed commit unless a generic public-core fix is truly required; any public-core change requires version bump + its own full tests/verifier/wheel CI.
4. AST/capability scan: **zero raw `order_stock`, `order_stock_async`, `cancel_order_stock`, `cancel_order_stock_async` call sites anywhere in TGrid production `src/`**. After Phase D there is no legacy exception for `xtquant_bridge.py`.
5. Dedicated fill-during-cancel -> FILLED still passes.
6. Dedicated transient-UNKNOWN -> recovery -> FILLED business-ledger test passes.
7. Evidence-source negative matrix proves no constant/self-certified production guard path remains.
8. Old-module -> public-core/retained-module mapping updated to final disposition.
9. No real or simulation QMT order/cancel invoked during this iteration.
10. `live_trading_allowed=false` remains unchanged.

## Handoff

When complete:

```text
state = REVIEW_READY
owner = architect
authorized_next = [AUDIT_TGRID_QMT_EXECUTION_CORE_INTEGRATION]
```

Provide exact TGrid commit, exact qmt-execution-core commit, test counts, capability-scan result, and a concise deletion/retention map.
