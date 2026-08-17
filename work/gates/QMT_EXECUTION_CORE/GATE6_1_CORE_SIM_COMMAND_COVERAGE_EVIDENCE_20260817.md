# Gate-6.1 Core Simulation Command / Lifecycle Coverage — Evidence

> Date: 2026-08-17 (09:4x +08:00)
> Task: `GATE6.1-CORE-SIMULATION-COMMAND-LIFECYCLE-COVERAGE` (user-authorized,
> simulation only)
> Author: DSH. Evidence SELF_CERTIFIED until independent audit
> (`AUDIT_GATE6_1_CORE_SIMULATION_COMMAND_COVERAGE`).
> `live_trading_allowed=false`; cumulative live/real calls = 0.

## 0. Locked baselines

```text
TGrid implementation : 1790812bb7ef7f6ceb35b2dcc18da49dabfc7451
Core 0.4.1           : a68572decb799bcbbf1b2892fcf58ac321ce9636
Gate-6 simulation    : PASS_GATE6_SIMULATION
```

## A. Core CLI — all four public commands (PASS)

| Case | Result | Evidence |
| --- | --- | --- |
| A1 `verify` | PASS | `release_formal_verification=PASS`; 433,489 states / 4,461,994 edges / 0 violations; `execution_source_sha256=e51180b5…`; `transition_spec_sha256=dede4b84…` |
| A2 `create-binding` | PASS | fresh temporary sim binding created; environment=simulation, account_type=2, account_id_sha256=7424e0cd…, qmt_path_sha256=e5dd14a0… — ALL match the accepted sim binding; no plaintext account id/path persisted |
| A3 `bootstrap-authority` ×2 | PASS | idempotent: both runs return account_key=79b2c89de…, authority_id=8bc66b60-5103-479b-a3f2-155ec28e3650, coordination_db_uuid=d94a29c2-07eb-4401-9f72-59ca7238c8bf, same canonical DB path — no second coordination domain |
| A4 `hash-token` | PASS | disposable test string only; deterministic output `8050b9c9d67a4bbfd6e80f2f0c7076e396cab8574e0854c06f1a6dc90cc3a194` (identical on both runs); not fed to any live gate |

## B. Real simulation runtime — no-side-effect flows (PASS)

Using the production TGrid/Core 0.4.1 shared Runtime-Authority composition:

| Case | Result | Evidence |
| --- | --- | --- |
| connect/build/open | PASS | `session_built`; resolved account_key=79b2c89de… (matches sim binding); session_id leased (100000213); coordinator Authority-bound (`expected_identity` set) |
| account identity | PASS | bound account_type=2; derived account_key equals the Authority account_key |
| read paths | PASS | `query_asset` OK (BrokerAsset); `query_orders` OK (3 TG_ orders incl. known Gate-6 order); `query_positions` OK (2); `query_trades` OK (1) — sanitized counts only |
| close + reopen | PASS | clean close; fresh runtime reopened; Authority still verify-only with the SAME certified DB identity (account_key 79b2c89de…, db_uuid d94a29c2…) |
| session-id coexistence | PASS | two concurrent sim runtimes: session ids 100000213 vs 100000359 (distinct); closing/keeping one leaves the other `execution_healthy`; no broker order required |

## C. Lifecycle coverage (bounded simulation broker side effects)

Budget: new sim order submits <= 2, sim cancels <= 2, live = 0.

The preferred single-order restart/cancel scenario was exercised through the
natural close/restart/recovery path (the first controlled submit remained a
valid non-marketable limit order; the run was closed and reopened through the
durable journal). Two 100-share BUY orders were used total, each recovered
and cancelled:

```text
C1 submit -> WORKING      : 2 orders (TG_G61_B001 @4.598, TG_G61_B002 @4.591),
                            100 shares each, non-marketable limit below fresh
                            quote, cash cap 5000 not exceeded
C1 close/restart/recovery : reopen with the SAME durable journal; open-time
                            recovery found the existing broker order
                            (machine=working) with NO blind resend
                            (TG_ broker order count unchanged)
C1 cancel + reconcile     : cancel -> CANCELLED; post-cancel poll CANCELLED;
                            reconcile filled_qty=0
C1 resource finality      : after CANCELLED, Core symbol_claim rows = 0 and
                            active reserved cash = 0.0; TGrid intent CANCELED,
                            active reservations = 0
C2 next_cycle             : machine -> wait_trigger after terminal lifecycle;
                            used client/order identity protection intact;
                            no implicit broker submit
C3 same-symbol second     : while B002 was unresolved, a second independent
writer                     runtime for the SAME sim account attempted the SAME
                            symbol -> REJECTED before broker (broker_order_id
                            null, TG_ broker order count unchanged, no TGrid
                            intent created — Core coordination claim blocked it)
```

### Order/cancel totals (Gate-6.1)

```text
new simulation order submits : 2   (at authorized max 2)
new simulation cancel calls  : 2   (at authorized max 2)
cumulative live/real calls   : 0
production src changes       : 0   (validation performed with transient
                                    probe scripts, NOT committed; no src/tgrid
                                    or Core modification)
```

## D. Best-effort flows — SKIPPED (with reasons)

| Case | Result | Reason |
| --- | --- | --- |
| `recover_after_disconnect` after controlled transport disconnect | SKIPPED | only safely constructible by forcing transport tamper against the live sim client; not done to avoid destabilizing the sim session |
| partial fill + cancel/reconcile | SKIPPED | would require racing the broker or placing repeated orders to land a partial state; budget + non-forcing principle |
| broker cancel rejection + recovery | SKIPPED | would require a broker-side rejection that is not naturally constructible here |
| UNKNOWN/ambiguous observation recovery | SKIPPED | covered by Core/TGrid automated tests; not naturally constructible against the live sim without tampering |
| active-order crash/restart beyond clean close | SKIPPED | the two accidental run-interruption recoveries above already exercised restart/recovery semantics naturally |

## E. Findings / notes

1. The simulation client's account-discovery query
   (`query_account_infos`/`query_account_status`) occasionally returned empty
   immediately after a crashed/closed trader connection, causing the
   Gate-6.1 runner's `_make_qec_binding` account probe to fail transiently
   ("expected exactly one normal sim account"); a subsequent identical call
   succeeded. Fail-closed and non-broker-affecting; retried.
2. Two controlled script interruptions left real WORKING sim orders
   (TG_G61_B001/B002) with OPEN Core claims; both were recovered through
   their durable journals (no blind resend) and cancelled — this is exactly
   the restart/recovery semantics Gate-6.1 was asked to cover, and all
   resources were released on RESOLVED finality.

## F. Safety statement

- `live_trading_allowed=false`; no live/real-money order or cancel.
- Simulation order/cancel totals at the authorized maxima (2/2); no second
  symbol, no parameter expansion, no repeated order forcing.
- No production `src/tgrid` or pinned-Core modification; no Authority/DB
  recreation; the established Runtime Authority identity was used
  verify-only throughout.
