# Current Task — Audit Node A Iteration 3 Fixes

## Owner

`DSH (DeepSeek Harness)`

## Status

`CHANGES_REQUIRED`

Gate 5.5 / Gate 6 / Gate 7 remain blocked. `live_trading_allowed=false` is mandatory.

## Review Source

Read and execute:

```text
work/gates/GATE_5/NODE_A_REVIEW_20260815.md
```

Review target / new remediation base:

```text
910a727d3ef66c262abfd9dea45b092106f6d4a6
```

## Required Fixes

Only close the six Node-A findings; do not expand into Gate 5.5:

1. **NODEA-001** — normalize ADJUSTED daily indicator price-domain into RAW trading-price domain before any comparison; add material corporate-action scale-discontinuity FI and metadata-consistency checks.
2. **NODEA-002** — fix settlement released-quantity carry-forward across later sessions; add >=3-day, partial-sell and T0 carry-forward tests.
3. **NODEA-003** — remove settlement/symbol guessing in real-QMT runner; explicit per-symbol settlement policy required; unknown/missing symbol config fails closed.
4. **NODEA-004** — remove `held-core -> Strategic` inference; real reconciliation components must be independently supplied from trusted local state; regenerate nonzero evidence without silent reclassification and commit only a sanitized summary/hash manifest.
5. **NODEA-005** — remove tracked `_tmp/` from current HEAD with a normal forward commit; no history rewrite/force push.
6. **NODEA-006** — make WORKFLOW_STATE/CURRENT_TASK/docs/reports agree on exact test count, concrete implementation SHA and replay-vs-live-soak terminology.

## Accepted / Do Not Rework Without Cause

- explicit XtQuant `dividend_type` request plumbing;
- separate `reconciliation` vs `shadow_delta` report structures;
- AUD-R1-007 ExecutionEngine exact-type capacity hardening;
- no-live-order boundary.

## Required Evidence

- full unit regression;
- `python -m compileall -q src tests`;
- AST/capability scan proving no real order/cancel path;
- corporate-action basis-domain FI with materially different RAW/ADJUSTED scale;
- settlement 3-day carry-forward + partial-sell + T0 carry-forward;
- explicit-policy unknown-symbol fail-closed tests;
- nonzero reconciliation using independently known Core/Strategic/OpenT, never broker residual inference;
- sanitized REAL_QMT nonzero evidence summary if available; if unavailable, mark that acceptance item BLOCKED instead of substituting synthetic evidence;
- proof `_tmp/` no longer exists in GitHub current HEAD.

## Stop / Handoff

When fixed:

1. push normally to `main`;
2. set canonical `state=AUDIT_READY`;
3. record exact implementation/evidence commit SHA and exact test count;
4. `authorized_next` must contain only `AUDIT_NODE_A` (or be empty for DSH execution);
5. STOP before Gate 5.5.

ChatGPT will perform Audit Node A again. No real order/cancel capability may be added in this task.
