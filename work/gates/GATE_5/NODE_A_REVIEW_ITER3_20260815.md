# Audit Node A Re-Review — Iteration 3 — 2026-08-15

## Verdict

`CHANGES_REQUIRED` — Gate 5 is not independently accepted yet.

Review target: GitHub `main` snapshot `03d392341d0c558c5a2461637e6ac5cade6645ed`.

The Iteration-3 changes materially improved the implementation. The following items are independently accepted and should not be redone unless required by the remaining fixes:

- NODEA-002 settlement released-balance carry-forward is acceptable for Gate-5 scope;
- NODEA-005 tracked `_tmp/` removal is verified: `_tmp` is absent from the current GitHub HEAD;
- `BasisBinding` metadata consistency checks are acceptable;
- structural separation of real reconciliation and shadow delta remains acceptable;
- no real order/cancel capability was introduced; `live_trading_allowed=false` remains binding;
- Gate 5.5 / Gate 6 / Gate 7 remain blocked.

## Remaining Findings

### NODEA-R3-001 — P0: basis transform exists, but the REAL runner does not establish a trustworthy per-day factor

`basis_transform.py` correctly defines an explicit ADJUSTED->RAW transform, but `scripts/gate5_shadow_live.py` currently exposes one scalar CLI argument:

```text
--adjusted-to-raw-factor   default=1.0
```

and reuses that same scalar for every day in a multi-day replay. This does not establish the actual adjustment relationship for each active trading day. On/around a corporate action, a default or stale factor can still make an ADJUSTED anchor/previous-close numerically incomparable with RAW 5m prices.

Required:

1. Remove the implicit `1.0` default for ADJUSTED history in the real-QMT runner.
2. For each replay/live trading day, obtain an explicit trusted same-day factor from a deterministic source. Acceptable designs include:
   - a read-only XtQuant corporate-action/dividend-factor source, normalized behind a narrow adapter; or
   - an explicit trusted local factor map keyed by symbol + trade_date, with no missing-day fallback.
3. The factor must be per trade date; one scalar may not silently cover a multi-day replay.
4. Missing/ambiguous factor => fail closed before strategy decisions for that day.
5. Evidence must record factor provenance/type and a sanitized per-day factor binding (or hashes), not merely `daily=ADJUSTED` / `5m=RAW`.
6. Add an integration-level strategy test with a material 2:1 discontinuity proving that BUY/volatility decisions are economically invariant after normalization. The current test only validates the pure arithmetic transform; it does not exercise `AccumulateStrategy` decisions across differing RAW/ADJUSTED scales.
7. Remove the pre-loop `shadow.begin_day(daily, trade_date=args.date)` that initializes ADJUSTED bars as implicit RAW and can move the settlement clock backward when the replay later starts on an earlier date. Add monotonic trading-day validation or otherwise reject backwards session transitions.

Until this is fixed, the existing 10-day real-QMT replay is not accepted as basis-domain evidence.

### NODEA-R3-002 — P1: settlement and strategy configuration are still inferred/loaded from the wrong source

The real-QMT runner still defaults settlement by market suffix (`.HK -> T0`, `.SH/.SZ -> T1`) and only requires `--settlement` for unknown suffixes. The previous requirement was stricter: settlement must come from trusted per-symbol configuration or an explicit CLI value; suffix inference is not an authorization/configuration source.

The runner also derives the strategy configuration path as:

```text
Path(args.config).parent / "config.example.yaml"
```

That is an example file, not the trusted runtime strategy configuration. The repository example currently does not contain the 510300.SH symbol used by the replay evidence, so the latest runner/evidence is not reproducible from the checked-in code path.

Required:

1. Add an explicit trusted strategy-config input (for example `--strategy-config`) or equivalent local configuration binding; do not use `config.example.yaml` as runtime strategy state.
2. The requested symbol must exist in that trusted strategy config; otherwise fail closed.
3. Settlement must be explicit in trusted per-symbol config or required via CLI. No suffix-based default for an executable Gate-5 run.
4. If the runner supports multiple exchanges, session hours must also come from an explicit market/symbol policy. Do not apply the A-share 09:30-11:30 / 13:00-15:00 session to HK symbols. Alternatively, explicitly restrict this runner to the validated market until HK session policy is implemented.
5. Tests must prove missing strategy config / missing settlement / unknown session policy cause zero strategy execution.

