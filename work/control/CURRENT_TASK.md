# Current Task — Gate-6 Simulation PASS / Await Separate Live Authorization

## Status

`PASS_GATE6_SIMULATION`

The user-authorized QMT **simulation-only** Gate-6 closed loop has completed and passed independent audit.

Locked baselines:

```text
TGrid implementation: 1790812bb7ef7f6ceb35b2dcc18da49dabfc7451
Core 0.4.1:          a68572decb799bcbbf1b2892fcf58ac321ce9636
Gate-6 evidence:     f29afd027993f1f534ab0d4ad218779b6ecc9565
Independent audit:   work/gates/QMT_EXECUTION_CORE/
                     GATE6_QEC_SIMULATION_INDEPENDENT_AUDIT_20260817.md
```

`live_trading_allowed=false` remains a hard invariant.

## Accepted Gate-6 simulation result

Phase A:

- exact Core/TGrid baselines verified;
- simulation account binding resolved;
- per-account Runtime Authority initialized only through explicit operator bootstrap;
- normal runtime remained verify-only;
- negative matrix passed: allowlist / quantity cap / cash cap / kill switch / unhealthy EventQueue all refused fail-closed;
- no negative test reached a broker order side effect.

Phase B:

```text
environment : simulation
symbol      : 510300.SH
side        : BUY
qty         : 100
quote       : 4.734
result      : FILLED 100/100
cancel      : not needed
reconcile   : filled / 100
```

Post-run:

```text
Core symbol claim        : released
Core active reserved cash: 0.0
TGrid intent             : FILLED
TGrid active reservation : none
```

Recorded side effects for the authorized run:

```text
simulation order calls : 1
simulation cancel calls: 0
live/real calls        : 0
```

## Non-blocking operational note

At 01:34 +08:00 the QMT trading-calendar query did not yet return 2026-08-17 and the runner safely skipped the positive path. A later fresh query at 09:34 correctly returned `is_trading_day=true` and the positive simulation ran.

This is recorded as P2: future hardening should distinguish "calendar data not ready / current day not returned" from an authoritative exchange closure. A data-not-ready condition must remain fail-closed, but should not be labelled as an exchange holiday without independent confirmation.

## Authorization boundary

The completed simulation authorization is consumed. There is currently **no authorized next broker-side-effect action**.

```text
owner = user
authorized_next = []
live_trading_allowed = false
simulation re-run/order/cancel = NOT AUTHORIZED unless separately requested
real/live order/cancel         = NOT AUTHORIZED
```

Any real-money Gate-6/7 step requires a new, explicit user instruction defining the intended live scope. Do not infer live authorization from prior simulation authorization or from the shorthand `f`.
