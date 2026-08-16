# Current Task — TGrid Iteration 16 Final: Core 0.4.1 Runtime Authority Integration

## Owner

`DSH (DeepSeek Harness)` — implementation + self-review. Final independent architect audit is required before Iteration 16 acceptance.

## Status

`IN_PROGRESS`

Core Runtime Authority hardening has completed independent review and is merged. The only allowed Core production baseline is:

```text
qmt-execution-core 0.4.1
a68572decb799bcbbf1b2892fcf58ac321ce9636
```

Core PR #4 final audited head was `970758cf797a9a7b7bc2810c7e5bf789b17285a2`; the merge SHA above is the TGrid pin target.

`live_trading_allowed=false`. Do not invoke real or simulation QMT order/cancel APIs.

## Objective

Finish TGrid Iteration 16 by replacing the earlier caller-selected coordination DB integration with Core 0.4.1 production Runtime Authority resolution, while preserving the accepted Iter16 execution/concurrency behavior.

Production authority chain must be:

```text
QMT binding
  -> account_key
  -> Core OS-derived canonical Runtime Authority
  -> Authority-certified dedicated per-account DB
       (canonical path + db_uuid + authority_id)
  -> SQLiteExecutionCoordinator
  -> CoordinatedExecutionSession
  -> TGrid ExecutionEngine
```

## P1-1 Exact Core pin

Update TGrid dependency/reference from Core 0.4.0 `acf20d9...` to exactly:

```text
a68572decb799bcbbf1b2892fcf58ac321ce9636
```

Do not pin branch/tag/latest.

## P1-2 Production composition MUST use canonical Runtime Authority

TGrid production construction of shared `MiniQmtRuntime` MUST:

- set `runtime_lock_mode="shared"`;
- call `MiniQmtRuntime.connect(...)` with neither `coordinator=` nor `authority=` overrides;
- provide no `coordination_path` or `authority_root` (Core 0.4.1 production config no longer supports them);
- rely on Core's canonical OS-derived Runtime Authority and verify-only runtime resolution;
- retain one runtime-owned session -> one TGrid `ExecutionEngine` authority per strategy process.

Low-level injection seams may exist only in clearly isolated tests. Any production TGrid path using `connect(coordinator=...)` or `connect(authority=...)` is a P1 blocker because it opts out of the Runtime-Authority uniqueness guarantee.

## P1-3 Remove old DB-selection surface

Remove production plumbing that lets TGrid/strategy/operator choose the coordination DB directly, including:

- function/config arguments representing `coordination_path` / `coordination_db` for production runtime construction;
- Gate-6 normal CLI option `--coordination-db`;
- environment/config aliases that can route production around Runtime Authority.

Do not replace this with a TGrid-specific Authority path/root option.

## P1-4 Explicit operator bootstrap prerequisite

Document and test the required first-use lifecycle:

```text
qmt-execution-core bootstrap-authority --binding <binding-file>
        ↓
start TGrid shared strategy runtime
```

Normal TGrid runtime MUST NOT bootstrap or recreate a missing Authority/DB.

If Authority is missing/corrupt, or the certified DB identity/path/UUID no longer matches, TGrid startup must fail closed before any broker order/cancel side effect.

Do not add an automatic TGrid recovery path that deletes/recreates/adopts the coordination DB.

## P1-5 Preserve TGrid business/Core responsibility split

Core Authority/coordination owns:

- account coordination-domain identity;
- `(account_key,symbol)` unresolved execution claim;
- shared BUY cash reservation across processes.

TGrid keeps its existing business ledger semantics (OrderIntent / Reservation / DailyExposure etc.) and project risk rules. Do not duplicate Core Runtime Authority inside TGrid.

Ordering remains:

```text
Core durable execution intent
  -> Core symbol/cash coordination COMMIT
  -> TGrid durable sidecar COMMIT
  -> broker submit
```

## Required regression/acceptance tests

At minimum prove with fake Broker/Fake XtQuant only:

1. **Production composition has no DB/root override**
   - runtime config contains no `coordination_path` / `authority_root`;
   - production `MiniQmtRuntime.connect` call receives neither `coordinator=` nor `authority=`.

2. **Bootstrap required**
   - missing Authority -> normal TGrid runtime construction fails closed;
   - no replacement Authority/DB created;
   - broker order/cancel call count remains zero.

3. **Automatic same-account convergence**
   - after one explicit bootstrap, two/three independent TGrid strategy runtimes for the same account resolve the same Authority-backed DB without being given a DB path.

4. **Different accounts isolated**
   - different authoritative account identities resolve different Authority/DB instances.

5. **DB instance replacement detection**
   - delete/recreate DB at the certified path or alter DB UUID/authority_id -> runtime construction fails closed before broker side effect.

6. **Three-process useful concurrency remains**
   - same account, three distinct symbols can reach WORKING concurrently through three independent TGrid runtimes/sessions.

7. **Same-symbol exclusion remains**
   - same account/same symbol second process rejected before broker call.

8. **Shared cash remains atomic**
   - retain the existing cash race/non-overcommit regression using the Authority-backed DB.

9. **QUARANTINED semantics remain**
   - UNKNOWN / CANCEL_REJECTED / unresolved FAILED retains symbol claim and active cash reservation; unrelated symbol can proceed if remaining cash allows.

10. **Journal cutover remains safe**
    - do not bypass Core protected source/spec hash checks;
    - 0.4.0/older journal is not silently reused as a 0.4.1 execution journal unless its established migration rule explicitly permits it.

11. **No raw broker authority regression**
    - TGrid `src/` has no direct raw QMT order/cancel authority outside the reviewed Core adapter/runtime path.

## Validation gate

Run and record:

```text
full TGrid pytest
compileall
Core exact-pin verification
capability/raw-QMT scan
three-runtime Authority-backed fake integration
same-symbol / shared-cash / quarantine regressions
startup failure matrix for missing/corrupt/recreated Authority DB
```

Also run the installed/pinned Core verification if the TGrid environment supports it:

```text
qmt-execution-core verify
```

No real or simulation QMT order/cancel during implementation or validation.

## Accepted regression baseline

Preserve the earlier Iter16 functional baseline (`bef47b3f4828937ad7dbda519d70d3df24a19657`, 913-test self-certified result), including:

- one runtime/session execution authority per strategy process;
- coordinate -> TGrid sidecar -> broker ordering;
- explicit `CashRequirementEstimator`;
- UNKNOWN/CANCEL_REJECTED/FAILED+QUARANTINED non-resend/non-release;
- safe journal cutover;
- three-runtime distinct-symbol concurrency;
- same-symbol exclusion;
- shared-cash non-overcommit;
- quarantine/account isolation;
- bounded session-id leasing.

## Handoff

When implementation is complete:

```text
state = REVIEW_READY
owner = architect
authorized_next = [AUDIT_TGRID_CORE_0_4_1_RUNTIME_AUTHORITY_INTEGRATION_ITER16]
reference_commit = a68572decb799bcbbf1b2892fcf58ac321ce9636
live_trading_allowed = false
```

Provide exact implementation commit, test counts, changed production call sites, proof that Gate-6 no longer exposes DB selection, and confirmation that no real/simulation QMT order/cancel API was invoked.
