# Current Task — TGrid → qmt-execution-core Migration — Iteration 14

## Owner

`DSH (DeepSeek Harness)` — implementation + self-review. Evidence remains `SELF_CERTIFIED` until independent audit.

## Status

`IN_PROGRESS` — architect reviewed Phase B+C and issued two required integration fixes, then Phase D cleanup.

Architect review:

```text
work/gates/QMT_EXECUTION_CORE/ARCHITECT_REVIEW_BC_ITER14_20260816.md
```

Current reusable-core dependency:

```text
qmt-execution-core 0.3.1
commit 937e6a4a1cbd54df960f9bde3ca2e91d6bc19c79
Python >=3.9
```

Prior migration evidence:

```text
work/gates/QMT_EXECUTION_CORE/TGRID_MIGRATION_EVIDENCE_20260816.md
```

## Do next

### 1. Fix production ExecutionGuard evidence

`build_qec_runtime()` must not self-certify readiness with constant `True/False` lambdas. Inject real current TGrid evidence sources/callables for environment, account, broker snapshot, position, cash, quote, kill switch, exposure readiness and exposure used. Safety-critical sources must have no permissive production defaults. Add negative tests proving false/unavailable evidence blocks before sidecar/broker side effects.

### 2. Fix recoverable UNKNOWN mapping

Public-core `TradeState.UNKNOWN` is recoverable; legacy TGrid `OrderStatus.UNKNOWN` is terminal. The qec adapter must not irreversibly write a transient public UNKNOWN into the TGrid terminal UNKNOWN state. Preserve a conservative pending business status until authoritative recovery, or use an explicitly recoverable representation. Add a dedicated regression:

```text
SUBMITTED -> public UNKNOWN -> recovery WORKING -> FILLED
```

The same TGrid intent must end FILLED, reservation released, and broker submit count remain one.

### 3. Execute Phase D only after 1+2 pass

Remove/reduce duplicated generic execution infrastructure now owned by qmt-execution-core: generic state machine/verifier port, journal/mutex, BrokerPort/status/recovery copies, raw XtQuant production bridge, and generic live-session/bootstrap/callback-event runtime. Preserve TGrid-specific store/intent/reservation/daily exposure/Core/T-Lot/settlement/risk/strategy logic and useful test fakes.

After Phase D, TGrid production `src/` must contain **zero** raw `order_stock*` / `cancel_order_stock*` call sites, including no legacy `xtquant_bridge.py` exception.

## Safety boundary

`live_trading_allowed=false`.

This task authorizes code/test migration only. Do not invoke any real or simulation QMT order/cancel API.

## Handoff

When all fixes + Phase D + full regression are complete:

```text
state = REVIEW_READY
owner = architect
authorized_next = [AUDIT_TGRID_QMT_EXECUTION_CORE_INTEGRATION]
```

Report exact TGrid/core commits, final test count, compileall, raw-call capability scan, transient-UNKNOWN recovery test, evidence-source negative matrix, and final old-module deletion/retention map.
