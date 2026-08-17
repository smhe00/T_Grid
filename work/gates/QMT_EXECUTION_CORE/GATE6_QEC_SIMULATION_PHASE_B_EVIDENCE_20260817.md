# Gate-6 QEC Simulation — Phase B (single positive BUY) Evidence

> Date: 2026-08-17 (09:34 +08:00)
> Task: `GATE6-QEC-SIMULATION-CLOSED-LOOP` (user-authorized, simulation only)
> Author: DSH. Evidence SELF_CERTIFIED until independent audit
> (`AUDIT_GATE6_QEC_SIMULATION_EVIDENCE`).
> `live_trading_allowed=false`; zero live/real-money calls.

## 0. Locked baselines

```text
TGrid implementation : 1790812bb7ef7f6ceb35b2dcc18da49dabfc7451
Core 0.4.1           : a68572decb799bcbbf1b2892fcf58ac321ce9636
```

## 1. Simulation-account proof (re-verified before submit)

```text
Gate-1 config environment        : simulation
runtime_config simulation_qmt_path: D:\国金QMT交易端模拟\userdata_mini  (simulation client)
runtime_config live_qmt_path      : D:\国金证券QMT交易端\userdata_mini   (NOT used)
account binding environment       : simulation
account binding label             : repo_simulation
account_id_sha256                 : 7424e0cd66f135606bf4036df6414a412c8f0d4dc0a0ccd9d082cf705537e030
```

The positive order ran against the SIMULATION QMT client only; the live path
was never referenced or connected.

## 2. Preflight (this run)

```text
is_trading_day      : true   (SH get_trading_dates confirms 2026-08-17)
in_execution_window : true   (09:34 +08:00, morning window)
session_built       : true   (Core 0.4.1 canonical Runtime Authority, verify-only)
```

## 3. Single positive simulation BUY (authorized scope)

```text
symbol          : 510300.SH
side            : BUY
qty             : 100        (exactly one t_unit; qty_cap 200 not exceeded)
cash_cap        : 5000 CNY   (not exceeded; exposure_used 473.4)
quote_price     : 4.734      (fresh quote immediately before submit)
broker_order_id : 1090520375 (simulation)
result          : FILLED, filled_qty 100
terminal_state  : FILLED
```

No cancel was issued (order filled within the bounded poll window).
Reconcile confirmed `filled_qty=100, status=filled`.

## 4. Post-run state (Core + TGrid)

```text
Core symbol_claim rows      : 0  (RESOLVED finality -> claim released)
Core cash_reservation rows  : 1  (active=0, released_at set)
Core active_reserved_cash   : 0.0
TGrid intent                : TG_G6SIM_B001 510300.SH BUY status=FILLED
                              broker_order_id=1090520375
TGrid active reservations   : []  (released)
```

## 5. Order/cancel side-effect accounting

```text
simulation order_stock calls : 1  (the single authorized BUY)
simulation cancel calls      : 0
live/real-money calls        : 0
Authority/DB recreation      : none
production code changes      : none
```

## 6. Safety statement

- `live_trading_allowed=false`; no live or real-money order/cancel invoked.
- Exactly one simulation BUY (510300.SH, 100 shares) was placed, matching the
  authorized scope; no second order, no alternate symbol, no parameter
  expansion, no automatic Authority/DB recreation.
