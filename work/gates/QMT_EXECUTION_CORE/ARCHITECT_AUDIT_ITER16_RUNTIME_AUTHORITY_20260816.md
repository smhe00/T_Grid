# Architect Audit — TGrid Core 0.4 Integration Iteration 16

> Date: 2026-08-16
> Reviewed TGrid commit: `bef47b3f4828937ad7dbda519d70d3df24a19657`
> Core runtime baseline: `acf20d9fe5cf2aede3cc0ad0e8936ecb0c5b2692`
> Result: **CHANGES_REQUIRED**

## 1. Summary

Iteration 16 successfully integrates Core 0.4 shared symbol/cash coordination, finality, bounded session-id leasing, and three-runtime fake-XtQuant concurrency. The 913-test evidence is useful and should be retained.

However, the production composition still treats `coordination_path` as caller/deployment configuration. Gate-6 exposes `--coordination-db`; `build_qec_runtime` accepts a caller-provided `coordination_path`; safety therefore still depends on every process for the same account choosing the same file.

That does not satisfy the newly frozen account Runtime Authority invariant:

```text
same authoritative account
→ one canonical Runtime Authority
→ one certified dedicated coordination DB instance
```

This is a P1 architecture blocker because two processes can still be configured as:

```text
same account_key
Strategy A -> coord-A.db
Strategy B -> coord-B.db
```

and both databases will independently authorize same-symbol/shared-cash execution.

## 2. Accepted Iter16 work

The following Iter16 results are accepted as the functional integration baseline and should not be reimplemented unless required by the Authority insertion:

- exact Core 0.4 code pin `acf20d9...` for the runtime baseline;
- one `MiniQmtRuntime` / one `runtime.session` execution authority per stack;
- `runtime_lock_mode="shared"` behavior;
- explicit `CashRequirementEstimator`;
- Core coordination COMMIT -> TGrid sidecar COMMIT -> broker ordering;
- `ExecutionFinality` aware TGrid folding;
- UNKNOWN/CANCEL_REJECTED/FAILED+QUARANTINED non-release/no-resend behavior;
- 0.3.1 journal rejection/cutover discipline;
- three fake strategy runtimes on distinct symbols concurrently WORKING;
- same-symbol exclusion;
- shared-cash non-overcommit;
- quarantine isolation;
- cross-account isolation;
- bounded session-id leasing;
- no raw QMT side-effect call sites in TGrid `src/`;
- no real/simulation QMT order/cancel invocation.

These remain regression requirements after the Authority change.

## 3. P1 blocker — coordination-domain uniqueness is not structural

Current production builder semantics are effectively:

```text
caller provides coordination_path
→ Core opens that DB
→ account_key scopes rows inside that DB
```

This proves atomicity **within one selected DB**, but does not prove uniqueness of the selected DB for an account.

Required semantics are:

```text
actual QMT account identity
→ stable account_key
→ canonical Account Runtime Authority
→ certified coordination_db_path + db_uuid
→ verify DB metadata
→ build coordinator
```

The strategy/runtime caller must not be the authority that decides the production DB path.

## 4. Required Core-first fix

This blocker belongs to public `qmt-execution-core`, not TGrid business code.

Authoritative public-Core documents:

```text
docs/CORE_0_4_1_RUNTIME_AUTHORITY_SPEC.md
docs/IMPLEMENTATION_TASK_V0_4_1_RUNTIME_AUTHORITY.md
```

Core 0.4.1 must implement:

- deterministic/canonical per-account Authority path from `account_key`;
- Authority fields including account identity, certified canonical DB path, `db_uuid`, `authority_id`;
- dedicated per-account coordination DB identity metadata;
- OS-lock-backed atomic Authority/DB bootstrap;
- DB replacement detection using persistent DB UUID;
- fail-closed mismatch handling;
- production shared-runtime resolution through Authority rather than arbitrary `coordination_path`;
- cross-process bootstrap tests + existing formal/refinement/Windows gates.

Core must be independently audited and merged before TGrid changes its production pin again.

## 5. Required TGrid follow-up after reviewed Core 0.4.1

TGrid should make only the integration delta:

1. Pin the exact reviewed Core 0.4.1 merge SHA.
2. Production `build_qec_runtime/build_tgrid_qec_stack` must use Core Runtime Authority mode.
3. Remove production responsibility for selecting `coordination_path`.
4. Remove Gate-6 `--coordination-db` as a normal production/runtime selection knob.
5. Keep test-only coordinator/authority injection clearly isolated.
6. Preserve explicit conservative `CashRequirementEstimator`.
7. Preserve every accepted Iter16 concurrency/finality/journal/session-id regression.

## 6. Required new TGrid acceptance cases

After Core 0.4.1 integration, prove with fake XtQuant:

- two TGrid strategies for the same account resolve the same Authority identity;
- they open the same Authority-certified DB path/UUID without being told the DB path independently;
- different accounts resolve different Authority files and different dedicated DB instances;
- Authority mismatch prevents stack construction before broker side effects;
- DB UUID mismatch/recreated DB at same path prevents stack construction;
- corrupted Authority prevents stack construction and does not create a fallback DB;
- existing three-runtime/different-symbol concurrency still reaches WORKING;
- same-symbol/shared-cash/quarantine invariants remain green.

## 7. Safety status

```text
live_trading_allowed = false
real QMT order/cancel = forbidden
simulation QMT order/cancel = forbidden
```

No integrated QMT simulation should run until Runtime Authority is implemented, Core independently audited/merged, and TGrid follow-up audit passes.

## 8. Verdict

**CHANGES_REQUIRED — P1 Runtime Authority blocker.**

Iteration 16 is accepted as a reusable functional baseline, but it is not accepted as the final production shared-account architecture because coordination DB uniqueness is still configuration-dependent.