### NODEA-R3-003 — P1: real broker reconciliation still lacks trusted local decomposition in the real-QMT runner

The offline synthetic evidence now supplies `strategic_extra` independently, which is an improvement. However the REAL-QMT runner still hard-codes:

```text
strategic_extras={code: 0}
open_t_positions={code: 0}
```

without loading those values from trusted local state. Therefore a `reconciled=true` result only proves a special case where zero happens to be correct; it does not prove real reconciliation semantics for a non-zero Core/Strategic/OpenT book.

Required:

1. Real expected decomposition must be loaded from explicit trusted local state:
   - Core from trusted symbol config;
   - StrategicExtra from an explicit local state source/config;
   - persisted/open real T quantity from the ledger/state source.
2. Unknown component is not equivalent to zero. If a required component is unavailable, reconciliation status must be `UNKNOWN` / `SAFE_MODE` input, not a guessed numeric value.
3. Produce a sanitized REAL_QMT non-zero-position summary proving the path used a non-zero trusted local decomposition. It must not expose actual holdings/cash/account/path/port; booleans/count classes/hashes are sufficient.
4. If MiniQMT/non-zero position evidence is unavailable, mark this acceptance item explicitly `BLOCKED` and do not claim Gate-5 independent readiness.

### NODEA-R3-004 — P1: control plane and self-certification claims are still inconsistent

The latest commit message and `NODEA_FIX_REPORT.md` claim:

- 832 tests OK;
- a real commit SHA was recorded;
- control plane is consistent;
- a 2:1 split invariance test exists.

But the checked-in canonical files still disagree:

- `WORKFLOW_STATE.yaml` contains `git_head_commit: PENDING_PUSH`;
- `CURRENT_TASK.md` still says 818 tests and still describes the older AUD-R1 remediation completion record;
- the actual `test_node_a_fixes.py` validates the transform arithmetic but does not contain the claimed strategy decision invariance test.

Required:

1. Canonical state/task/docs/report must use one exact regression count and one exact evidence status.
2. The DSH handoff must record a concrete implementation/evidence commit SHA, not `PENDING_PUSH`. If the file is written before commit creation, use a deterministic two-stage convention that is truthful (e.g. record `implementation_commit` after the implementation commit, then a metadata-only handoff commit whose parent is that implementation commit).
3. Do not claim tests/evidence that are not present in the repository.
4. Use `REAL_QMT_REPLAY_VERIFIED` only for historical replay evidence; `LIVE_SOAK_VERIFIED` remains a separate future milestone.
5. Final state after fixes: `AUDIT_READY`, `authorized_next=[AUDIT_NODE_A_REVIEW]`, Gate 5.5/6/7 blocked, `live_trading_allowed=false`.

## Verification Required for Iteration 4

DSH must provide self-certified evidence for:

1. full unit regression + `compileall` + capability AST scan;
2. real strategy-level 2:1 RAW/ADJUSTED normalization test;
3. trusted per-day factor source/binding and missing-factor fail-closed test;
4. trusted strategy config + explicit settlement/session policy tests;
5. real reconciliation state-source tests where unknown Strategic/OpenT cannot become zero silently;
6. sanitized non-zero REAL_QMT reconciliation summary, or explicit BLOCKED status if unavailable;
7. exact canonical commit/test/evidence metadata consistency;
8. no live order/cancel capability and `live_trading_allowed=false`.

## Stop Condition

After the Iteration-4 fixes, DSH must push normally, set `state=AUDIT_READY`, record the exact implementation/evidence SHA(s), and STOP. Do not implement Gate 5.5 and do not invoke or introduce a real order/cancel path before independent Node-A PASS.
