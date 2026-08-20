# Implementation Report — Gate-6.2 T+0 Intraday Roundtrip (SIMULATION)

## Task
`GATE6.2-T0-INTRADAY-ROUNDTRIP-20260820` — one bounded QMT **simulation** T+0 intraday
roundtrip on `513100.SH` (SSE 纳指ETF, T+0 eligible) to validate the full TGrid + Core
execution chain end-to-end.

Authorization boundary (exact, from `CURRENT_TASK.md`):

```text
environment              = simulation only
symbol                   = 513100.SH only
BUY qty                  = exactly 100
SELL qty                 = the same filled 100 (never more than 100)
max BUY notional         = 2000 CNY
max broker submits       = 2 total (one BUY + one SELL)
max broker cancels       = 2 total
real/live order calls    = 0
real/live cancel calls   = 0
production src changes   = NOT AUTHORIZED
Core source changes      = NOT AUTHORIZED
```

## Outcome
**ROUNDTRIP_PASS**

## Safety / preflight chain (all verified before any broker side effect)

| # | Guard | Result |
|---|---|---|
| 1 | `environment = simulation` (hardcoded in `build_tgrid_qec_stack`; `qmt_gate1_runtime` raises if non-sim) | ✔ |
| 2 | `live_trading_allowed = false` | ✔ |
| 3 | Bound account is the healthy **simulation securities account** (type=2, status=0), on a sim userdata path physically separate from the live path | ✔ |
| 4 | Core reference pin `a68572de…` verified unchanged | ✔ |
| 5 | No unresolved Core `symbol_claim` / TGrid reservation for `513100.SH` before execution | ✔ |
| 6 | `2026-08-20` is an exchange trading day | ✔ |
| 7 | Execution inside continuous-auction window (BUY submit 11:01, SELL submit 11:09, China time) | ✔ |
| 8 | Fresh valid quote: `bid1 > 0`, `ask1 > 0`, `ask1 >= bid1` | ✔ |
| 9 | `compileall src scripts` = 0 errors; `pytest tests/unit/test_qec_runtime.py tests/unit/test_qec_iter16.py` = 23 passed / 17 subtests; `qmt-execution-core verify` = PASS (433,489 reachable states, 0 invariant/finality violations) | ✔ |

## Execution evidence

### Leg A — BUY 100
- Fresh quote `ask1 = 2.218`; conservative marketable limit `BUY = 2.221` (`ask1 * 1.001`);
  notional `= 222.10 CNY` (< 2000 CNY limit).
- Submitted **exactly once** through the TGrid → Core path → broker order id `<sanitized>` →
  polled → **FILLED 100**.
- Post-BUY broker position: `513100.SH` `volume 100 / can_use 100` (same-day sellable).

### Leg B — SELL the same 100
- Fresh quote `bid1 = 2.218`; limit `SELL = 2.217` (`bid1 * 0.999`).
- Submitted **exactly once** → broker order id `<sanitized>` → polled → **FILLED 100**.
- Post-SELL broker position: `513100.SH` `volume 0 / can_use 0` (roundtrip closed).

## Final reconciliation (acceptance invariants — independently re-verified after run)

| Invariant | Result |
|---|---|
| BUY FILLED 100, SELL FILLED 100, net roundtrip qty = 0 | ✔ |
| Live sim position `513100.SH` = 0 (closed) | ✔ |
| TGrid intents: `TG_G62_A` BUY FILLED, `TG_G62_B` SELL FILLED | ✔ |
| TGrid active reservations = 0 (both released) | ✔ |
| Core `symbol_claim` for `513100.SH` unresolved = 0 | ✔ |
| Core active cash reservation from roundtrip = 0 | ✔ |
| No blind resend / duplicate `client_order_key` | ✔ |
| Simulation account only; live calls = 0 | ✔ |

## Exact counts (per CURRENT_TASK completion requirement)

```text
simulation BUY submits : 1
simulation SELL submits: 1
simulation cancels    : 0
live order calls      : 0
live cancel calls     : 0
product src changes   : 0
```

## Runner correction applied in this task (`scripts/gate6_t0_roundtrip.py`)

The original run completed both legs (BUY 11:01 → SELL 11:09, both FILLED) but then crashed
on the SELL-leg verification line with `AttributeError: 'OrderIntent' object has no attribute
'filled_qty'`. `OrderIntent` carries `status`, not a `filled_qty` field (filled qty lives on the
broker side). Two corrections were made:

1. **Bug fix** — both leg verification lines now use `state != "FILLED"` instead of reading the
   non-existent `OrderIntent.filled_qty`.
2. **Idempotent "already-closed" short-circuit** — a re-run that finds both intents `FILLED`
   **and** live position `0` declares `ROUNDTRIP_PASS` **without placing any order**. This prevents
   a blind re-run (after closure, position is 0) from re-BUYing and violating the
   "exactly 100 / max 1 BUY + 1 SELL" Gate-6.2 limits. The fix is for code correctness and future
   safety; it does **not** re-execute the roundtrip.

## Override note on prior BLOCKED_PRE_BROKER
The architect's handoff `b6a5c25` recorded `BLOCKED_PRE_BROKER` at 09:40 on 2026-08-20 because the
QMT simulation data feed showed a frozen call-auction quote for `513100.SH` (`bid1=ask1=0`). That
was a **transient sim-feed freeze**: the quote recovered later in the session and the roundtrip
was executed successfully (BUY 11:01 → SELL 11:09, both FILLED, position closed to 0). This
handback supersedes `b6a5c25` with the actual `ROUNDTRIP_PASS` result at `handoff_seq=64`.

## Files in this handback (the allowed set, per CURRENT_TASK)

```text
scripts/gate6_t0_roundtrip.py                     # fixed (bug + idempotency guard)
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md
work/handoff/claude_to_architect/TEST_REPORT.md
work/control/WORKFLOW_STATE.yaml
```

## Hard invariant honored
- `live_trading_allowed = false` remains a hard invariant.
- Zero live order/cancel calls; zero production `src/` or Core source changes.
- Only the 4 allowed files are committed; no force push, rebase, reset, or automatic retry.
