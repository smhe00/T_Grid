# Implementation Report — Gate-6.2 T+0 Intraday Roundtrip (SIMULATION) — Iteration 2

## Task (unchanged from iteration 1)
`GATE6.2-T0-INTRADAY-ROUNDTRIP-20260820` — one bounded QMT **simulation** T+0 intraday
roundtrip on `513100.SH` (SSE 纳指ETF, T+0 eligible) to validate the full TGrid + Core
execution chain end-to-end.

## Outcome
**ROUNDTRIP_PASS** (the iteration-1 execution is retained as positive evidence).
Independent audit verdict on iteration 1: **CHANGES_REQUIRED**. This iteration resolves all
7 required fixes. **No additional broker roundtrip was performed** — every fix is repo-scope /
runner-safety and is verifiable offline plus via failure-injection (per the architect's explicit
"prefer offline/failure-injection verification" guidance).

## Protocol / scope acknowledgement (P0-2, P0-1)

- **Conflict-merge deviation (P0-2).** The iteration-1 handback `032c548` was a **merge commit**
  (parents `db12179` + `b6a5c25`), not a fast-forward. This violated both `CURRENT_TASK.md`'s
  `git merge --ff-only origin/main` requirement and the collaboration protocol's STOP-WRITE-on-
  remote-divergence rule. The merge is **preserved as historical evidence and not rewritten**.
  From the architect's `CHANGES_REQUIRED` handoff (`2472c74`) forward, only linear/ff-only
  consumes of GitHub `main` are used; no further merge / rebase / force.
- **Out-of-scope tracked JSON (P0-1).** `work/reports/gate6-sim/gate6-sim-negative-2026-08-15.json`
  (machine/account-specific, not in the authorized file set) was committed. It is removed from
  HEAD by a normal forward commit in this iteration. The audit named this specific file; the
  fix request scoped deletion to it, so only this file is removed. Remaining `gate6-sim/*`
  tracking status is per the user's 2026-08-20 instruction and is outside this fix iteration's
  authorized changes.
- This report **no longer claims a strict four-file history**; the actual diff from the audit
  handoff touches the runner, both reports, the control state, and the JSON deletion.

## Fixes applied in iteration 2

| Finding | Fix | Location |
|---|---|---|
| P0-3 recovery sells unrelated inventory | Skip-BUY only when task intent `TG_G62_A` is authoritatively `FILLED` **and** broker reflects the same held qty; account position alone never proves task ownership | `_should_skip_buy()` + Leg A |
| P1-1 unresolved leg had no cancel | Poll; if not `FILLED`, exactly **one** cancel via `engine.cancel_order` (normal TGrid→Core path), reconcile via `poll_order`, record state, then **STOP**. No blind retry | `_wait_and_resolve_leg()` |
| P1-2 no freshness / spread bound | `_quote_ok()` enforces positive ordered bid/ask, tick age ≤ `QUOTE_MAX_AGE_MS` (5000 ms vs exchange epoch-ms tick), spread ≤ 1% of ask1; applied immediately before **both** submits; fail closed | `_quote_ok()` + Leg A/B gates |
| P1-3 hard-coded account literals | Identity derived from local, ignored qec binding via `account_key_from_binding_identity(...)`; prior sha256 literals removed; derived key reproduces original coordination DB path | final reconciliation block |
| P0-1 out-of-scope JSON | Forward `git rm` of the negative evidence file | repo |
| P0-2 report honesty | This + TEST_REPORT state the deviation explicitly | reports |

### P0-3 — Recovery must not sell unrelated inventory
`Leg A` skip-BUY now requires `store.get_intent("TG_G62_A")` to exist with `status == "FILLED"`
**and** the broker to still show `can_use_volume >= 100`. A recovery run on an account that
already holds `513100.SH` for unrelated reasons (but has no `TG_G62_A` FILLED intent) will
**not** skip BUY and will **not** sell that unrelated inventory. It fails safe by attempting the
authorized BUY.

### P1-1 — Unresolved leg: at most one cancel → reconcile → STOP
`_wait_and_resolve_leg(engine, key, now_fn, evidence)` polls up to 10×. If the leg reaches
`FILLED`, it returns. If already terminal (`CANCELED`/`REJECTED`), it returns with **zero**
cancels. Otherwise it issues **exactly one** `engine.cancel_order(key)` through the normal
TGrid→Core path, reconciles authoritatively via `poll_order`, records `cancel` + `reconcile`
evidence, and stops. No resend, no loop retry.

### P1-2 — Quote freshness + conservative spread bound
`_quote_ok(quote, *, is_sell)` rejects when bid/ask are not positive & ordered, when the
exchange tick is stale (`age_ms < 0` or `> 5000`), or when `spread > ask1 * 0.01`. It is called
immediately before the BUY submit (on a fresh re-fetched quote) and before the SELL submit.
A rejected quote never reaches a broker submit.

