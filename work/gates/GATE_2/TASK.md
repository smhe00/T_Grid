# Gate 2 / Current Task

当前任务：`G2-T005 — T-Lot Business Transition Policy Guard（CLAUDE_READY / Iteration 1）`

唯一规范正文：

```text
work/control/CURRENT_TASK.md
```

已完成并 PASS：G2-T001 Core Position、G2-T002 T-Lot schema、G2-T003 append-only Audit Log、
G2-T004 atomic status CAS + audit writer。

G2-T005 只在 G2-T004 之上增加闭集 business transition policy/guard：五条批准 lifecycle edge，
其余 fail closed。不得实现 QMT、OrderIntent、Reconciliation、真实人工交易授权或 live trading。

本轮授权基线：`439bbd96bece598f1aed7471db72c6267ee257a7`。
