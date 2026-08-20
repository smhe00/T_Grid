# Current Task — Gate-6.2 Simulation T+0 Intraday Roundtrip

## Goal

Use the existing **QMT simulation account only** to validate one complete TGrid + Core execution roundtrip on a product that supports same-day buy and sell.

Architect-selected instrument:

```text
symbol = 513100.SH
name   = 纳指ETF / NASDAQ-100 ETF
reason = SSE-listed cross-border ETF; architect has verified the exchange rule permits T+0 secondary-market trading
```

This task validates the execution chain, not strategy profitability.

## Hard authorization boundary

```text
environment                 = simulation only
symbol                      = 513100.SH only
BUY qty                     = exactly 100
SELL qty                    = at most the quantity actually filled by the authorized BUY, and never more than 100
max BUY notional            = 2000 CNY
max broker submit calls     = 2 total (one BUY + one SELL)
max broker cancel calls     = 2 total (at most one per leg)
real/live order calls       = 0
real/live cancel calls      = 0
production src changes      = NOT AUTHORIZED
Core source changes         = NOT AUTHORIZED
```

No alternate symbol, no quantity increase, no retry order, no second roundtrip, no live fallback.

## WorkBuddy protocol identity

```text
actual executor = workbuddy
protocol role   = claude
```

Existing GitHub handoff protocol remains authoritative.

## Preflight 0 — restore a truly clean worktree

Previous handshake exposed pre-existing local untracked files. For this task only, WorkBuddy is explicitly allowed to modify **local `.git/info/exclude` only** to ignore these known local-only paths without deleting or modifying their contents:

```text
.claude/
.workbuddy/
work/reports/gate6-sim/
```

This local exclusion MUST NOT be committed.

After applying those exact exclusions:

```text
git status --porcelain
```

MUST be empty before continuing.

If any tracked modification or any other untracked path remains, STOP WRITE / BLOCKED. Do not stash, reset, delete, move, force, rebase, or hide any additional path.

## Preflight 1 — immutable GitHub handoff

1. `git fetch origin main`.
2. Require `origin/main` to equal the handoff baseline.
3. `git merge --ff-only origin/main`.
4. Re-read protocol, `WORKFLOW_STATE.yaml`, and this task from the same commit.
5. Verify exact owner/state/task/handoff authorization before any QMT access.
6. Before any broker side effect, fetch again and require `origin/main` unchanged.

Any mismatch => STOP WRITE.

## Preflight 2 — simulation/QMT safety

Before any order call, prove and record all of:

- bound environment is exactly `simulation`;
- `live_trading_allowed=false`;
- runtime config has `live_trading_enabled=false`;
- production shared Runtime Authority resolves verify-only;
- Core reference remains `a68572decb799bcbbf1b2892fcf58ac321ce9636`;
- account is the expected healthy simulation securities account;
- event queue / execution health is healthy;
- no unresolved Core execution claim exists for `513100.SH`;
- no unresolved TGrid business reservation exists for `513100.SH`;
- current date from QMT trading calendar includes `2026-08-20`;
- current local exchange time is inside continuous auction: `09:30-11:30` or `13:00-15:00` China time;
- QMT recognizes `513100.SH`, not suspended, with a fresh valid quote;
- fresh `bid1 > 0`, `ask1 > 0`, `ask1 >= bid1`, spread is reasonable and quote timestamp is fresh.

If the task is consumed before 09:30, WorkBuddy may remain locally idle until the first valid continuous-auction window, but MUST NOT write/push heartbeat commits and MUST NOT place an order before all preflights pass.

## Implementation scope

Preferred path: reuse the already-audited Gate-6 production QEC composition.

If a dedicated runner is necessary, WorkBuddy may create only:

```text
scripts/gate6_t0_roundtrip.py
```

The runner must compose the normal TGrid production simulation stack and Core Runtime Authority path. It must not call raw XtQuant `order_stock()` / `cancel_order_stock()` outside the existing Core adapter.

Before broker side effects, run at least:

