# Current Task — AUD-R1 Gate 5 Remediation

## Owner

`DSH (DeepSeek Harness)` — single programming Agent, may perform implementation + self-review.

Self-review is useful evidence but must be labelled `SELF_CERTIFIED`; it is not an independent Gate verdict.

## Status

`CHANGES_REQUIRED`

Gate 6 and Gate 7 are blocked. `live_trading_allowed=false` remains mandatory.

## Source of Requirements

Read and execute:

```text
work/gates/GATE_5/INDEPENDENT_AUDIT_20260815.md
```

The independent audit was made against baseline:

```text
2f4957b215beec9f6b6e40054cc6a0375198c29d
```

## Required Work

Fix all Gate-5 remediation findings:

1. deterministic explicit RAW/ADJUSTED market-data acquisition;
2. settlement/T+1-aware total vs sellable position model;
3. correct separation of real broker reconciliation and shadow hypothetical delta;
4. truthful evidence classification (historical real-QMT replay is not wall-clock multi-day live soak);
5. remove `_tmp/` and sanitize local runtime/account/environment details; update ignore rules;
6. restore consistent canonical project state and mark DSH Gate results as `SELF_CERTIFIED`;
7. close or explicitly carry the Gate-4 exact-type coercion hardening item into Gate 5.5; it must be fixed before any real-order invocation.

Do not roll back good Gate 2–4 implementation solely because of the audit.

## Safety / Forbidden During This Task

- no real order submission;
- no real cancel execution;
- no enabling `live_trading`;
- no force push / history rewrite;
- no silent deletion of audit evidence needed to understand prior behavior;
- no committing account identifiers, cash/position details, userdata paths, ports/endpoints, local config, secrets or logs.

## Required Evidence

- full unit regression;
- `python -m compileall -q src tests`;
- AST/capability scan showing no unexpected real order/cancel capability;
- focused tests for price-basis binding, settlement sellability and reconciliation semantics;
- refreshed Gate-5 evidence after the fixes:
  - zero-real-position case;
  - non-zero real/Core-position case;
  - settlement-policy behavior;
  - explicit RAW/ADJUSTED basis behavior;
- sanitized committed reports only.

## Stop / Handoff Condition — AUDIT NODE A

When remediation is complete:

1. push normally to GitHub `main`;
2. update `WORKFLOW_STATE.yaml` to an unambiguous `AUDIT_READY` state;
3. record exact baseline/head, tests, evidence and open risks;
4. stop before implementing Gate 5.5 or any real order/cancel adapter.

ChatGPT will perform the next independent audit at this point.

A second mandatory audit (`AUDIT NODE B`) is required later after Gate-5.5 real broker capability is implemented but **before the first real order invocation**. Gate 6 remains blocked until Node B independent PASS + explicit user authorization.
