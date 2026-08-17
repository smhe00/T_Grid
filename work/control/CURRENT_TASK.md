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

## Phase A COMPLETE / Phase B DEFERRED (2026-08-17 01:34 +08:00)

Evidence: `work/gates/QMT_EXECUTION_CORE/
GATE6_QEC_SIMULATION_PHASE_A_EVIDENCE_20260817.md`.

- **A1/A2**: TGrid pin `a68572d…` + Core verify PASS; simulation QMT path and
  account identity resolved read-only (account_id_sha256 `7424e0cd…`,
  qmt_path_sha256 `e5dd14a0…`).
- **A3/A4**: explicit operator `qmt-execution-core bootstrap-authority`
  performed once (no auto-bootstrap); canonical Authority resolved+validated
  (authority_id `8bc66b60-…`, db_uuid `d94a29c2-…`, idempotent re-run).
- **A5**: negative matrix PASS (`all_refused: true`, clean "rejected" labels
  with a fresh journal); Authority-certified DB shows 0 symbol claims / 0
  cash reservations -> zero broker-reaching submissions.
- **Phase B deferred**: `gate6_sim_live.py` preflight returned
  `is_trading_day=false` + `in_execution_window=false`; authoritative SH
  `get_trading_dates` shows the last 2026-08 trading day is 2026-08-14, so
  2026-08-17 (Monday) is a non-trading day. The single positive sim BUY was
  NOT placed and will only run on a genuine trading day within the execution
  window (09:30-11:28 / 13:00-15:28).
- **Order/cancel count: 0 simulation, 0 live/real.** No Authority/DB
  recreation, no production code change.

Next: retry Phase B on the next exchange trading day within the execution
window, under the exact authorized single-order scope (510300.SH, qty=100,
qty_cap<=200, cash_cap<=5000).

## Phase B COMPLETE (2026-08-17 09:34 +08:00)

Evidence: `work/gates/QMT_EXECUTION_CORE/
GATE6_QEC_SIMULATION_PHASE_B_EVIDENCE_20260817.md`.

- **Simulation-account re-verified before submit**: Gate-1 environment
  `simulation`; `simulation_qmt_path=D:\国金QMT交易端模拟\userdata_mini`
  (live path NOT used); account binding `simulation` / `repo_simulation`.
- **Preflight**: `is_trading_day=true` (SH get_trading_dates confirms
  2026-08-17), `in_execution_window=true` (09:34 morning window).
- **Single positive sim BUY**: 510300.SH, qty=100, quote 4.734,
  broker_order_id 1090520375 → **FILLED** (filled_qty 100). No cancel
  needed; reconcile confirmed filled.
- **Post-run state**: Core symbol_claim 0 (RESOLVED released), Core
  active_reserved_cash 0.0, TGrid intent FILLED + active reservations [].
- **Order/cancel count: 1 simulation order, 0 cancel, 0 live/real.** No
  Authority/DB recreation, no production code change.

Handoff: REVIEW_READY, owner=architect,
authorized_next=[AUDIT_GATE6_QEC_SIMULATION_EVIDENCE].
