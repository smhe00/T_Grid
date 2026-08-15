# Validation Request — qmt-execution-core 0.2.0

## Scope

This task is **validation only**. TGrid migration is paused until this validation is independently reviewed.

Validate the standalone library at the user's local path:

```text
D:\gitee\miniQMT\qmt-execution-core
```

against the authoritative GitHub identity:

```text
repository: https://github.com/smhe00/qmt-execution-core
branch:     main
commit:     a1500e724bcfed13efbac65d9fbdce2b2513c817
version:    0.2.0
```

Before testing, in that exact local directory run/fetch as needed and verify `git rev-parse HEAD` is exactly the commit above and the working tree is clean. Do not validate a different checkout by accident.

Important: validate the **actual squash-merged main commit above**, not only the pre-merge PR head.

Do not modify TGrid execution code and do not migrate TGrid during this task. Do not modify qmt-execution-core unless a later architect instruction explicitly authorizes fixes. Findings go into the validation report.

## Evidence classification

All DSH results are `SELF_CERTIFIED` until independently reviewed by the architect.

## Prohibited actions

```text
NO real-money order/cancel
NO QMT simulation order/cancel
NO order_stock / order_stock_async invocation
NO cancel_order_stock / cancel_order_stock_async invocation
NO live trading enablement
NO TGrid migration/refactor
NO widening of risk limits
```

A real MiniQMT environment may be used only for read-only connection/query smoke testing.

## V1 — Repository / package identity

1. Work in exactly `D:\gitee\miniQMT\qmt-execution-core`.
2. Fetch GitHub and checkout exactly `a1500e724bcfed13efbac65d9fbdce2b2513c817` (or confirm local `main` already equals it).
3. Verify `pyproject.toml` reports version `0.2.0`.
4. Confirm generic core code has no TGrid/Core/T-Lot/strategy dependency.
5. Confirm generic core does not require `xtquant` for import/tests; `xtquant` is runtime-supplied only by MiniQMT integration.
6. Record Python version(s), OS, exact commit and dirty-tree status.

## V2 — Full source-tree verification

Run from the exact main commit:

```text
python -m pytest -q
python -m compileall -q src tests
qmt-execution-core verify
```

If editable install is needed first:

```text
python -m pip install -e ".[dev]"
```

Record exact test count and complete verifier summary including:

```text
reachable states
reachable transitions
unreachable states/transitions
states without terminal path
invariant violations
transition_spec_sha256
execution_source_sha256
```

Any non-zero invariant violation or missing protected source is a FAIL.

## V3 — Installed-wheel verification

Build and verify the package as an installed artifact, not only from a checkout:

```text
python -m pip wheel --no-deps . -w dist
```

Install the produced wheel into a clean Python >=3.11 environment and, from a directory outside `D:\gitee\miniQMT\qmt-execution-core`, run:

```text
qmt-execution-core verify
python -c "import qmt_execution_core; print(qmt_execution_core.__file__)"
```

Requirements:

- installation succeeds;
- verifier succeeds outside the source checkout;
- installed package source hash is internally consistent;
- missing protected execution source must fail closed (demonstrate only in an isolated copied package fixture, never by corrupting the real environment).

## V4 — Static safety audit

Independently inspect at least:

```text
src/qmt_execution_core/state_machine.py
src/qmt_execution_core/session.py
src/qmt_execution_core/journal.py
src/qmt_execution_core/mutex.py
src/qmt_execution_core/recovery.py
src/qmt_execution_core/verifier.py
src/qmt_execution_core/event_queue.py
src/qmt_execution_core/guards.py
src/qmt_execution_core/miniqmt/status.py
src/qmt_execution_core/miniqmt/adapter.py
src/qmt_execution_core/miniqmt/binding.py
src/qmt_execution_core/miniqmt/callbacks.py
src/qmt_execution_core/miniqmt/runtime_gate.py
src/qmt_execution_core/miniqmt/runtime.py
```

Explicitly check:

### V4-A UNKNOWN / ambiguous submission
- submit exception/ambiguous result cannot blind-resubmit;
- zero broker match does not authorize resend;
- duplicate/multiple match fails closed;
- recovery identity is durable local identity, not caller-provided transient identity.

### V4-B cancel semantics
- cancel API success is not terminal cancellation;
- cancel requires authoritative re-query;
- fill-during-cancel resolves correctly;
- partial fill is preserved.

