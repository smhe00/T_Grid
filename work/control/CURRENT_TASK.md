# Current Task — Validate qmt-execution-core 0.2.0

## Owner

`DSH (DeepSeek Harness)` — validation + self-review only. All evidence must remain labelled `SELF_CERTIFIED` until independent architect review.

## Status

`IN_PROGRESS` — TGrid migration is PAUSED. The only authorized task is to validate the standalone execution library at:

```text
D:\gitee\miniQMT\qmt-execution-core
```

against:

```text
repo:    https://github.com/smhe00/qmt-execution-core
commit:  a1500e724bcfed13efbac65d9fbdce2b2513c817
version: 0.2.0
```

The previous TGrid Iteration-10 state-machine audit is superseded as an immediate task because that duplicate execution infrastructure may be replaced by the common core. The historical Gate 5.5 PASS_PRELIVE baseline `e252847` remains regression evidence and is not revoked.

## Validation contract

Read and execute:

```text
work/gates/QMT_EXECUTION_CORE/VALIDATION_REQUEST_20260816.md
```

## Hard prohibitions

```text
NO TGrid migration/refactor
NO qmt-execution-core production-code changes
NO real-money order/cancel
NO QMT simulation order/cancel
NO order_stock/order_stock_async
NO cancel_order_stock/cancel_order_stock_async
NO live trading enablement
```

Real MiniQMT may be used only for safe read-only connection/query smoke testing.

## Required output

```text
work/gates/QMT_EXECUTION_CORE/DSH_VALIDATION_REPORT_20260816.md
```

Report either:

```text
SELF_CERTIFIED PASS
```

or:

```text
CHANGES_REQUIRED
```

with exact defects and evidence. Do not repair findings in this task.

## Required handoff

When validation is complete:

```text
state = REVIEW_READY
owner = architect
authorized_next = [AUDIT_QMT_EXECUTION_CORE_0_2_0]
live_trading_allowed = false
```

Do not start TGrid migration until the architect independently reviews this validation.
