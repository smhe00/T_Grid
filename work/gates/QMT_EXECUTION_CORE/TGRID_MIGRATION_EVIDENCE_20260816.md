# TGrid → qmt-execution-core Migration Evidence — Iteration 13 (2026-08-16)

## Status

Phases **A0** (Python 3.9 compat gate) and **A** (public-core sidecar seam)
COMPLETE; Phase **B** (TGrid adapter) and Phase **C** (equivalence + cutover
builder + capability scan) COMPLETE; Phase **D** (remove duplicate reusable
infrastructure) REMAINING — destructive cleanup deferred to its own focused
pass after the equivalence evidence is reviewed.

`live_trading_allowed=false`; no real or simulation QMT order/cancel invoked.

## Public-core pins

```text
baseline (audited):    0.2.1  2e222e16731bd8ce232ffba78c697245472c2094
Phase A hooks:         0.3.0  87293e65d0c32ae10dbb94b857933c34d97fcaf4
A0 compat release:     0.3.1  937e6a4a1cbd54df960f9bde3ca2e91d6bc19c79  (>=3.9, CI 3.9/3.11/3.12)
TGrid pin (pyproject):        git+...@937e6a4a1cbd54df960f9bde3ca2e91d6bc19c79
```

## Phase A0 — Python 3.9 compatibility

Real Windows Python 3.9.13 (official embeddable, temp-only): import OK, full
suite 66 passed (pytest 7.4.4 + iniconfig 2.0.0), compileall 0, CLI verifier
50/208/0/0/0 with hashes identical to 3.12, wheel build + clean-env install +
out-of-tree installed-wheel verifier, same-process msvcrt ExecutionMutex
cycles, runtime-mutex contention test. Static: every src file parses with
`ast.parse(feature_version=(3,9))`; no runtime `X|Y` unions. xtquant NOT usable
from 3.9 locally → MiniQMT read-only smoke not re-run on 3.9 (recorded; 3.12
smoke already passed). TGrid stays `requires-python >=3.9`.

## Phase A — public-core sidecar seam (in qmt-execution-core 0.3.0/0.3.1)

`ExecutionSession` + `MiniQmtRuntime.connect()` accept
`before_broker_submit(request)` / `before_broker_cancel(order_id)` — no-op
default, synchronous execution-thread, AFTER the public durable intent /
cancel-intent and BEFORE the broker side effect; a raised hook proves the
broker call was never invoked (fail closed); no UNKNOWN blind retry; hook code
inside the protected-source manifest. Public-core suite 66 passed (+5 hook
tests).

## Phase B — TGrid adapter layer

New modules:

```text
src/tgrid/integrations/qec_adapter.py
    make_execution_request()      TGrid plan -> public ExecutionRequest
    TGridExecutionGuard           SessionEvidence/PrecheckEvidence from TGrid
                                  gates (allowlist/qty/cash/day-cap/kill switch/
                                  exposure + verified flags)
    TGridSidecar                  before_broker_submit/cancel: SQLite OrderIntent
                                  + Reservation + daily exposure commit BEFORE
                                  broker side effect; failure fail-closed
    snapshot_status_to_tgrid()    public TradeState -> TGrid OrderStatus
    apply_snapshot()              public snapshot -> TGrid ledger (status,
                                  broker_order_id, FILLED releases reservation)
src/tgrid/integrations/qec_runtime.py
    build_qec_runtime()           production-shaped MiniQmtRuntime with TGrid
                                  guard + sidecar (fake injection for tests)
```

Tests: `tests/unit/test_qec_adapter.py` (16), `test_qec_runtime.py` (2).

## Phase C — equivalence + cutover evidence

`tests/unit/test_qec_equivalence.py` (15) — integrated regression matrix
through the public core with the TGrid sidecar + guard:

