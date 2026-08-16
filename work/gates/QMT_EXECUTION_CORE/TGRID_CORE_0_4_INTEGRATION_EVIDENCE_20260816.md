# TGrid → qmt-execution-core 0.4 Integration Evidence — Iteration 16

> Date: 2026-08-16
> Task: `TGRID-QEC-CORE-0.4-INTEGRATION-ITER16`
> Author: DSH (implementation + self-review). All evidence is SELF_CERTIFIED
> until the independent architect audit
> (`AUDIT_TGRID_QMT_EXECUTION_CORE_V0_4_ITER16`).
> Authoritative plan: `work/gates/QMT_EXECUTION_CORE/
> CORE_0_4_TGRID_INTEGRATION_PLAN_20260816.md`.

## 0. Baseline

| Item | Value |
| --- | --- |
| TGrid implementation baseline | Iteration 15 single-authority composition (`bf6cb86`), 897 tests |
| Public Core locked version | `qmt-execution-core 0.4.0` |
| Public Core locked commit | `acf20d9fe5cf2aede3cc0ad0e8936ecb0c5b2692` (PR #3, audit + 3-process formal verification PASS) |
| TGrid dependency pin | `git+https://github.com/smhe00/qmt-execution-core@acf20d9fe5cf2aede3cc0ad0e8936ecb0c5b2692` |
| TGrid `requires-python` | `>=3.9` (retained; every `src`/`tests`/`scripts` file parses with `ast.parse(feature_version=(3, 9))`) |
| `live_trading_allowed` | `false` throughout |

## 1. Core 0.4 independent verification (fresh venv, no TGrid code involved)

A fresh venv `%TEMP%\qec_venv_v04` was created (Python 3.12.10), the locked
Core 0.4 was installed editable, and the full Core suite + release gate ran
out-of-tree from the TGrid checkout:

```text
pytest (Core 0.4)     : 88 passed   (was 66 on 0.3.1; +22 new tests)
compileall (Core src) : 0
qmt-execution-core verify (release gate):
  single-process abstract machine : 52 reachable states / 211 transitions /
                                     0 unreachable / 0 no-terminal-path /
                                     0 invariant violations /
                                     0 v0.4-finality violations
  implementation refinement       : 0 hidden runtime state mutations,
                                     0 undeclared runtime events,
                                     0 illegal observation edges
  three-process coordination      : 433,489 total reachable global states /
                                     4,461,994 interleaving edges /
                                     0 symbol-cash-release-quarantine
                                     violations / 0 same-symbol exclusivity
                                     violations / 0 shared-cash authorization
                                     violations
                                     witnesses: same_account_three_distinct_
                                     symbols -> all_three_working=true;
                                     cross_account_same_symbol_independence
                                     -> all_three_working=true;
                                     same_account_same_symbol_exclusion and
                                     same_account_cash_contention -> blocked
                                     (all_three_working=false, 0 violations)
  release_formal_verification      : PASS
```

## 2. Exact pin and single-authority composition (P1-1)

`pyproject.toml` now pins exactly:

```text
qmt-execution-core @ git+https://github.com/smhe00/qmt-execution-core@acf20d9fe5cf2aede3cc0ad0e8936ecb0c5b2692
```

Iteration 15's one-authority invariant is preserved and re-asserted on Core
0.4 (tests `test_qec_iter15.py` P1-1 + `test_qec_iter16.py`):

```python
engine.session is runtime.session            # identity, per stack
# one TGrid submit -> exactly one broker submit call (place_calls == 1)
# runtime.close() releases session/mutex/lease exactly once
```

In shared mode the runtime session is Core's `CoordinatedExecutionSession`;
no second `ExecutionSession`/journal/mutex is constructed around the same
runtime/broker (asserted `isinstance(runtime.session, CoordinatedExecutionSession)`
and `engine.session is runtime.session` for every stack).

## 3. Shared account-level coordination (P1-2)

`build_tgrid_qec_stack` / `build_qec_runtime` now accept and default to:

```text
runtime_lock_mode = "shared"
coordination_path = explicit canonical account-level coordination DB
cash_estimator    = explicit conservative CashRequirementEstimator
```

Fail-closed builder behaviour (new `test_qec_iter16.py::TestBuilderFailClosed`):

- shared mode without `coordination_path` AND without an injected
  `coordinator` -> `QecRuntimeError` (never silently runs uncoordinated);
- shared mode without `cash_estimator` -> `QecRuntimeError` (no implicit
  `qty * price` fallback);
- the builder never defaults coordination to a strategy-specific
  journal/database path;
- `exclusive` mode remains available for explicitly single-writer
  test/compatibility use (test proves `runtime_mutex` held, plain
  `ExecutionSession`, no session-id lease).

Gate-6 simulation runners (`scripts/gate6_sim_live.py`,
`scripts/gate6_sim_negative.py`) pass the new configuration explicitly:

```text
runtime_lock_mode = "shared"
coordination_path = --coordination-db   (default work/coordination/
                                          qmt-execution-coordination.db)
cash_estimator    = default_cash_requirement_estimator()
```

`default_cash_requirement_estimator()` is a documented explicit conservative
A-share estimator: commission 0.03% with 5 CNY minimum (folded transfer-fee
margin), no temporary withholding / FX rounding (not applicable), 0 safety
buffer by default (deployment may raise). Both scripts keep `--help` /
import smoke green (verified below).

## 4. Sidecar ordering (plan §5)

Final ordering is Core durable intent -> Core account-level symbol/cash
coordination COMMIT -> TGrid business sidecar COMMIT -> broker submit.
`TestCoordinatedSidecarOrdering` records a single shared event sequence:

```text
submit BUY (WORKING)   : events == [("coordinate", K), ("sidecar", K), ("broker", K)]
same-symbol conflict   : events == [("coordinate", K)] only; broker.place_calls == 0;
                          no TGrid business intent created (sidecar never ran)
```

The TGrid `OrderIntent + Reservation + DailyExposure` business ledger remains
the TGrid business ledger (persisted by the sidecar) and is explicitly NOT
the cross-process shared-cash authority; Core 0.4 owns the final
account-level BUY cash reservation gate using a fresh authoritative
`query_asset()` before the atomic reservation (P1-3).

## 5. Finality / recovery mapping (P1-4)

`snapshot_is_tgrid_terminal(state, finality)` (table-driven) + finality-aware
`apply_snapshot(..., finality=...)` and engine `_snapshot_status`:

| Core state | Core finality | TGrid business terminality |
| --- | --- | --- |
| FILLED / CANCELLED / REJECTED | RESOLVED | terminal (reservation released) |
| FAILED | RESOLVED (no unresolved order) | terminal (UNKNOWN) |
| FAILED + unresolved_order | QUARANTINED | **NOT terminal** (pending kept, reservation held) |
| UNKNOWN / CANCEL_REJECTED / WORKING / PARTIALLY_FILLED / PENDING_CANCEL | OPEN | NOT terminal (recoverable) |

The engine folds snapshots with the LIVE Core finality
(`execution_finality(self._session.machine)`), so a quarantined FAILED can
never become a TGrid release/terminal permission. Existing regressions stay
green on 0.4: `WORKING -> cancel rejected -> UNKNOWN -> WORKING -> FILLED`
(one submit / no resend), `UNKNOWN -> recovery failure -> FAILED /
QUARANTINED` with the symbol claim + Core cash reservation + TGrid business
reservation all retained, no blind resend.

## 6. Journal cutover (P1-5)

The 0.3.1 -> 0.4 journal cutover is REJECT, never silently migrate:

- Core binds every journal to `transition_spec_sha256` +
  `execution_source_sha256` of the actual Core source build; the 0.4 hashes
  differ from 0.3.1, so `ExecutionSession.open()` raises
  `JournalIntegrityError` on an old journal (fail closed — hash checks are
  never disabled);
- `build_qec_runtime` converts that into an explicit `QecRuntimeError`
  documenting the operator procedure: reconcile the old execution under the
  old deployment, archive the old 0.3.1 journal, configure a new 0.4
  journal path, then start the 0.4 runtime;
- `TestJournalRejection` proves: a journal with rewritten (old-style) hash
  binding is REJECTED by the 0.4 build; the file is untouched (not migrated,
  not deleted); after explicit archive + new 0.4 journal path the build
  succeeds and submits WORKING.

## 7. Bounded session-id leasing (plan §8)

No strategy business code manages MiniQMT session ids; Core 0.4
`BoundedSessionIdAllocator` leases them from a bounded OS-lock-backed pool.
Fake-XtQuant tests prove:

- two shared runtimes on the SAME qmt path acquire DIFFERENT session ids;
- closing one runtime releases only its own lease; the other runtime stays
  open and can still execute;
- exact session-id collision fails closed with `SessionIdUnavailable`
  (no fallback past the explicit id);
- same strategy name (identical candidate list) -> the second runtime's
  bounded fallback succeeds with a different id.

## 8. Required integration scenarios (plan §9)

All with fake Broker / fake XtQuant only — zero QMT order/cancel calls:

### 9.1 Three independent stacks / distinct symbols (PASS)
`TG-A/510300.SH`, `TG-B/510600.SH`, `TG-C/510900.SH` sharing one account
binding + one coordination DB are WORKING simultaneously; three distinct
session ids; `runtime_mutex is None` on all (no global qmt-path lock);
closing stack A leaves B/C fully operational; three OPEN symbol claims and
reserved cash 3 x 470 held in the shared coordination DB.

### 9.2 Same-symbol exclusion (PASS)
`TG-A` WORKING on 510300.SH; `TG-B` same account/symbol -> local REJECTED,
broker submit count 0, no TGrid business intent (runtime path AND engine
path); `TG-C` on a different symbol of the SAME account -> WORKING (no
global block).

### 9.3 Shared-cash race (PASS)
Deterministic fresh broker cash = 100 (both stacks). P0 BUY 60 -> WORKING
(reserve 60); P1 BUY 50 -> REJECTED before broker (only 40 remain), broker
submit 0, account-level active reservations stay 60; P1 BUY 40 -> WORKING
(active reservations exactly 100 — cannot overcommit).

### 9.4 Quarantine isolation (PASS)
`TG-A` 510300.SH: WORKING -> UNKNOWN (claim OPEN) -> authoritative recovery
failure -> FAILED / QUARANTINED. Asserted: symbol claim finality
QUARANTINED and Core cash reservation (470) held; TGrid business intent stays
SUBMITTED with its reservation active; the engine folds the quarantined
FAILED without terminalizing; no blind resend (`place_calls == 1`); `TG-B`
on 510600.SH proceeds; `TG-C` on 510300.SH is REJECTED before the broker.

### 9.5 Account isolation (PASS)
Bindings A1 and A2 (different `account_id_sha256` -> different
`account_key`), same symbol, same coordination DB: both WORKING; two
independent OPEN claims and independent 470 reservations; no
cross-contamination.

## 9. Regression gates (plan §11)

```text
full TGrid pytest        : 913 passed, 17 subtests passed   (was 897)
compileall -q src tests scripts : 0
qec pin                  : acf20d9fe5cf2aede3cc0ad0e8936ecb0c5b2692 (exact)
requires-python          : >=3.9 retained; ast.parse(feature_version=(3,9))
                           on every src/tests/scripts file: NONE failed
Gate-6 import/--help     : gate6_sim_live.py, gate6_sim_negative.py --help OK
capability scan          : ZERO raw QMT order/cancel call sites in src/
                           (AST scan, test_qec_cutover 2 passed; only
                           docstring prose mentions remain)
one-authority identity   : engine.session is runtime.session per stack
coordinated ordering     : coordinate -> sidecar -> broker (proven)
3 stacks / 3 symbols     : concurrent WORKING (proven)
same-symbol exclusion    : rejected before broker (proven)
shared-cash non-overcommit: proven with fresh broker cash 100
UNKNOWN / CANCEL_REJECTED / QUARANTINED : non-resend / non-release (proven)
fill-during-cancel -> FILLED : green (test_qec_equivalence)
disconnect/reconnect evidence gates : green (test_qec_equivalence)
```

## 10. Files changed

```text
pyproject.toml                        qec pin -> acf20d9 (0.4.0)
src/tgrid/integrations/qec_runtime.py shared mode + coordination_path +
                                      cash_estimator + coordinator wiring;
                                      journal hash-bound rejection;
                                      default_cash_requirement_estimator()
src/tgrid/integrations/qec_adapter.py ExecutionFinality import;
                                      snapshot_is_tgrid_terminal;
                                      apply_snapshot(finality=...) with
                                      QUARANTINED non-release semantics
src/tgrid/execution/executor.py       live-finality folding
                                      (execution_finality(session.machine))
scripts/gate6_sim_live.py             shared + coordination-db + estimator
scripts/gate6_sim_negative.py         shared + coordination-db + estimator
tests/unit/test_qec_iter16.py         NEW: 16 tests / 10 subtests (9.1-9.5,
                                      session-id, journal rejection,
                                      finality table, sidecar ordering,
                                      builder fail-closed, exclusive mode)
tests/unit/test_qec_iter15.py         stack helper -> shared config
tests/unit/test_qec_runtime.py        runtime helper -> shared config
work/control/CURRENT_TASK.md          Iteration 16 completion notes
work/control/WORKFLOW_STATE.yaml      handoff state (seq 42)
work/gates/QMT_EXECUTION_CORE/TGRID_CORE_0_4_INTEGRATION_EVIDENCE_20260816.md
```

## 11. Explicit safety statement

- `live_trading_allowed=false` throughout Iteration 16.
- NO real or simulation QMT order/cancel API was invoked at any point: all
  integration tests use fake XtQuant traders and fake `BrokerPort`
  implementations; Gate-6 scripts were only import/`--help` smoke-tested.
- The Gate-6 integrated QMT simulation run remains a separate
  user-authorized step.
