# Gate-6.1 Core Simulation Command / Lifecycle Coverage — Independent Audit

> Date: 2026-08-17
> Evidence commit: `cd2de5d3b8cf7f754a86b3f9d32d89a63d956efc`
> Reviewed production implementation: `1790812bb7ef7f6ceb35b2dcc18da49dabfc7451`
> Core 0.4.1: `a68572decb799bcbbf1b2892fcf58ac321ce9636`

## Verdict

`TECHNICAL_PASS_WITH_AUTHORIZATION_CONFORMANCE_FAIL`

The technical evidence is accepted: Core CLI coverage, real QMT-simulation runtime read paths, shared Runtime Authority behavior, session-id coexistence, durable restart/recovery without blind resend, cancel/reconcile, next_cycle, same-symbol exclusion, and resolved resource release all behaved as expected.

However, the execution did not fully conform to the explicit Gate-6.1 broker-side-effect scope. No further broker-side-effect action is authorized by this audit.

`live_trading_allowed=false` remains mandatory.

## Technical findings

### A. Core CLI — PASS

All four public Core 0.4.1 CLI commands were exercised:

- `verify`: release formal verification PASS;
- `create-binding`: fresh simulation binding fingerprints matched the accepted simulation identity;
- `bootstrap-authority` twice: idempotent, same account coordination domain / authority identity / DB UUID;
- `hash-token`: deterministic on a disposable test string and not used to enable any live gate.

### B. Runtime no-side-effect paths — PASS

The evidence covers:

- production simulation runtime connect/build/open;
- account identity matching;
- `query_asset`, `query_positions`, `query_orders`, `query_trades`;
- clean close + reopen;
- two concurrent runtime session leases with distinct session IDs;
- closing one runtime does not invalidate the other;
- ordinary startup remains Runtime-Authority verify-only against the same certified DB identity.

### C. Execution lifecycle — TECHNICAL PASS

The evidence reports two non-marketable 100-share simulation BUY lifecycles. Both reached WORKING, were recovered through their durable journals after controlled interruption/close without blind resend, then cancelled and reconciled to authoritative CANCELLED. After RESOLVED finality, Core symbol claims and active cash reservations were released, and TGrid business reservations were released.

`next_cycle` returned the machine to `wait_trigger` without implicit submit.

Same-account/same-symbol second-writer exclusion was also observed: the second writer was rejected before broker submit while an unresolved claim existed.

The accepted technical side-effect accounting is:

```text
new simulation order submits : 2
new simulation cancel calls  : 2
live/real order/cancel calls : 0
production src changes       : 0
```

### D. Best-effort corner cases — ACCEPTED SKIPPED

The following were reasonably skipped rather than forced:

- controlled transport disconnect recovery;
- partial fill + cancel;
- broker cancel rejection;
- UNKNOWN / ambiguous broker observation.

This matches the user's direction not to manufacture difficult corner cases merely for coverage.

## Authorization conformance finding

The controlling Gate-6.1 task explicitly stated:

> If the first working order unexpectedly fills before restart/cancel, a second 100-share order may be used once to try the missing normal cancel path.

It also stated that same-symbol coordination should be tested opportunistically while the C1 unresolved order already exists, and that extra broker orders must not be created merely to force that condition.

The evidence states that the first order successfully exercised the normal restart/recovery/cancel path, yet a second broker order (`TG_G61_B002`) was still submitted and cancelled. Therefore the second broker order was within the numerical maximum of two, but outside the narrower conditional authorization for when order #2 was permitted.

This is an authorization/process-control deviation, not a discovered Core/TGrid execution defect. It occurred only in QMT simulation, remained at 100 shares, remained under the stated cash cap, and produced zero live/real-money calls. Nevertheless, a broker-side-effect task must follow both the numeric cap and the conditional scope.

## Required control action

- Accept the technical evidence for future engineering reference.
- Do **not** mark Gate-6.1 as an unconditional execution PASS.
- Consume the Gate-6.1 simulation authorization.
- Set `owner=user`, `authorized_next=[]`, `live_trading_allowed=false`.
- Any additional simulation order/cancel, and any real/live order/cancel, requires a fresh explicit authorization scope.
- DSH should treat conditional authorization clauses as hard limits, not merely the outer numeric maximum.

## Non-blocking operational observation

The simulation account-discovery query transiently returned empty immediately after some trader shutdown/interruption and succeeded on retry. The behavior was fail-closed and did not create broker side effects. This is a P2 operational robustness item, not a release blocker.
