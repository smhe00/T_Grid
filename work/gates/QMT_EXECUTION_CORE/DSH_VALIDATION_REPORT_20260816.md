# DSH Validation Report — qmt-execution-core 0.2.0 (2026-08-16)

## Verdict

**SELF_CERTIFIED CHANGES_REQUIRED**

The standalone library is architecturally sound (verifier passes, wheel
installs and verifies, real MiniQMT read-only smoke passes, static audit of
the safety semantics passes on every sampled control), but it ships with one
**P1 Windows-only defect** (execution-mutex release fails after the first
owner cycle — deterministic, reproduced cross-process 12/12) that breaks
**three committed tests**, and two **P2 committed-test gaps**. Per the
validation-task instructions, defects are **reported, not fixed**.

## Identity (V1)

| Item | Result |
|------|--------|
| Local path | `D:\gitee\miniQMT\qmt-execution-core` |
| `git rev-parse HEAD` | `a1500e724bcfed13efbac65d9fbdce2b2513c817` (== authoritative) |
| Working tree | clean at start and after validation (dist/__pycache__ ignored) |
| `pyproject.toml` version | `0.2.0` |
| TGrid/Core/T-Lot/strategy dependency | **none** — 0 `tgrid` imports in `src/` and `tests/` |
| xtquant requirement for import/tests | **not required** — the only 3 `xtquant` imports are lazy, inside `miniqmt/runtime.py::_real_xtquant_dependencies()` (raises `RuntimeConfigurationError` when missing) |
| Environment | Windows (os.name=`nt`), Python 3.12.10, CPython 64-bit |

## V2 — Full source-tree verification (at a1500e7)

```text
python -m pytest -q            -> 56 passed, 3 failed, 1.78s
python -m compileall -q src tests -> exit 0
qmt-execution-core verify      -> PASS (CLI verifier)
```

CLI verifier summary:

```text
declared_states: 16        reachable_abstract_states: 50
declared_transitions: 78   reachable_transitions: 208
unreachable_states: 0      unreachable_transitions: 0
states_without_terminal_path: 0
invariant_violations: 0
transition_spec_sha256: 62e04e05482e50836325efb4ccc0eb09dc65ccf162646ad1f0c667eab447398e
execution_source_sha256: 67dd05dd27a378542608d62d350a6c46b2cecea5a495322a2e05973a1dc79055
```

**3 failing committed tests (all the same P1 Windows mutex defect):**

```text
tests/test_journal_mutex.py::test_mutex_excludes_second_owner
tests/test_miniqmt_runtime.py::test_same_qmt_path_allows_only_one_runtime_even_with_different_project_locks
tests/test_session.py::test_restart_recovers_working_order
```

Each fails with `PermissionError: [Errno 13] Permission denied` at
`src/qmt_execution_core/mutex.py:65` (`msvcrt.locking(..., LK_UNLCK, 1)`).

## V3 — Installed-wheel verification

```text
python -m pip wheel --no-deps . -w dist  -> qmt_execution_core-0.2.0-py3-none-any.whl
```

- Installed into a clean Python 3.12 venv; install succeeds.
- From a directory OUTSIDE the checkout (`%TEMP%\qec_outside`):
  `qmt-execution-core verify` succeeds with **identical** hashes
  (`execution_source_sha256=67dd05dd...`, `transition_spec_sha256=62e04e05...`,
  50/208/0/0/0) — installed-package source hash is internally consistent.
- `python -c "import qmt_execution_core; print(qmt_execution_core.__file__)"`
  resolves to `site-packages\qmt_execution_core\__init__.py` (outside checkout).
- **Missing protected source fails closed** (demonstrated ONLY on an isolated
  copy of the installed package under `%TEMP%` — real environment untouched):
  deleting `mutex.py` from the fixture makes `execution_source_sha256()` raise
  `FileNotFoundError: protected execution source missing: mutex.py`.

## V4 — Static safety audit

Manual spot-check of the safety-critical controls (full per-item matrix in
the architect review trail): all sampled controls PASS —

- V4-A: `session.py::submit` maps `BrokerSubmissionRejected` ->
  `SUBMIT_REJECTED`, `BrokerSubmissionAmbiguous`/`BrokerError` ->
  `SUBMIT_AMBIGUOUS`; no blind resubmit from UNKNOWN (`state_machine.py`
  UNKNOWN has no resubmit transitions); recovery identity comes from the
  **durable journal intent** (`_recover_unknown` +
  `find_unique_managed_order(symbol, side, qty, order_remark)`), never a
  caller selector; `_validate_identity` enforces symbol/side/qty + durable
  broker_order_id match.
