# Gate 2 / Current Task

当前任务：`G2-T002 — Transactional T-Lot Ledger Schema（CHANGES_REQUIRED / Iteration 2）`

唯一规范正文：

```text
work/control/CURRENT_TASK.md
```

G2-T001 已 PASS（commit `7270485`）。本任务只新增 SQLite migration 2、t_lots schema、禁止删除 trigger
与启动完整性验证；不得实现 Ledger CRUD、Audit Log、Reconciliation、OrderIntent 或任何 QMT/交易能力。

Iteration 1 的 SQLite type/null/probe-collision/PnL 语义注入失败。Iteration 2 只修
`REV-G2T002-001..005`，详见 `work/handoff/architect_to_claude/FIX_REQUEST.md`。
