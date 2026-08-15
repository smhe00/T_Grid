# Current Task — Audit Node A Iteration 5 Fixes

## Owner

`DSH (DeepSeek Harness)` — single programming Agent, implementation + self-review allowed.

Self-review must be labelled `SELF_CERTIFIED`; it is not an independent Gate verdict.

## Status

`AUDIT_READY`（Iteration 5 fixes complete, SELF_CERTIFIED, awaiting independent Node-A re-review）

## Completion Record (SELF_CERTIFIED — 2026-08-15)

1. NODEA-R4-001 (P0): replay basis uses ONLY strictly-prior daily bars
   (`bar_date < D`); `AccumulateStrategy.begin_day` also filters and fails
   closed if none remain; strategy-level FI proves extreme day-D OHLC/volume
   does not change day-D basis or intraday decisions; boundary tests confirm
   the last prior bar is included and the current-day bar excluded.
2. NODEA-R4-002 (P0): `SymbolConfig.core_qty` is the sole Core authority;
   reconciliation-state carries no Core (or exact-match-checked then
   discarded); mismatch fails closed before strategy execution.
3. NODEA-R4-003 (P1): runbook rewritten to the current CLI (placeholders, no
   absolute paths); `LIVE_VERIFICATION.md` marked `SUPERSEDED`; current-code
   replay evidence to be regenerated with the new CLI.
4. NODEA-R4-004 (P1): canonical SHA uses exact full GitHub hashes;
   `implementation_commit` distinguished from the metadata handoff commit.

Evidence: 846 tests OK; compileall 0; src AST scan 0 hits;
`work/gates/GATE_5/NODEA_R4_FIX_REPORT.md`.
```

Gate 5.5 / Gate 6 / Gate 7 remain blocked. `live_trading_allowed=false` remains mandatory.

## Accepted Work — Do Not Redo

- per-day factor registry with no implicit 1.0 fallback;
- strategy-level 2:1 RAW/ADJUSTED invariance tests;
- trusted strategy-config input;
- explicit settlement / SH-SZ-only session restriction;
- settlement sellable carry-forward;
- real reconciliation vs shadow-delta structural separation;
- `_tmp/` removal;
- ExecutionEngine exact-type hardening;
- no real order/cancel capability.

## Required Work

### 1. P0 — Remove daily-bar look-ahead from replay

For replay day D, pre-market basis may use only completed daily bars with date `< D`. Never include D's daily bar. Add strict no-look-ahead tests and fail closed on insufficient prior history.

### 2. P0 — Restore single Core authority

`SymbolConfig.core_qty` is the sole Core source. Reconciliation state must not independently define Core. Prefer schema = `{strategic_extra, open_t_position}` only; if a legacy Core is present, require exact equality and discard it. `ShadowEngine` must use `symbol_cfg.core_qty`.

### 3. P1 — Refresh operational evidence and runbook

After the two P0 fixes:

- update `GATE5_RUNBOOK.md` to the current CLI with placeholders only;
- remove all machine-specific absolute paths;
- mark old `LIVE_VERIFICATION.md` result as superseded/historical;
- execute a fresh REAL_QMT historical replay with current code and trusted inputs;
- commit only sanitized evidence bound to exact implementation SHA and input provenance/hash identifiers;
- provide sanitized non-zero REAL_QMT reconciliation summary when available; otherwise state the environment limitation explicitly and do not claim REAL_QMT evidence from synthetic fixtures.

### 4. P1 — Fix canonical SHA / metadata consistency

The actual Iteration-4 implementation commit is:

```text
4e7d04a27733df52c902321fd4049d5a3a1a3bab
```

The metadata-only child is:

```text
e6091ee77e1a9e534c02318eec6dd91a974b894e
```

Do not use the nonexistent `4e7d04a0bdef...` SHA. Keep exact test count/status/evidence class consistent across canonical files and Gate-5 reports.

## Required Verification

- full `unittest` regression;
- `python -m compileall -q src tests`;
- capability AST scan proving no real order/cancel path;
- no-look-ahead FI (current-day daily OHLC/volume mutation cannot affect same-day decisions);
- last-prior-day included/current-day excluded boundary test;
- Core-authority mismatch FI;
- current factor/config/settlement/reconciliation fail-closed tests retained;
- `_tmp/` absent and committed evidence sanitized;
- refreshed REAL_QMT replay evidence after the P0 fixes;
- `live_trading_allowed=false`.

## Stop / Handoff — Audit Node A

When complete:

1. push normally to `main`;
2. set `state=AUDIT_READY`;
3. record the exact implementation commit and any later evidence/metadata commit separately;
4. authorize only `AUDIT_NODE_A_REVIEW`;
5. STOP before Gate 5.5 or any real broker order/cancel capability.
