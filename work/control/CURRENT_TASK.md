# Current Task — Await Explicit User Authorization for Gate 6

## Status

`PASS_PRELIVE` — TGrid Iteration 16 Core 0.4.1 Runtime Authority integration has passed independent architecture/code audit.

Reviewed implementation:

```text
TGrid: 1790812bb7ef7f6ceb35b2dcc18da49dabfc7451
Core:  a68572decb799bcbbf1b2892fcf58ac321ce9636
```

Independent audit:

```text
work/gates/QMT_EXECUTION_CORE/
TGRID_CORE_0_4_1_RUNTIME_AUTHORITY_INTEGRATION_AUDIT_20260816.md
```

## Accepted invariants

- production shared runtime uses Core 0.4.1 canonical Runtime Authority only;
- no production `coordination_path` / `authority_root` / `coordinator=` / `authority=` bypass;
- explicit operator `bootstrap-authority` is required before first shared runtime start;
- missing/corrupt/replaced Authority or certified DB fails closed;
- one runtime-owned Core session is the execution authority per strategy process;
- same-account/different-symbol concurrency remains supported;
- same-account/same-symbol unresolved lifecycle remains excluded;
- shared BUY cash reservation remains atomic per account;
- QUARANTINED retains claim/cash/business reservation;
- TGrid business ledger remains downstream of Core coordination and upstream of broker submit;
- TGrid `src/` has no raw QMT order/cancel authority.

## Authorization boundary

`live_trading_allowed=false`.

No real or simulation QMT order/cancel is currently authorized. The shorthand `f` means fetch/audit only and never constitutes trading authorization.

The next execution-bearing step is Gate 6 and requires an explicit user instruction authorizing the intended simulation/live action and scope.

Until that happens:

```text
owner = user
authorized_next = []
simulation QMT order/cancel = NOT AUTHORIZED
real QMT order/cancel       = NOT AUTHORIZED
```

DSH/Codex should not start another implementation or invoke QMT order/cancel APIs while this state is active.