### P1-3 — No committed account-specific literals
The final reconciliation previously embedded two sha256 literals. They are removed; identity is
derived from the local, ignored binding file `work/gate6-qec-binding.json`
(`account_key_from_binding_identity(environment, account_type, account_id_sha256)`). Verified the
derived `account_key` equals the prior hardcoded value (`79b2c89d…`), so the coordination DB path
still resolves. No account-specific constant is committed; the binding file is untracked/local.

## Offline verification (re-run this iteration)

| Gate | Command | Result |
|---|---|---|
| compileall | `python -m compileall -q src scripts` | 0 errors |
| Core runtime tests | `pytest -q tests/unit/test_qec_runtime.py tests/unit/test_qec_iter16.py` | 23 passed, 17 subtests |
| Core model verify | `qmt-execution-core verify` | PASS — 433,489 reachable global states, 0 invariant/finality violations, 0 unreachable states |

## Failure-injection evidence (offline, no broker)

| Case | Input | Expected | Result |
|---|---|---|---|
| P1-2 valid quote | bid 2.218 / ask 2.219 / age 0 ms | pass | ✔ pass |
| P1-2 stale quote | age 10,000 ms (> 5000) | reject | ✔ reject `quote stale` |
| P1-2 wide spread | spread 0.200 > cap 0.022 | reject | ✔ reject `spread too wide` |
| P1-2 zero bid | bid 0 | reject | ✔ reject `bid/ask invalid` |
| P0-3 unrelated position | held 100, **no** `TG_G62_A` intent | do **not** skip BUY | ✔ `False` |
| P0-3 task filled + held | `TG_G62_A` FILLED, held 100 | skip BUY | ✔ `True` |
| P0-3 task rejected + held | `TG_G62_A` REJECTED, held 100 | do not skip | ✔ `False` |
| P0-3 task filled + partial | `TG_G62_A` FILLED, held 50 | do not skip | ✔ `False` |
| P1-1 unresolved leg | poll stays `SUBMITTED` | exactly 1 cancel → STOP | ✔ 1 cancel, returns non-FILLED |
| P1-1 already terminal | poll `CANCELED` | 0 cancels | ✔ 0 cancels |
| P1-1 filled leg | poll `FILLED` | 0 cancels | ✔ 0 cancels |

## Execution evidence (iteration 1 — retained positive evidence)

### Leg A — BUY 100
- Fresh quote `ask1 = 2.218`; marketable limit `BUY = 2.221` (`ask1 * 1.001`); notional `222.10 CNY` (< 2000 CNY).
- Submitted exactly once through TGrid→Core → broker order id `<sanitized>` → polled → **FILLED 100**.
- Post-BUY position `513100.SH` `volume 100 / can_use 100`.

### Leg B — SELL the same 100
- Fresh quote `bid1 = 2.218`; limit `SELL = 2.217` (`bid1 * 0.999`).
- Submitted exactly once → broker order id `<sanitized>` → **FILLED 100**.
- Post-SELL position `513100.SH` `volume 0 / can_use 0` (roundtrip closed).

## Final reconciliation invariants (independently re-verified after iteration-1 run)

| Invariant | Result |
|---|---|
| BUY FILLED 100, SELL FILLED 100, net qty = 0 | ✔ |
| Live sim position `513100.SH` = 0 | ✔ |
| TGrid intents `TG_G62_A` BUY FILLED, `TG_G62_B` SELL FILLED | ✔ |
| TGrid active reservations = 0 | ✔ |
| Core `symbol_claim` 513100 unresolved = 0 | ✔ |
| Core active cash reservation = 0 | ✔ |
| Simulation account only; live calls = 0 | ✔ |

## Exact counts

```text
# This iteration (fixes only — no broker side effects):
simulation BUY submits : 0
simulation SELL submits: 0
simulation cancels    : 0
live order calls      : 0
live cancel calls     : 0
product src changes   : 0

# Iteration 1 execution (retained positive evidence):
simulation BUY submits : 1
simulation SELL submits: 1
simulation cancels    : 0
live order calls      : 0
live cancel calls     : 0
product src changes   : 0
```

## Handoff

- `WORKFLOW_STATE.yaml`: `state=REVIEW_READY`, `owner=architect`, `authorized_next=[]`,
  `iteration=2`, `handoff_seq=66`, `live_trading_allowed=false`.
- Forward commit only; ff-only push to GitHub `main`; awaiting
  `AUDIT_GATE6_2_T0_INTRADAY_ROUNDTRIP_ITER2`.

## Files changed in this handback

```text
scripts/gate6_t0_roundtrip.py                                  # modified (P0-3/P1-1/P1-2/P1-3)
work/reports/gate6-sim/gate6-sim-negative-2026-08-15.json      # deleted (P0-1)
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md      # modified (P0-2 + fixes)
work/handoff/claude_to_architect/TEST_REPORT.md                # modified (P0-2 + fixes)
work/control/WORKFLOW_STATE.yaml                               # modified (handback)
```

## Hard invariant
`live_trading_allowed = false`. Zero live order/cancel calls; zero production `src/` or Core
source changes; no force push / rebase / reset / automatic retry this iteration.
