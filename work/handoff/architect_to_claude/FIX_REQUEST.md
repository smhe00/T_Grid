# FIX_REQUEST — Gate-6.2 T+0 Intraday Roundtrip — Iteration 2

Status: **CHANGES_REQUIRED**

Task remains:

```text
GATE6.2-T0-INTRADAY-ROUNDTRIP-20260820
```

Review target:

```text
032c54815ccc3f20e13761745e24ee4d2549cd94
```

Authoritative audit:

```text
work/gates/GATE_6/GATE6_2_T0_INTRADAY_ROUNDTRIP_AUDIT_20260820.md
```

## Required fixes only

1. Remove `work/reports/gate6-sim/gate6-sim-negative-2026-08-15.json` from current HEAD using a normal forward commit. Do not rewrite history or force push.
2. Fix `scripts/gate6_t0_roundtrip.py` so recovery may skip BUY only when authoritative TGrid/Core/broker evidence proves `TG_G62_A` FILLED exactly 100; never infer task ownership from account position alone.
3. Implement bounded unresolved-leg handling exactly as: at most one cancel through TGrid -> Core, authoritative reconcile, then STOP. No blind retry.
4. Enforce quote timestamp freshness and a conservative explicit spread bound immediately before both BUY and SELL submits; stale/invalid/wide quote must fail closed.
5. Remove committed account-specific runtime/account identifier literals. Resolve identity from the already-built simulation runtime/binding or local ignored configuration.
6. Update implementation/test reports to acknowledge the prior conflict-merge/protocol deviation and the out-of-scope tracked JSON. Do not claim a four-file-only history when Git history shows otherwise.
7. Re-run offline verification:

```text
python -m compileall -q src scripts
python -m pytest -q tests/unit/test_qec_runtime.py tests/unit/test_qec_iter16.py
qmt-execution-core verify
```

Also provide failure-injection evidence for stale quote, wide spread, unrelated pre-existing position, and unresolved cancel/reconcile behavior.

## Explicitly authorized repository files for this fix iteration

```text
scripts/gate6_t0_roundtrip.py
work/reports/gate6-sim/gate6-sim-negative-2026-08-15.json   # deletion only
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md
work/handoff/claude_to_architect/TEST_REPORT.md
work/control/WORKFLOW_STATE.yaml
```

No production `src/`, `tests/`, public Core, strategy config, runtime binding, protocol, or other repository changes are authorized.

## Broker authorization boundary

The user separately authorizes additional submits/cancels/retries/symbol or quantity changes when strictly confined to the QMT simulation account. This fix request does **not require** another broker roundtrip; prefer offline/failure-injection verification for these fixes. Any broker side effect must prove simulation binding first. Live/real calls remain prohibited and `live_trading_allowed=false` remains mandatory.

## Handoff requirement

When fixes are complete:

```text
state = REVIEW_READY
owner = architect
authorized_next = []
iteration = 2
live_trading_allowed = false
```

Record exact simulation/live submit/cancel counts for any actions actually performed during this iteration, including zero when none were performed.
