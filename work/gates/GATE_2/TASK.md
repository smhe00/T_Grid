# Gate 2 / Current Task

已完成任务：`G2-T001 — Offline Core Position Guard（PASS / Iteration 2）`

唯一规范正文：

```text
work/control/CURRENT_TASK.md
```

Gate 1 已 PASS（commit `20e00c1`）。本任务只实现 immutable Position Snapshot、持仓分解与 Core Floor /
available-volume / reservation 卖出保护；不得实现 Ledger、Reconciliation、OrderIntent 或任何 QMT/交易能力。

Iteration 1 的 Strategic Position 隔离缺陷已在 Iteration 2 修复；正式裁决见
`work/gates/GATE_2/G2-T001_RESULT.md`。
