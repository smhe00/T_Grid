# Test Report — Gate-6.2 T+0 Intraday Roundtrip (SIMULATION) — Iteration 2

## Task
`GATE6.2-T0-INTRADAY-ROUNDTRIP-20260820` — validate one complete TGrid + Core execution
roundtrip on `513100.SH` in the **simulation** account only. Iteration 2 addresses the
independent audit's **CHANGES_REQUIRED** verdict with repo-scope / runner-safety fixes, verified
offline + via failure-injection (no additional broker roundtrip required).

## Offline verification gates (re-run)

| # | Gate | Command | Result |
|---|---|---|---|
| 1 | `environment = simulation` | `build_tgrid_qec_stack(environment="simulation")` + `qmt_gate1_runtime` rejects non-sim | ✔ |
| 2 | `live_trading_allowed = false` | `WORKFLOW_STATE.yaml` | ✔ |
| 3 | compileall | `python -m compileall -q src scripts` | ✔ 0 errors |
| 4 | Core runtime tests | `pytest -q tests/unit/test_qec_runtime.py tests/unit/test_qec_iter16.py` | ✔ 23 passed, 17 subtests |
| 5 | Core model verify | `qmt-execution-core verify` | ✔ PASS — 433,489 reachable states, 0 invariant/finality violations, 0 unreachable |

## Iteration-1 execution checks (retained positive evidence)

| # | Check | Evidence | Result |
|---|---|---|---|
| 6 | BUY submitted exactly once | `sim_buy_submits = 1` | ✔ |
| 7 | BUY FILLED 100 | broker `<sanitized>`, polled `FILLED` | ✔ |
| 8 | BUY notional ≤ 2000 CNY | `222.10 CNY` | ✔ |
| 9 | Post-BUY same-day sellable | position `513100.SH` 100/100 | ✔ |
| 10 | SELL submitted exactly once | `sim_sell_submits = 1` | ✔ |
| 11 | SELL FILLED 100 | broker `<sanitized>`, polled `FILLED` | ✔ |
| 12 | SELL qty = BUY filled (never >100) | 100 = 100 | ✔ |
| 13 | Post-SELL position closed | position `513100.SH` 0/0 | ✔ |
| 14 | No third order | capped at 1 BUY + 1 SELL | ✔ |
| 15 | Cancels = 0 | `sim_cancels = 0` | ✔ |

## Iteration-2 fix verification (offline, no broker)

### P1-2 — quote freshness + spread bound (`_quote_ok`)
| # | Case | Input | Expected | Result |
|---|---|---|---|---|
| 16 | valid quote | bid 2.218 / ask 2.219 / age 0 ms | pass | ✔ pass |
| 17 | stale quote | age 10,000 ms (> 5000) | reject | ✔ `quote stale` |
| 18 | wide spread | spread 0.200 > cap 0.022 | reject | ✔ `spread too wide` |
| 19 | zero bid | bid 0 | reject | ✔ `bid/ask invalid` |

### P0-3 — recovery must not sell unrelated inventory (`_should_skip_buy`)
| # | Case | Input | Expected | Result |
|---|---|---|---|---|
| 20 | unrelated pre-existing position | held 100, **no** `TG_G62_A` intent | do NOT skip BUY | ✔ `False` |
| 21 | task filled + held | `TG_G62_A` FILLED, held 100 | skip BUY | ✔ `True` |
| 22 | task rejected + held | `TG_G62_A` REJECTED, held 100 | do NOT skip | ✔ `False` |
| 23 | task filled + partial | `TG_G62_A` FILLED, held 50 | do NOT skip | ✔ `False` |

### P1-1 — unresolved leg: at most one cancel → reconcile → STOP (`_wait_and_resolve_leg`)
| # | Case | Engine behavior | Expected | Result |
|---|---|---|---|---|
| 24 | unresolved | poll stays `SUBMITTED` | exactly 1 cancel → STOP | ✔ 1 cancel, returns non-FILLED |
| 25 | already terminal | poll `CANCELED` first | 0 cancels | ✔ 0 cancels |
| 26 | filled | poll `FILLED` first | 0 cancels | ✔ 0 cancels |

### P1-3 — no committed account-specific literals
| # | Check | Method | Result |
|---|---|---|---|
| 27 | sha256 literals removed from runner | `grep` for prior literals → none | ✔ |
| 28 | identity derived from local binding | `account_key_from_binding_identity(env, type, sha)` | ✔ reproduces original `account_key` |
| 29 | binding file not tracked | `git ls-files` for binding → not present | ✔ (local/ignored) |

### P0-1 — out-of-scope JSON removed
| # | Check | Method | Result |
|---|---|---|---|
| 30 | negative JSON deleted from HEAD | `git rm` + forward commit | ✔ |

### P0-2 — protocol deviation acknowledged
| # | Check | Result |
|---|---|---|
| 31 | conflict-merge deviation stated in both reports | ✔ |
| 32 | no history rewrite / force push this iteration | ✔ |

## Reconciliation / acceptance invariants (independent re-query after iteration-1 run)

| # | Invariant | Result |
|---|---|---|
| 33 | TGrid intent `TG_G62_A` BUY FILLED | ✔ |
| 34 | TGrid intent `TG_G62_B` SELL FILLED | ✔ |
| 35 | TGrid active reservations = 0 | ✔ |
| 36 | Core `symbol_claim` 513100 unresolved = 0 | ✔ |
| 37 | Core active cash reservation = 0 | ✔ |
| 38 | Live sim position `513100.SH` = 0 | ✔ |
| 39 | Net roundtrip qty = 0 | ✔ |
| 40 | Live order/cancel calls = 0 | ✔ |
| 41 | RESOURCE INVARIANT OK | ✔ |

## Exact counts

```text
# This iteration (fixes only — zero broker side effects):
simulation BUY submits : 0
simulation SELL submits: 0
simulation cancels    : 0
live order calls      : 0
live cancel calls     : 0
product src changes   : 0

# Iteration 1 execution (retained):
simulation BUY submits : 1
simulation SELL submits: 1
simulation cancels    : 0
live order calls      : 0
live cancel calls     : 0
product src changes   : 0
```

## Outcome
**ROUNDTRIP_PASS retained as positive evidence; iteration-2 fixes verified offline + via
failure-injection.** Gate-6.2 remains pending independent re-review
(`AUDIT_GATE6_2_T0_INTRADAY_ROUNDTRIP_ITER2`).

## Handoff
- `WORKFLOW_STATE.yaml`: `state=REVIEW_READY`, `owner=architect`, `authorized_next=[]`,
  `iteration=2`, `handoff_seq=66`, `live_trading_allowed=false`.
- Forward commit only; ff-only push to GitHub `main`.

## Files changed in this handback

```text
scripts/gate6_t0_roundtrip.py                                  # modified
work/reports/gate6-sim/gate6-sim-negative-2026-08-15.json      # deleted
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md      # modified
work/handoff/claude_to_architect/TEST_REPORT.md                # modified
work/control/WORKFLOW_STATE.yaml                               # modified
```

## Hard invariant
`live_trading_allowed=false`. Zero product-code changes, zero live order/cancel calls,
zero live broker side effects this iteration.
