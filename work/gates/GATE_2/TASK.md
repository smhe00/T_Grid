# Gate 2 / Current Task

当前任务：`G2-T006 — Offline Position Reconciliation Decision Engine（CLAUDE_READY / Iteration 1）`

唯一规范正文：

```text
work/control/CURRENT_TASK.md
```

已完成并 PASS：

- G2-T001 — Core Position / T-only sell protection
- G2-T002 — T-Lot ledger schema
- G2-T003 — append-only Audit Log schema
- G2-T004 — atomic status CAS + audit writer
- G2-T005 — closed-set T-Lot business transition policy guard

G2-T006 只实现纯离线 reconciliation decision：比较 Broker Position 与本地预期分解；任何未知差异 fail closed 到 symbol SAFE_MODE，不自动猜测 Strategic/T-Lot/人工交易意图。

不得实现 SQLite reader、QMT、startup orchestration、SAFE_MODE persistence、OrderIntent 或交易。`live_trading_allowed=false`。

本轮授权基线：`e9572d67feab498ce421f8c9220366470c208a61`。
