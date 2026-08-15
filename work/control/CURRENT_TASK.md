# Current Task — Audit Node A Iteration 4 Fixes

## Owner

`DSH (DeepSeek Harness)` — single programming Agent, implementation + self-review allowed.

Self-review must be labelled `SELF_CERTIFIED`; it is not an independent Gate verdict.

## Status

`AUDIT_READY`（Iteration 4 fixes complete, SELF_CERTIFIED, awaiting independent Node-A re-review）

## Completion Record (SELF_CERTIFIED — 2026-08-15)

1. NODEA-R3-001: trusted per-day ADJUSTED->RAW factor registry
   (`tgrid.shadow.daily_factor.DailyFactorRegistry`, no 1.0 default, missing
   day fail-closed); runner uses per-day factors, removes the pre-loop
   `begin_day` seed, days advance monotonically; strategy-level 2:1 split
   invariance tests prove BUY/no-buy/volatility-halt decisions are identical
   across RAW and ADJUSTED scales.
2. NODEA-R3-002: runner requires `--strategy-config` (trusted; never
   `config.example.yaml`), symbol must be configured, settlement explicit
   (`--settlement` or config; no suffix default), market restricted to SH/SZ
   (HK session policy not implemented -> fail closed).
3. NODEA-R3-003: real reconciliation loads Core/Strategic/OpenT from
   `--reconciliation-state` trusted JSON; unknown component fails closed,
   never silently zero.
4. NODEA-R3-004: canonical metadata unified to **840 tests OK**; real commit
   SHA recorded post-push; evidence wording `REAL_QMT_REPLAY_VERIFIED`.

Evidence: 840 tests OK; compileall 0; src AST scan 0 hits;
`work/gates/GATE_5/NODEA_R3_FIX_REPORT.md`.

Gate 5.5 / Gate 6 / Gate 7 are blocked. `live_trading_allowed=false` remains mandatory.

## Review Source

Execute the narrow fixes in:

```text
work/gates/GATE_5/NODE_A_REVIEW_ITER3_20260815.md
```

Review target/baseline:

```text
03d392341d0c558c5a2461637e6ac5cade6645ed
```

## Required Work

Only the remaining Node-A findings need closure. Retain the already accepted Iteration-3 work.

1. **Basis factor provenance / per-day normalization**
   - real-QMT runner must not default ADJUSTED->RAW factor to 1.0;
   - factor must be trusted and keyed to each trading day;
   - missing/ambiguous factor fails closed;
   - add strategy-level 2:1 discontinuity test, not only arithmetic transform test;
   - remove the pre-loop `begin_day` that seeds the replay with a backwards session transition; enforce monotonic trading sessions.

2. **Trusted strategy/settlement/session configuration**
   - no runtime use of `config.example.yaml` as trusted strategy state;
   - add explicit local strategy config binding;
   - symbol must be configured;
   - settlement must be explicit via trusted config or required CLI, not suffix default;
   - session policy must be explicit per supported market, or restrict the runner to a validated market.

3. **Trusted real reconciliation decomposition**
   - Core / StrategicExtra / persisted real OpenT must come from independent trusted local state;
   - unavailable component => UNKNOWN/SAFE_MODE input, never implicit zero;
   - produce sanitized non-zero REAL_QMT reconciliation summary, or mark this acceptance item BLOCKED if the evidence cannot be obtained.

4. **Control/evidence consistency**
   - make `WORKFLOW_STATE`, `CURRENT_TASK`, `docs/GATES`, fix report and commit messages agree on exact test count/status;
   - record concrete implementation/evidence SHA(s), not `PENDING_PUSH`;
   - do not claim strategy invariance/evidence not actually present.

## Required Verification

- full unit regression;
- `python -m compileall -q src tests`;
- capability AST scan proving no real order/cancel path;
- strategy-level basis normalization FI with materially different RAW/ADJUSTED scales;
- missing factor/config/settlement/session fail-closed tests;
- reconciliation unknown-component tests;
- `_tmp/` remains absent from current HEAD;
- `live_trading_allowed=false`.

## Stop / Handoff

When complete:

1. push normally to `main`;
2. set canonical state to `AUDIT_READY`;
3. record exact implementation/evidence commit SHA(s), tests and open blockers;
4. authorize only `AUDIT_NODE_A_REVIEW`;
5. STOP before Gate 5.5 / any real broker order or cancel capability.