- V4-B: `cancel()` persists the durable cancel intent (`persist_cancel_intent`)
  BEFORE `CANCEL_REQUESTED`, then ALWAYS re-queries via `poll()`; cancel ack
  alone is not cancellation (`test_cancel_ack_is_not_cancelled_until_query_confirms`);
  partial fills preserved (`test_partial_cancel_preserves_fill`).
- V4-C: `miniqmt/status.py` maps 48..57 explicitly; **255 and any unrecognized
  value (or non-int) -> UNKNOWN (fail closed)**.
- V4-D: `strict_non_none_query` (binding) / `_strict_query` (adapter): `None`
  is ambiguous, bounded retries then fail closed; `[]` only accepted when a
  non-None empty list was returned.
- V4-E: journal construction performs **no I/O**; `session.open()` acquires
  the execution mutex BEFORE `journal.open()`; writes are
  temp+fsync+`os.replace` (atomic); spec/source hash binding verified on open;
  cross-cycle `client_order_id`/`order_remark` reuse rejected
  (`used_client_order_ids`/`used_order_remarks`, `assert_identity_unused`).
  **Exception**: mutex release defect (see Findings P1) breaks the
  "lost/released lock cannot leave an execution-capable session" lifecycle in
  the same process on Windows.
- V4-F: callbacks only enqueue immutable observations via `try_emit`
  (never block, never send/cancel); full/unhealthy queue -> FAILED and the
  broker health probe includes `event_queue.healthy`.
- V4-G: binding is strict-schema, **plaintext account/path forbidden**,
  exact qmt-path fingerprint; `select_bound_account` requires exactly one
  candidate (type + account_id fingerprint) and exactly one healthy status
  (id + type + status exact); disconnect invalidates and recovery re-verifies
  account + subscribe + reconcile + re-confirmation.
- V4-H: `RuntimeExecutionGate` — simulation ready without live token; live
  requires config enable **AND** runtime token (SHA-256 digest, HMAC compare,
  plaintext never persisted); `revoke()` on disconnect/close; simulation never
  satisfies live semantics (`confirm()` rejects non-live).
- V4-I: the runtime mutex path is `%TEMP%\qmt-execution-core\qmt-runtime-<qmt_path_fingerprint>.lock`
  — a SINGLE lock per QMT userdata path regardless of project journal locks,
  so two `MiniQmtRuntime` processes on the same userdata contend on the same
  mutex by construction. The committed test for this fails only because of the
  P1 mutex defect, not the design.

## V5 — Fake-broker / fake-trader refinement coverage (committed tests)

| Path | Covered by | Status |
|------|-----------|--------|
| submit accepted | test_session.py::test_submit_poll_and_fill | OK |
| submit rejected | test_miniqmt_status.py::test_minus_one_is_definitive_submit_reject | OK |
| submit ambiguous | test_miniqmt_status.py::test_submit_exception_is_ambiguous + test_session.py::test_submit_unknown_recovers_by_durable_remark_without_resend | OK |
| working | test_session.py::test_submit_poll_and_fill | OK |
| partial fill | test_session.py::test_partial_cancel_preserves_fill + status 52/53 tests | OK |
| full fill | test_session.py::test_submit_poll_and_fill | OK |
| cancel pending | test_session.py::test_cancel_ack_is_not_cancelled_until_query_confirms | OK |
| partial-fill + cancel | test_session.py::test_partial_cancel_preserves_fill | OK |
| fill during cancel | test_partial_cancel_preserves_fill | **PARTIAL** (fill preserved on partial-cancel; no dedicated race test) |
| cancel confirmed | test_cancel_ack_is_not_cancelled_until_query_confirms | OK |
| cancel rejected + re-query | — | **GAP (no committed test)** |
| query None | test_miniqmt_status.py::test_query_none_is_ambiguous_not_empty | OK |
| unknown raw status | test_miniqmt_status.py::test_qmt_status_mapping | OK |
| restart active | test_session.py::test_restart_recovers_working_order | OK (present; **currently FAILING** — P1) |
| restart cancel-pending | — | **GAP (no committed test)** |
| duplicate recovery identity | test_cross_cycle_client_id_and_remark_are_durable_idempotency_keys + test_submit_unknown_recovers_by_durable_remark_without_resend | OK |
| disconnect -> blocked | test_disconnect_revokes_execution_and_recovery_requires_full_sequence | OK |
| reconnect without reconcile -> blocked | same | OK |
| full reconnect/reconcile -> restored only when all gates pass | same | OK |
| live missing token -> blocked | test_live_disabled_cannot_confirm / test_live_requires_config_and_runtime_confirmation | OK |
| runtime mutex contention -> blocked | test_same_qmt_path_allows_only_one_runtime_even_with_different_project_locks | OK (present; **currently FAILING** — P1) |

