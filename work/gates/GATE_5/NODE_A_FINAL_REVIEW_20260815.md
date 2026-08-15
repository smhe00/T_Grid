# Gate 5 Audit Node A — Final Independent Review — 2026-08-15

## Verdict

`PASS` — Gate 5 Shadow Mode is independently accepted.

Audit target GitHub `main` snapshot:

```text
df1cbb53471d8f765c89c4bc644323d5839d0dd6
```

Iteration-5 implementation commit:

```text
5a2e2fd32e21328badd1ceb2c92b973436c4c95a
```

This PASS is scoped to **Gate 5 Shadow execution only**. It is not authorization to send, cancel, or amend a real broker order. `live_trading_allowed=false` remains mandatory.

## Independently Accepted

### 1. No-look-ahead replay basis

The real-QMT replay now forms each day-D indicator history only from completed daily bars with `bar_date < D`. `AccumulateStrategy.begin_day` independently applies the same guard, so a caller cannot accidentally inject day-D 15:00 information into the pre-market basis.

The Iteration-5 tests include a fault-injection case where day-D OHLC/volume is changed to an extreme value and day-D anchor / previous close / intraday decision remain unchanged, plus a boundary case proving the last prior daily bar is included and the current-day bar is excluded.

This closes NODEA-R4-001 and removes the look-ahead contamination in the earlier replay.

### 2. RAW / ADJUSTED basis discipline

Previously accepted remediation remains valid:

- daily indicator acquisition is explicit `front` / `ADJUSTED`;
- 5-minute execution reference is explicit `none` / `RAW`;
- a per-(symbol, trade_date) `DailyFactorRegistry` is required;
- there is no implicit 1.0 fallback for a missing replay day;
- strategy-level 2:1 scale-discontinuity tests exercise BUY / NO_ACTION / volatility-halt invariance.

### 3. Settlement / sellability model

The persistent released-balance settlement model remains accepted for Gate-5 scope: same-day T1 shadow buys are not immediately sellable, released quantity carries into later sessions until consumed, and SH/SZ replay uses an explicit settlement rule and validated A-share session policy.

### 4. Core authority and reconciliation semantics

The actual runtime construction now uses:

```text
CoreQty = SymbolConfig.core_qty
```

and `ShadowEngine` is constructed from that value rather than from reconciliation-state input. Real broker reconciliation remains separated from hypothetical shadow delta, and StrategicExtra / persisted OpenT are supplied from explicit trusted local state rather than inferred from broker residual.

This is sufficient to close the original second-Core blocker for Gate 5.

### 5. Current-code REAL_QMT replay evidence

A new evidence set exists under:

```text
work/reports/shadow/r4-10day-2026-08-14/
```

and is materially different from the superseded pre-fix replay, confirming that the run was regenerated after the basis corrections. The current evidence records:

- class: `REAL_QMT_HISTORICAL_REPLAY + REAL_BROKER_SNAPSHOT`;
- 10 replay dates from 2026-08-03 through 2026-08-14;
- daily `front` / ADJUSTED and 5m `none` / RAW;
- 10 per-day factor bindings with trusted-local-map provenance;
- SHA-256 identifiers for factor map, strategy config and reconciliation state;
- settlement `T1` for `510300.SH`;
- Core authority = `SymbolConfig.core_qty`;
- 4 shadow orders (2 WOULD_BUY + 2 WOULD_SELL);
- realized shadow T PnL = 13.1 for this historical replay;
- real reconciliation delta = 0;
- final shadow delta = 0.

The prior +13.3 report is explicitly marked `SUPERSEDED` and is not used for acceptance.

The currently committed real-QMT reconciliation sample has a zero real position. Non-zero reconciliation semantics are covered by the offline decomposition tests; a sanitized non-zero REAL_QMT sample remains desirable when a suitable environment/holding is available, but is not required to keep Gate 5 in shadow-only status.

### 6. Repository hygiene / live boundary

Tracked `_tmp/` artifacts were removed in the prior iteration and remain outside the accepted evidence path. Gate-5 evidence uses sanitized hashes/provenance rather than committing local account, path, port or cash details.

No real order/cancel capability is authorized by this Gate. The DSH regression report states 846 tests OK, compileall exit 0 and a clean capability AST scan; these remain `SELF_CERTIFIED` test-execution evidence. The independent auditor inspected the implementation and committed evidence but could not independently rerun the suite because the audit runtime had no network path to clone GitHub, and this repository has no GitHub CI status for the implementation commit.

## Mandatory Carry-Forward to Audit Node B

The following item is **not a Gate-5 blocker**, because the engine already uses `SymbolConfig.core_qty` exclusively, but it becomes a mandatory pre-live blocker:

### NODEB-P0-001 — legacy reconciliation `core_qty` mismatch guard is not wired through the loader

`_load_reconciliation_state()` currently returns only `strategic_extra` and `open_t_position`, so an optional legacy `core_qty` field is discarded before `_check_core_authority()` is called. Therefore the code does **not** actually perform the documented fail-closed comparison for a legacy file carrying a mismatched Core.

Before Audit Node B can PASS, DSH must do one of the following:

1. reject `core_qty` as an unexpected reconciliation-state field; or
2. preserve it long enough to compare it exactly with `SymbolConfig.core_qty`, then discard it.

A full loader-to-runner test must prove `legacy core != configured core` fails closed before any broker execution capability can be invoked.

## Gate 5.5 Authorization

Gate 5.5 implementation is now authorized **for code development only**.

DSH may implement the real Broker Adapter / pre-live execution capability, but must not invoke any real `order` or `cancel` operation. The implementation must stop at `AUDIT_READY_PRELIVE` for Audit Node B.

Node B must independently verify at minimum:

- live default OFF plus an explicit second runtime confirmation;
- symbol allowlist and hard per-order / per-day quantity and cash limits;
- kill switch;
- callback -> Event Queue isolation;
- idempotent OrderIntent + Reservation before broker send;
- partial fill handling;
- timeout -> cancel -> re-query semantics without assuming cancellation implies zero fill;
- order/trade reconciliation and crash recovery;
- exact-type fail-closed validation;
- NODEB-P0-001 legacy-Core mismatch guard;
- no real order invocation before Node-B PASS.

Gate 6 remains blocked until **Audit Node B PASS + explicit user authorization**.

## Final State

```text
Gate 5   = PASS
Gate 5.5 = AUTHORIZED_FOR_IMPLEMENTATION_ONLY
Gate 6   = BLOCKED
Gate 7   = BLOCKED
live_trading_allowed = false
```
