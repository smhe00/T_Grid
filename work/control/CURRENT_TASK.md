# Current Task — Gate 6 QEC Simulation Closed-Loop

## Authorization

The user explicitly authorized **Gate 6** on 2026-08-17.

This authorization is intentionally scoped to the existing **QMT simulation** Gate-6 workflow only. It does **not** authorize any live/real-money order or cancel.

Reviewed baselines remain locked:

```text
TGrid implementation: 1790812bb7ef7f6ceb35b2dcc18da49dabfc7451
Core 0.4.1:          a68572decb799bcbbf1b2892fcf58ac321ce9636
```

`live_trading_allowed=false` remains a hard invariant.

## Authorized Gate-6 scope

Run one bounded simulation verification sequence using the reviewed Gate-6 runners and Core 0.4.1 Runtime Authority.

### Phase A — safety/bootstrap preflight

Before any simulation broker order/cancel:

1. verify the locked Core/TGrid versions and the simulation binding;
2. resolve the QMT simulation account identity;
3. ensure the per-account Core Runtime Authority exists and validates its certified dedicated coordination DB (`account_key + canonical path + db_uuid + authority_id`);
4. if this is first use, perform **explicit operator bootstrap** through `qmt-execution-core bootstrap-authority` only — normal TGrid runtime must remain verify-only and must never auto-bootstrap;
5. run the Gate-6 negative-path matrix; every negative case must fail closed before broker side effect.

If Authority/bootstrap/identity verification fails ambiguously, STOP. Do not delete/recreate/adopt a DB automatically and do not continue to the positive order.

### Phase B — one positive simulation order

Only after Phase A passes:

- environment: `simulation` only;
- symbol: `510300.SH` (existing Gate-6 default / allowlisted instrument);
- BUY quantity: exactly `100` shares (one t_unit);
- `qty_cap <= 200`;
- `cash_cap <= 5000 CNY`;
- require exchange trading day + existing execution-window preflight;
- fetch a fresh quote immediately before submit;
- place at most **one** simulation BUY for this authorized Gate-6 run;
- poll/query through the reviewed Core session authority;
- if not terminal within the existing bounded polling window, issue the reviewed cancel path and re-query/reconcile;
- never assume zero fill;
- emit sanitized Gate-6 evidence.

No automatic second BUY, no parameter expansion, no alternate symbol, and no retry that could create another broker order. Any ambiguous/UNKNOWN/QUARANTINED state is fail-closed and ends the run pending audit.

## Forbidden by this authorization

```text
real/live QMT order or cancel      NOT AUTHORIZED
more than one positive sim BUY     NOT AUTHORIZED
symbol other than 510300.SH        NOT AUTHORIZED
qty > 100 for positive order       NOT AUTHORIZED
cash cap > 5000 CNY                NOT AUTHORIZED
automatic Authority/DB recreation  NOT AUTHORIZED
production code changes before run NOT AUTHORIZED
```

If an implementation change is discovered to be necessary to make Gate-6 compatible with Core 0.4.1 Runtime Authority, STOP before any order/cancel, hand back for code review, and obtain a fresh audit of the changed code before resuming Gate-6.

## Evidence and handoff

Record at minimum:

- exact TGrid/Core commits;
- simulation-only environment proof;
- Runtime Authority/bootstrap result without plaintext account ID/path disclosure;
- negative-path results and proof of zero broker side effects for negative tests;
- exchange trading-day and execution-window checks;
- quote timestamp/price evidence;
- positive submit result / broker order id (sanitized as appropriate);
- poll/fill/cancel/reconcile sequence;
- final Core state/finality and TGrid business status;
- claim/cash-reservation state after terminal or ambiguous outcome;
- explicit count of simulation order and cancel API calls;
- confirmation of zero live/real-money calls.

After the run, hand back:

```text
state = REVIEW_READY
owner = architect
authorized_next = [AUDIT_GATE6_QEC_SIMULATION_EVIDENCE]
live_trading_allowed = false
```

Do not proceed to any live Gate-6/7 action without a separate explicit user authorization.
