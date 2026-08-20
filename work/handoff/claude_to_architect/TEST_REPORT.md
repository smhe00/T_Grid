# Test Report — Gate-6.2 T+0 Intraday Roundtrip (SIMULATION)

## Task
`GATE6.2-T0-INTRADAY-ROUNDTRIP-20260820` — validate one complete TGrid + Core execution
roundtrip on `513100.SH` in the **simulation** account only. No strategy profitability is
asserted; this validates the execution chain and the Gate-6.2 safety invariants.

## Preflight / safety checks

| # | Check | Method | Result |
|---|---|---|---|
| 1 | `environment = simulation` | `build_tgrid_qec_stack(environment="simulation")` + `qmt_gate1_runtime` rejects non-sim | ✔ |
| 2 | `live_trading_allowed = false` | `WORKFLOW_STATE.yaml` | ✔ |
| 3 | Bound sim securities account (type=2, status=0) | runtime broker probe; sim path ≠ live path | ✔ |
| 4 | Core reference pin unchanged | `a68572de…` | ✔ |
| 5 | No unresolved Core claim for `513100.SH` pre-broker | Core coordination DB query | ✔ |
| 6 | No unresolved TGrid reservation for `513100.SH` pre-broker | `store.list_active_reservations()` | ✔ |
| 7 | `2026-08-20` is exchange trading day | QMT `get_trading_dates` | ✔ |
| 8 | Inside continuous-auction window | local clock 09:30–11:30 / 13:00–15:00 | ✔ (exec @ 11:01 / 11:09) |
| 9 | Fresh valid quote `bid1>0, ask1>0, ask1>=bid1` | `get_full_tick` | ✔ |
| 10 | Code gates | `python -m compileall -q src scripts` → 0 errors | ✔ |
| 11 | Core gate tests | `pytest tests/unit/test_qec_runtime.py tests/unit/test_qec_iter16.py` → 23 passed, 17 subtests | ✔ |
| 12 | qmt-execution-core verify | `qmt-execution-core verify` → PASS (433,489 reachable states, 0 violations) | ✔ |

## Execution checks

| # | Check | Evidence | Result |
|---|---|---|---|
| 13 | BUY submitted exactly once | `COUNTS.sim_buy_submits = 1` | ✔ |
| 14 | BUY FILLED 100 | broker order `<sanitized>`, polled to `FILLED`, qty 100 | ✔ |
| 15 | BUY notional ≤ 2000 CNY | `222.10 CNY` | ✔ |
| 16 | Post-BUY same-day sellable | broker position `513100.SH` volume 100 / can_use 100 | ✔ |
| 17 | SELL submitted exactly once | `COUNTS.sim_sell_submits = 1` | ✔ |
| 18 | SELL FILLED 100 | broker order `<sanitized>`, polled to `FILLED`, qty 100 | ✔ |
| 19 | SELL qty = BUY filled qty (never >100) | 100 = 100 | ✔ |
| 20 | Post-SELL position closed | broker position `513100.SH` volume 0 / can_use 0 | ✔ |
| 21 | No third order | legs capped at 1 BUY + 1 SELL | ✔ |
| 22 | Cancels = 0 | `COUNTS.sim_cancels = 0` | ✔ |

## Reconciliation / acceptance invariants (independent re-query after run)

| # | Invariant | Query | Result |
|---|---|---|---|
| 23 | TGrid intent `TG_G62_A` BUY FILLED | `store.get_intent` | ✔ |
| 24 | TGrid intent `TG_G62_B` SELL FILLED | `store.get_intent` | ✔ |
| 25 | TGrid active reservations = 0 | `store.list_active_reservations()` → `[]` | ✔ |
| 26 | Core `symbol_claim` 513100 unresolved = 0 | coordination DB `symbol_claim WHERE finality!='resolved'` → 0 rows | ✔ |
| 27 | Core active cash reservation = 0 | coordination DB `cash_reservation WHERE active=1` → `0` | ✔ |
| 28 | Live sim position `513100.SH` = 0 | broker `query_stock_positions` → volume 0 | ✔ |
| 29 | Net roundtrip qty = 0 | BUY 100 − SELL 100 | ✔ |
| 30 | No duplicate `client_order_key` | `TG_G62_A` / `TG_G62_B` unique, single submit each | ✔ |
| 31 | Live order/cancel calls = 0 | `COUNTS.live_order_calls = 0`, `live_cancel_calls = 0` | ✔ |
| 32 | RESOURCE INVARIANT OK | all of 25–27 clear | ✔ |

## Exact counts

```text
simulation BUY submits : 1
simulation SELL submits: 1
simulation cancels    : 0
live order calls      : 0
live cancel calls     : 0
product src changes   : 0
```

## Outcome
**ROUNDTRIP_PASS** — both legs FILLED, position closed to 0, all resource invariants clean.

This result does **not** self-certify Gate-6.2; the architect performs an independent audit
(`AUDIT_GATE6_2_T0_INTRADAY_ROUNDTRIP`) after `f`.

## Files committed (only the allowed set)

```text
scripts/gate6_t0_roundtrip.py
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md
work/handoff/claude_to_architect/TEST_REPORT.md
work/control/WORKFLOW_STATE.yaml
```

No other file changed. `git status` after commit shows only the intended files.

## Post-commit state returned

- `WORKFLOW_STATE.yaml`: `state=REVIEW_READY`, `owner=architect`, `authorized_next=[]`,
  `handoff_seq=64`, `handoff_id=TGRID-GATE6-2-T0-ROUNDTRIP-PASS-20260820-064`.
- Stopped and waiting for Architect review. No further action taken.

## Hard invariant
`live_trading_allowed=false`. Zero product-code changes, zero live order/cancel calls,
zero live broker side effects.
