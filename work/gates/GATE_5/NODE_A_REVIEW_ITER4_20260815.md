# Audit Node A Re-Review — Iteration 4 — 2026-08-15

## Verdict

`CHANGES_REQUIRED` — Gate 5 is still not independently accepted.

Review target: GitHub `main` snapshot `e6091ee77e1a9e534c02318eec6dd91a974b894e`.
Implementation commit immediately below the metadata commit is `4e7d04a27733df52c902321fd4049d5a3a1a3bab`.

Iteration 4 materially improved the implementation. The following items are independently accepted and must not be reworked unless required by the remaining fixes:

- per-day `DailyFactorRegistry` has no implicit 1.0 fallback and missing-day lookup fails closed;
- strategy-level RAW/ADJUSTED 2:1 decision-invariance tests now exist;
- trusted `--strategy-config` replaced runtime use of `config.example.yaml`;
- executable settlement is no longer inferred by symbol suffix; SH/SZ-only session restriction is acceptable for Gate-5 scope;
- settlement carry-forward and tracked `_tmp/` cleanup remain accepted;
- no real order/cancel capability was introduced; `live_trading_allowed=false` remains binding;
- Gate 5.5 / Gate 6 / Gate 7 remain blocked.

## Remaining Findings

### NODEA-R4-001 — P0: historical replay has same-day daily-bar look-ahead

Design §9 requires Anchor/ATR to be calculated before market open and frozen for the day. Therefore a replay for trade date D may only use completed daily bars strictly before D.

The current runner downloads daily history through `args.date`, then for each replay day builds:

```python
day_bars = daily[: len(daily) - (len(trading_days) - index)]
```

For the final replay day this is the entire daily series, including that day's 15:00 daily bar. For aligned earlier replay days the same slicing also includes the current day's completed daily bar. This is future information at the 09:xx pre-market decision point and contaminates Anchor, ATR, volatility-halt references and therefore the historical shadow PnL/signals.

Required:

1. For each replay day D, construct the indicator history only from bars with `bar_date < D`.
2. Never use a daily bar from D itself to compute D's pre-market basis.
3. Fail closed if the strictly-prior history is insufficient for the configured VWAP/EMA/ATR requirements.
4. Add a look-ahead FI: changing D's daily OHLC/volume by an extreme amount must not change D's pre-market basis or any D intraday decision.
5. Add a boundary test proving the last prior completed daily bar is included and the current-day bar is excluded.
6. Re-run all committed REAL_QMT historical replay evidence after this fix; the existing 10-day PnL/signal evidence is not accepted because it predates this correction.

### NODEA-R4-002 — P0: reconciliation state reintroduces a second Core authority

The established position invariant is that `SymbolConfig.core_qty` is the sole Core source. The current runner loads a second `core_qty` from `--reconciliation-state` and constructs:

```python
ShadowEngine(..., core_qty=rec_state["core_qty"])
```

while the strategy independently holds `symbol_cfg.core_qty`. If those values differ, Core-floor/reconciliation semantics can diverge.

Required:

1. `SymbolConfig.core_qty` must remain the sole Core authority.
2. Prefer removing `core_qty` from the reconciliation-state schema entirely. That state should provide only independently known `strategic_extra` and persisted/open real T quantity.
3. If legacy reconciliation input still carries a Core field, it must be checked for exact equality with `symbol_cfg.core_qty` and then discarded; mismatch => fail closed before strategy execution.
4. Construct `ShadowEngine` from `symbol_cfg.core_qty`, not an independent state value.
5. Add a mismatch FI proving two Core values can never silently coexist.

### NODEA-R4-003 — P1: current Gate-5 operational evidence/runbook is stale and no longer executable

`LIVE_VERIFICATION.md` still says `LIVE VERIFIED`, uses the old command, and reports the old 10-day result (+13.3) produced before the current factor/config/reconciliation changes and before NODEA-R4-001 is fixed.

`GATE5_RUNBOOK.md` also still uses the old CLI, omits `--strategy-config`, `--factor-map`, `--reconciliation-state` and explicit settlement, and contains local absolute paths. It is therefore both stale and inconsistent with the current runner/hygiene policy.

Required after R4-001/R4-002 are fixed:

1. Rewrite the runbook to the current CLI using placeholders only; remove machine-specific absolute paths.
2. Mark the old verification/result as `SUPERSEDED` / historical evidence, not current Gate-5 acceptance evidence.
3. Run a fresh REAL_QMT historical replay with the current code, trusted strategy config, explicit settlement, per-day factor map and trusted reconciliation state.
4. Commit only sanitized evidence. Evidence must bind at least: code/implementation SHA, symbol class, replay dates/count, factor-map provenance and hash/identifier, reconciliation-state provenance/hash/identifier, basis modes, settlement, signal/order counts and reconciliation result.
5. Provide a sanitized non-zero REAL_QMT reconciliation summary if a suitable non-zero configured symbol is available. If it is unavailable, state that limitation explicitly; do not substitute synthetic evidence while calling it REAL_QMT.
6. `LIVE_SOAK_VERIFIED` remains a separate future evidence class.

### NODEA-R4-004 — P1: canonical implementation SHA is invalid

`WORKFLOW_STATE.yaml` records:

```text
git_head_commit: 4e7d04a0bdefd2bc30638d5a2b63e7e8aa742143
```

That SHA does not exist. The actual Iteration-4 implementation commit is:

```text
4e7d04a27733df52c902321fd4049d5a3a1a3bab
```

and the metadata-only child commit is:

```text
e6091ee77e1a9e534c02318eec6dd91a974b894e
```

Required:

- use exact GitHub SHAs only;
- distinguish `implementation_commit` from the later metadata/handoff commit if both are recorded;
- make `WORKFLOW_STATE`, `CURRENT_TASK`, `docs/GATES`, runbook and Gate-5 reports agree on status/test count/evidence class;
- final DSH state after fixes must be `AUDIT_READY`, authorize only `AUDIT_NODE_A_REVIEW`, and keep Gate 5.5/6/7 blocked.

## Verification Required for Iteration 5

DSH must provide SELF_CERTIFIED evidence for:

1. full regression + compileall + capability AST scan;
2. strict-prior-day pre-market basis / no-look-ahead FI;
3. single-Core-authority mismatch FI;
4. per-day factor missing/fail-closed tests retained;
5. current CLI/runbook consistency;
6. refreshed current-code REAL_QMT replay evidence (or explicit environment blocker, without claiming independent Gate readiness);
7. exact commit SHA/control-plane consistency;
8. `_tmp/` remains absent; no local paths/account values in committed evidence;
9. no real order/cancel capability and `live_trading_allowed=false`.

## Stop Condition

After Iteration-5 fixes, DSH must push normally, set `state=AUDIT_READY`, record exact implementation/evidence SHA(s), and STOP. Do not implement Gate 5.5 and do not introduce/invoke real order/cancel capability before independent Node-A PASS.
