# Gate-6 QEC Simulation — Phase A Evidence + Phase B Deferred

> Date: 2026-08-17 (01:34 +08:00)
> Task: `GATE6-QEC-SIMULATION-CLOSED-LOOP` (user-authorized, simulation only)
> Author: DSH. Evidence SELF_CERTIFIED until independent audit
> (`AUDIT_GATE6_QEC_SIMULATION_EVIDENCE`).
> `live_trading_allowed=false` throughout; zero live/real-money calls.

## 0. Locked baselines

```text
TGrid implementation : 1790812bb7ef7f6ceb35b2dcc18da49dabfc7451
Core 0.4.1           : a68572decb799bcbbf1b2892fcf58ac321ce9636
```

## 1. Phase A — preflight + bootstrap + negative matrix (COMPLETE)

### A1/A2 versions + binding identity
- TGrid pin verified = `a68572decb799bcbbf1b2892fcf58ac321ce9636` (exact).
- Pinned `qmt-execution-core verify` PASS (release formal, 433,489 states /
  4,461,994 edges / 0 violations).
- Simulation QMT path resolved from Gate-1 config (simulation environment).
- Simulation account identity resolved read-only: `account_type=2`,
  `account_id_sha256=7424e0cd66f135606bf4036df6414a412c8f0d4dc0a0ccd9d082cf705537e030`,
  `qmt_path_sha256=e5dd14a0e60436a6fda670c99d88d75c833eed1a3e763813ad96460d23adcfc8`.

### A3/A4 canonical Runtime Authority + explicit operator bootstrap
- Explicit operator bootstrap performed once via
  `qmt-execution-core bootstrap-authority --binding <binding>` (no
  auto-bootstrap; normal runtime remains verify-only).
- Canonical Authority resolved and validated under the OS-derived host root:
  `account_key=79b2c89de3530efb179a84368ecaec3d551e6f39e4f34d02bc2dc722834fdae3`,
  `authority_id=8bc66b60-5103-479b-a3f2-155ec28e3650`,
  `coordination_db_uuid=d94a29c2-07eb-4401-9f72-59ca7238c8bf`.
- Re-running bootstrap is idempotent (same authority_id/db_uuid); the
  Authority-certified coordination DB identity verifies on open.

### A5 negative-path matrix (PASS, zero broker side effects)
`gate6_sim_negative.py` (fresh db/journal per run):

```text
all_refused                  : true
allowlist non-allowed symbol : refused (rejected)
per-order qty cap            : refused (rejected)
per-order cash cap           : refused (rejected)
kill switch                  : refused (rejected)
event-queue stopped          : refused (execution_healthy false)
session_built                : true
```

Post-run Authority-certified coordination DB inspection: `symbol_claim` rows
= 0, `cash_reservation` rows = 0, active reserved cash = 0.0 — proving NO
negative case reached Core coordination and therefore NO broker submit.

> Note: a prior negative run surfaced "ExecutionError" labels because a
> stale `<db>.journal.json` from an earlier attempt persisted a non-idle
> machine state; the runner correctly refused (fail-closed, zero broker
> order). A fresh journal re-run produced clean "rejected" labels. This is a
> documented operational note (run each Gate-6 pass with a fresh db/journal).

## 2. Phase B — single positive simulation BUY (DEFERRED, not run)

`gate6_sim_live.py` preflight at 2026-08-17T01:34+08:00:

```text
is_trading_day     : false
in_execution_window: false
skipped_reason     : non-trading-day
```

Authoritative SH trading calendar via read-only `get_trading_dates`:
the last trading date present for 2026-08 is **2026-08-14**; **2026-08-17
(Monday) is a non-trading day** in the client's calendar. The runner
correctly skipped the order path (fail-closed) before any connection/order.

Phase B therefore remains pending a genuine exchange trading day within the
execution window (09:30-11:28 / 13:00-15:28). The authorized single BUY
(510300.SH, qty=100, qty_cap<=200, cash_cap<=5000) was NOT placed.

## 3. Order/cancel side-effect accounting

```text
simulation order_stock calls : 0
simulation cancel calls      : 0
live/real-money calls        : 0
Authority/DB recreation      : none (explicit single bootstrap only)
production code changes      : none
```

## 4. Safety statement

- `live_trading_allowed=false`; no live or real-money order/cancel invoked.
- Phase B was blocked by the authoritative trading-day + execution-window
  preflight and will only be attempted when both conditions hold, under the
  exact authorized single-order scope.