## V6 — Real MiniQMT read-only smoke

**PERFORMED — PASS** (QMT simulation client running: `XtItClient`/`XtMiniQmt`).

Read-only lifecycle on the simulation userdata (exact commit checkout):

```text
raw probe: connect rc=0; exactly one normal OK securities account discovered
MiniQmtRuntime.connect (real xtquant, live_trading_enabled=False, auto_open=True)
  bound account: <sim-account-id-sanitized> (SECURITY_ACCOUNT=2 / ACCOUNT_STATUS_OK=0)
  query_asset:      cash/frozen/market_value/total_asset (numbers only, sanitized)
  query_positions:  1
  query_orders:     3
  query_trades:     0
  execution_healthy: True
runtime.close(): gate revoked, queue stopped, trader stopped, mutex released
```

**No `order_stock` / `order_stock_async` / `cancel_order_stock` /
`cancel_order_stock_async` / `submit` / `cancel` / `confirm_live` invoked.**

## V7 — Independence / reuse audit

- 0 `tgrid` imports in `src/` and `tests/`; no Core/T-Lot semantics.
- Public API sufficient for project adapters: `ExecutionRequest`,
  `ExecutionSnapshot`, `ExecutionSession`, evidence types
  (`PrecheckEvidence`/`SessionEvidence`), guard types (`ExecutionGuard`
  protocol / `LimitExecutionGuard`/`ExecutionLimits`), `SafetyFacts`,
  `TradeEvent`/`TradeState`, `verify_state_machine`, plus the full
  `qmt_execution_core.miniqmt` profile (`MiniQmtRuntime`,
  `MiniQmtRuntimeConfig`, adapter, binding, callbacks, runtime gate, status).
- Project-specific risk evidence is injectable through the `ExecutionGuard`
  protocol (`verify_session`/`verify` return `SessionEvidence`/`PrecheckEvidence`).
- Raw QMT states stay below the broker adapter boundary: normalized by
  `miniqmt/status.py::normalize_qmt_order_status` into package-owned
  `BrokerOrderStatus`; DTOs are package-owned.
- No hidden dependency on TGrid filesystem/database layout: the package takes
  its own `journal_path`/`lock_path`/binding paths.
- Docs: `docs/{ARCHITECTURE,STATE_MACHINE_SPEC,MINIQMT_PROFILE,PRODUCTION_RUNTIME}.md`
  + `docs/project_integration.py`.

## Findings

### P1 — Windows execution-mutex release fails after the first owner cycle

- **File/function**: `src/qmt_execution_core/mutex.py` — `ExecutionMutex._lock`
  (lines 73-82, the Windows "write a 0 byte before locking" workaround) +
  `ExecutionMutex.acquire` (line 47 `handle.truncate()`) + `ExecutionMutex.release`
  (line 65 `msvcrt.locking(..., LK_UNLCK, 1)`).
- **Observation**: after ONE complete owner cycle on a lock file (write "0"
  on empty -> lock -> truncate -> write pid -> unlock), any SUBSEQUENT owner
  (new `ExecutionMutex` object in the same process **or a separate process**)
  successfully acquires the lock but its `release()` raises
  `PermissionError: [Errno 13] Permission denied` at the `LK_UNLCK`.
- **Reproduction**: deterministic; minimal repro 12/12; cross-process child
  process repro also fails; a control variant without the pre-lock "0"-byte
  write passes (TGrid's faithful reverse_repo port of the same lock passes).
- **Impact**: breaks 3 committed tests; a crash-restart or second session in
  the same process cannot release the lock (lock is only freed by OS process
  exit); graceful teardown of the second owner raises.
- **Suggested direction for the architect** (not implemented here): remove the
  pre-lock write/read workaround or avoid `truncate()` while the byte-range
  lock is held, then re-run the 3 tests on Windows.

### P2 — committed-test gaps

- No committed test for **cancel rejected + re-query**.
- No committed test for **restart from cancel-pending**.
- **fill during cancel** only partially covered (fill preserved on
  partial-cancel; no dedicated fill-arrives-after-cancel-request race test).

## Confirmations

- **No real or simulation QMT order/cancel invoked** (validation was
  read-only; V6 smoke never called order/cancel APIs).
- **TGrid migration was not performed** (paused per the validation request;
  no TGrid execution code was modified).
- **qmt-execution-core was not modified** (only read; `git status` clean).
- Verifier: 0 invariant violations; protected source fail-closed verified.
