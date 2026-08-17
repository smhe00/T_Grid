# Gate-6 QEC Simulation Closed-Loop — Independent Audit

> Date: 2026-08-17
> Audit target evidence commit: `f29afd027993f1f534ab0d4ad218779b6ecc9565`
> Reviewed TGrid implementation: `1790812bb7ef7f6ceb35b2dcc18da49dabfc7451`
> Locked Core 0.4.1: `a68572decb799bcbbf1b2892fcf58ac321ce9636`

## Verdict

**PASS_GATE6_SIMULATION**.

The user-authorized Gate-6 QMT simulation closed loop completed within the authorized scope. This audit does **not** authorize any live/real-money order or cancel. `live_trading_allowed=false` remains mandatory.

## 1. Scope / code-integrity check

From the independently reviewed implementation `1790812b...` to evidence commit `f29afd0...`, there are no production `src/` code changes. Changes are documentation/control/evidence plus a non-semantic Iter16 test docstring edit. The execution path therefore remains the previously audited Core 0.4.1 Runtime-Authority composition.

## 2. Phase A — safety/bootstrap / negative matrix

Accepted:

- exact Core pin `a68572d...` verified;
- simulation account binding resolved without switching to the live path;
- Account Runtime Authority initialized through explicit operator bootstrap only; normal TGrid runtime remained verify-only;
- Authority identity (`account_key + db_uuid + authority_id`) was stable on idempotent re-bootstrap;
- negative matrix reports all protected cases refused: wrong allowlist symbol, quantity cap, cash cap, kill switch and unhealthy EventQueue;
- post-run coordination DB inspection recorded zero symbol claims and zero cash reservations for the negative run;
- no positive order was attempted during the initial blocked preflight.

### P2-1 — pre-market calendar false negative (non-blocking)

At 01:34 +08:00, the QMT `get_trading_dates` result did not contain 2026-08-17 and the runner conservatively treated the day as non-trading. This was safe because it skipped the order path, but the evidence text incorrectly described 2026-08-17 itself as an exchange non-trading day.

The Shanghai Stock Exchange 2026 closure schedule does not list 2026-08-17 as a closure date, and SSE trading rules define Monday-Friday as trading days except statutory/announced closures. The later 09:34 QMT query correctly returned `is_trading_day=true`.

Future operational hardening should distinguish:

```text
calendar source has not yet returned current day / data not ready
```

from:

```text
exchange-authoritative closed day
```

A data-not-ready condition should remain fail-closed, but should not be persisted/reported as an exchange closure without independent confirmation.

This P2 does not invalidate the Gate-6 simulation result because the false negative caused no broker side effect, and the actual positive order was submitted only after a fresh in-window query returned trading-day=true.

## 3. Phase B — single positive simulation BUY

Raw runner evidence records:

```text
environment         : simulation
symbol              : 510300.SH
qty                 : 100
fresh quote         : 4.734
in_execution_window : true
is_trading_day      : true
send result         : FILLED / filled_qty=100
broker reconcile    : filled / filled_qty=100
terminal_state      : FILLED
```

This exactly matches the authorized positive scope: one 100-share BUY, no alternate symbol and no parameter expansion.

No cancel was required because the order became terminal FILLED during the bounded poll window.

## 4. Resource-finality check

The evidence records after FILLED:

```text
Core symbol claim        : released (0 rows)
Core active reserved cash: 0.0
cash reservation record  : inactive / released_at set
TGrid business intent    : FILLED
TGrid active reservation : none
```

This is consistent with Core `ExecutionFinality.RESOLVED` semantics and TGrid business-reservation release.

## 5. Broker side-effect boundary

Recorded execution accounting:

```text
simulation BUY order calls : 1
simulation cancel calls    : 0
live/real order/cancel     : 0
```

The raw runner evidence independently shows one broker order id and one terminal FILLED lifecycle. The exact aggregate API-call count and post-run DB inspection remain execution evidence produced by DSH/local runtime rather than GitHub-hosted CI instrumentation; this limitation is noted but does not contradict the observable evidence.

## 6. Gate decision

Gate-6 **simulation** validation is accepted.

The accepted progression is now:

```text
Gate 0-5              PASS
Core 0.4.1            PASS / locked
TGrid Iter16          PASS_PRELIVE
Gate-6 QMT simulation PASS_GATE6_SIMULATION
live/real trading     NOT AUTHORIZED
```

No automatic progression to a real-money Gate-6/7 action is allowed. Any live order/cancel requires a separate explicit user authorization with its own bounded scope.
