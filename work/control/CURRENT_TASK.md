# Current Task — Gate-6.1 Technical PASS / Authorization Conformance Hold

## Status

`TECHNICAL_PASS_WITH_AUTHORIZATION_CONFORMANCE_FAIL`

Gate-6.1 successfully exercised the intended Core 0.4.1 command/runtime/lifecycle paths in QMT simulation, but the execution exceeded one conditional broker-side-effect clause in the authorized task.

Locked baselines:

```text
TGrid implementation : 1790812bb7ef7f6ceb35b2dcc18da49dabfc7451
Core 0.4.1           : a68572decb799bcbbf1b2892fcf58ac321ce9636
Gate-6 evidence      : f29afd027993f1f534ab0d4ad218779b6ecc9565
Gate-6.1 evidence    : cd2de5d3b8cf7f754a86b3f9d32d89a63d956efc
Gate-6.1 audit       : work/gates/QMT_EXECUTION_CORE/
                       GATE6_1_CORE_SIM_COMMAND_COVERAGE_INDEPENDENT_AUDIT_20260817.md
```

`live_trading_allowed=false` remains a hard invariant.

## Technical result accepted

The following Gate-6.1 evidence is technically accepted:

- all four Core CLI commands exercised: `verify`, `create-binding`, `bootstrap-authority`, `hash-token`;
- production simulation runtime connect/open/close/reopen;
- account identity + Runtime Authority verify-only behavior;
- `query_asset`, `query_positions`, `query_orders`, `query_trades`;
- concurrent session-id leasing;
- non-marketable simulation order reaches WORKING;
- durable close/restart recovery finds existing broker order without blind resend;
- cancel -> re-query/reconcile -> CANCELLED;
- RESOLVED finality releases Core claim/cash and TGrid business reservation;
- `next_cycle` returns to `wait_trigger` without implicit submit;
- same-account/same-symbol second writer rejected before broker submit;
- difficult partial/UNKNOWN/cancel-reject/disconnect cases were correctly left SKIPPED rather than forced.

Recorded Gate-6.1 side effects:

```text
simulation order submits : 2
simulation cancel calls  : 2
live/real calls          : 0
production src changes   : 0
```

## Authorization conformance issue

The Gate-6.1 task allowed a second 100-share simulation order **only if the first order unexpectedly filled before the normal cancel path could be exercised**.

The evidence shows the first order already covered WORKING -> restart/recovery -> cancel -> CANCELLED. A second broker order was nevertheless submitted and cancelled to continue coverage.

Therefore:

- technical lifecycle evidence is retained and accepted;
- this is **not** treated as a Core/TGrid product defect;
- however the Gate-6.1 execution cannot receive an unconditional authorization-conformance PASS;
- the Gate-6.1 broker-side-effect authorization is consumed.

Future DSH runs must treat conditional authorization clauses as hard bounds, not only the outer numeric count.

## Current authorization boundary

```text
owner = user
authorized_next = []
live_trading_allowed = false
additional simulation order/cancel = NOT AUTHORIZED
real/live order/cancel             = NOT AUTHORIZED
```

Any new broker-side-effect action requires a fresh explicit user scope.

A shorthand `f` remains fetch/audit only and does not authorize another simulation or live order.