### V4-C MiniQMT status normalization
Verify `48..57`, `255`, and an unrecognized value. Unrecognized/255 must map to UNKNOWN/fail closed.

### V4-D query contract
- `None` is ambiguous, not empty success;
- bounded query failure is fail closed;
- `[]` is accepted as empty only when a non-None empty list was actually returned.

### V4-E journal / mutex
- execution mutex acquired before journal load/create;
- journal writes are crash-safe/atomic;
- source/spec hash binding is verified;
- lost/released lock cannot leave an execution-capable session;
- cross-cycle client order id / remark reuse is rejected.

### V4-F callback/event queue
- callbacks emit immutable observations only;
- callbacks do not send/cancel orders or mutate strategy state;
- stopped/failed/overflowed event queue makes execution unhealthy/fail closed.

### V4-G account binding / reconnect
- exact account fingerprint/type/status binding;
- wrong/multiple/no-normal account fails closed;
- disconnect immediately invalidates new-order capability;
- transport reconnect alone cannot restore order capability;
- recovery requires account re-verification, subscribe, authoritative reconcile and runtime re-confirmation.

### V4-H live gate
- live requires trusted config enable + runtime-only token confirmation;
- token plaintext is not persisted;
- disconnect/close revokes confirmation;
- simulation does not accidentally satisfy live authorization semantics.

### V4-I cross-project runtime ownership
- same QMT userdata path cannot be concurrently owned by two `MiniQmtRuntime` processes even if project journal locks differ.

## V5 — Fake-broker / fake-trader refinement

Run committed tests and report coverage of:

```text
submit accepted
submit rejected
submit ambiguous
working
partial fill
full fill
cancel pending
partial-fill + cancel
fill during cancel
cancel confirmed
cancel rejected + re-query
query None
unknown raw status
restart active
restart cancel-pending
duplicate recovery identity
disconnect -> blocked
reconnect without reconcile -> blocked
full reconnect/reconcile -> restored only when all gates pass
live missing token -> blocked
runtime mutex contention -> blocked
```

If a path lacks a committed test, note it. Temporary local exploratory tests are allowed but must not change production code or be committed unless later requested.

## V6 — Real MiniQMT read-only smoke

If MiniQMT is available on this machine, perform only read-only/session-lifecycle smoke:

Allowed examples:

```text
start/connect
account discovery/status
subscribe
query asset
query positions
query orders
query trades
close/session teardown
```

Strict prohibition:

```text
DO NOT call order_stock/order_stock_async
DO NOT call cancel_order_stock/cancel_order_stock_async
```

Validate exact account/path binding, account type/status constants, read-only query normalization and EventQueue lifecycle. Do not intentionally disrupt a production/live client to test reconnect.

If MiniQMT is unavailable or a safe read-only session cannot be established, report `UNAVAILABLE` rather than weakening constraints.

## V7 — Independence / reuse audit

Confirm:

- no TGrid-specific imports or Core/T-Lot semantics;
- public API is sufficient for project adapters (`ExecutionRequest`, `ExecutionSnapshot`, `ExecutionSession`, evidence/guard types, `MiniQmtRuntime`);
- project-specific risk evidence remains injectable;
- raw QMT states stay below broker adapter boundary;
- no hidden dependency on TGrid filesystem/database layout.

## Required report

Write in TGrid:

```text
work/gates/QMT_EXECUTION_CORE/DSH_VALIDATION_REPORT_20260816.md
```

Include:

```text
Verdict: SELF_CERTIFIED PASS / CHANGES_REQUIRED
Exact core commit/version
Local core path
Environment
Commands and exact results
Verifier hashes/results
Static-audit findings
Test/path coverage matrix
Real MiniQMT read-only smoke result (or UNAVAILABLE)
Any P0/P1/P2 defects with file:function references
Confirmation: no real or simulation QMT order/cancel invoked
Confirmation: TGrid migration was not performed
```

Do not fix defects in this validation task. Report them for independent review.

## Handoff

On completion update TGrid control only:

```text
state = REVIEW_READY
owner = architect
authorized_next = [AUDIT_QMT_EXECUTION_CORE_0_2_0]
live_trading_allowed = false
```

Migration remains paused until the architect reviews this validation.