1. submit accepted; 2. definitive submit rejected; 3. submit ambiguous /
   UNKNOWN no blind resend; 4. zero/duplicate recovery fail closed;
   5. working; 6. partial fill; 7. full fill; 8. cancel pending;
   9. cancel rejected + re-query; 10. partial fill + cancel preserves fill;
   11. **dedicated fill-during-cancel race -> FILLED**; 12. cancel confirmed;
   13. restart active; 14. restart cancel-pending; 15. query None ambiguous;
   16. unknown raw status -> UNKNOWN; 17. disconnect blocks; 18. reconnect
   without reconcile blocked; 19. full reconcile restores; 21. TGrid pre-send
   ledger commit; 22. crash after reservation before broker return fail-closed;
   23. duplicate client_order_id idempotent; 24. kill switch blocks;
   25/26. runtime mutex (public-core suite); 27. Python 3.9 evidence (A0).

`tests/unit/test_qec_cutover.py` (2):
- capability scan: **zero TGrid production raw QMT order/cancel call sites**
  (AST scan over `src/`; the only allowed owner is the retained legacy
  `xtquant_bridge.py` used for equivalence);
- old-vs-new lifecycle parity: legacy `ExecutionEngine`+`SimBroker` and the
  public-core session both land the same TGrid OrderIntent in FILLED with the
  reservation released.

Full TGrid regression: **1044 tests OK** (was 1009; +35 migration tests);
`compileall -q src tests scripts` exit 0.

## Module mapping (old -> public-core or retained TGrid-specific)

| TGrid module (old) | Disposition | Replacement |
|--------------------|-------------|-------------|
| `execution/statemachine.py` (reverse_repo port) | Phase D remove | `qmt_execution_core.state_machine` + `verifier` |
| `execution/execution_journal.py` | Phase D remove | `qmt_execution_core.journal` |
| `execution/execution_mutex.py` | Phase D remove | `qmt_execution_core.mutex` |
| `execution/port.py` (BrokerPort/status DTOs) | Phase D reduce | `qmt_execution_core.ports`/`domain` |
| `execution/recovery.py` | Phase D remove | `qmt_execution_core.recovery` |
| `integrations/xtquant_bridge.py` (raw QMT bridge) | Phase D remove (legacy-only) | `qmt_execution_core.miniqmt.*` |
| `integrations/live_session.py` + `live_bootstrap.py` | Phase D reduce | `qmt_execution_core.miniqmt.runtime` + `qec_runtime.build_qec_runtime` |
| `integrations/live_broker_adapter.py` | RETAIN (TGrid risk gates re-expressed via `TGridExecutionGuard`; legacy chain kept only for equivalence until D) | `TGridExecutionGuard` + sidecar |
| `events/` (EventQueue) | Phase D reduce | `qmt_execution_core.event_queue` |
| `execution/executor.py` (engine) | RETAIN-TRIM: TGrid-specific orchestration kept; generic parts removed in D | public session + TGrid ledger |
| `execution/store.py`, `models.py` | RETAIN (TGrid business ledger) | — |
| `execution/simbroker.py`, `simdriver.py` | RETAIN (test/dry-run fakes) | — |
| Core/T-Lot/settlement/risk/strategy/accounting | RETAIN (TGrid-specific) | — |

## Phase D — remaining (deferred)

After the equivalence evidence is reviewed, remove/reduce the generic
duplicates listed above (state machine, journal, mutex, generic port/recovery,
raw bridge, generic bootstrap/event-queue) while keeping TGrid-specific
ledger/risk/strategy. This is destructive (it touches the previously audited
Gate-5.5 chain and ~1000 legacy-path tests) and is therefore scoped as its own
focused pass; the legacy path stays ONLY for the equivalence harness until
then. Old and new execution authorities must never simultaneously own the
same QMT session.

## Confirmations

- No real or simulation QMT order/cancel invoked during B/C.
- `live_trading_allowed=false`.
- Capability scan: zero TGrid production raw QMT call sites outside the
  retained legacy bridge.