```text
python -m compileall -q src scripts
python -m pytest -q tests/unit/test_qec_runtime.py tests/unit/test_qec_iter16.py
qmt-execution-core verify
```

If a production `src/` change appears necessary, STOP before any order and return `CHANGES_REQUIRED`. Do not patch production code inside this authorization.

## Execution leg A — BUY 100

Only after every preflight passes:

1. Query a fresh quote immediately before submit.
2. Build a conservative marketable limit BUY for exactly `100` shares.
3. Price must remain within current broker/exchange limits and total BUY notional must be `<= 2000 CNY`.
4. Submit exactly once through the TGrid -> Core path.
5. Poll/reconcile until one of:
   - `FILLED 100`: proceed;
   - still unresolved after a bounded wait: issue at most one cancel, reconcile, then STOP with evidence;
   - `UNKNOWN / CANCEL_REJECTED / FAILED / REJECTED`: STOP; no blind retry.
6. If BUY is not exactly FILLED 100, SELL leg is NOT authorized.

After BUY FILLED, record broker order/trade evidence and query broker position. The broker/TGrid state must show that the acquired quantity is eligible for same-day sell before the SELL leg.

If TGrid rejects same-day sell because its business model treats this instrument as T+1, do not bypass TGrid and do not call raw broker APIs. Record this as the product gap and STOP.

## Execution leg B — SELL the same 100

Only if BUY FILLED 100 and same-day sellability is proven through the normal stack:

1. Fresh quote immediately before submit.
2. Build a conservative marketable limit SELL for exactly `100` shares.
3. Submit exactly once through TGrid -> Core.
4. Poll/reconcile until:
   - `FILLED 100`: proceed to final reconciliation;
   - unresolved after bounded wait: at most one cancel, reconcile, STOP with evidence;
   - `UNKNOWN / CANCEL_REJECTED / FAILED / REJECTED`: STOP; no retry.

No third order is allowed for any reason.

## Final reconciliation / acceptance evidence

If roundtrip completes, record and verify:

```text
BUY:  FILLED 100
SELL: FILLED 100
net roundtrip qty = 0
```

Then independently query/fold:

- broker orders and trades for both legs;
- broker position before BUY / after BUY / after SELL;
- TGrid intent / T-Lot / reservation state;
- Core execution finality for each leg;
- `(account_key, 513100.SH)` active claim count after each RESOLVED leg;
- active Core BUY cash reservations after final SELL;
- `next_cycle()` behavior after each resolved lifecycle;
- no blind resend / duplicate client_order_id;
- all sanitized order IDs, prices, timestamps, filled quantities, states and reasons.

Target end state:

```text
no unresolved Core claim for 513100.SH
no active Core cash reservation from the roundtrip
no unresolved TGrid reservation
no unexpected residual T-Lot from the completed roundtrip
simulation account only
live calls = 0
```

If any invariant is not provable, result is not PASS.

## Allowed repository changes

Only:

```text
scripts/gate6_t0_roundtrip.py                     # only if needed
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md
work/handoff/claude_to_architect/TEST_REPORT.md
work/control/WORKFLOW_STATE.yaml
```

No `src/`, `tests/`, Core repo, strategy config, binding, Authority, journal, or protocol file changes are authorized.

Local runtime/journal/evidence artifacts may be created only in already-ignored/local paths and must not be committed if they contain machine/account-specific data.

## Completion state

After execution or a fail-closed stop:

```text
state = REVIEW_READY   # technical result available for architect audit
owner = architect
authorized_next = []
handoff_seq = previous + 1
live_trading_allowed = false
```

Reports MUST state exact counts:

```text
simulation BUY submits
simulation SELL submits
simulation cancels
live order calls
live cancel calls
product src changes
```

and clearly distinguish one of:

```text
ROUNDTRIP_PASS
BLOCKED_PRE_BROKER
BUY_NOT_RESOLVED
T0_SELL_BLOCKED_BY_TGRID
SELL_NOT_RESOLVED
INVARIANT_FAIL
```

No result self-certifies Gate-6.2; Architect performs independent review after `f`.
