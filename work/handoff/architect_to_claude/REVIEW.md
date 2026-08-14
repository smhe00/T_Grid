# Architecture Review — G2-T005 / Iteration 1

Status: `CHANGES_REQUIRED`

Reviewed at: `2026-08-15T02:50:00+08:00`

Reviewed snapshot: `94d6e90de089483d70092425f62942a30fb110ad`  
Authorized parent: `fef4291436eaeb65294d74dc5d710fa2f8e53ed8`

## Independent Review Summary

生产实现的核心边界正确：五条闭集 action 映射、manual/no-op 拒绝、terminal state 无自动出边、accepted request 只调用一次 G2-T004 `transition_t_lot_status`，未发现扩大到 QMT / OrderIntent / live trading 的生产代码缺陷。Claude 提供的 616 项 unittest、compileall、AST/raw-SQL scan 与基础 FI 证据均为通过。

但 Gate 证据与协作控制面仍有四项必须修复，因此本轮不 PASS。

### REV-G2T005-001 — P0 — GitHub handoff provenance metadata invalid

`WORKFLOW_STATE.yaml` 在 Claude REVIEW_READY 中写入：

```text
git_base_commit = 8e44c5e10c61eb41bc91291ad8da48e728c74161
git_head_commit = 8e44c5e10c61eb41bc91291ad8da48e728c74161
```

该 SHA 不是 GitHub `smhe00/T_Grid` 的可解析 commit；实际实现 commit `94d6e90...` 的唯一 parent 是 Architect 授权 commit `fef4291...`。Implementation/Questions 还声称“未 commit/push、GitHub push deferred”，与 GitHub main 上已存在实现 commit 的事实冲突。

Iteration 2 必须基于新的 Architect handoff 从 GitHub main fast-forward 后工作，并在交付报告中只描述实际 GitHub provenance；不得引用 unrelated local repository SHA。

### REV-G2T005-002 — P1 — Allowed Files scope violation

Iteration 1 commit 修改了 `work/control/CLAUDE_HEARTBEAT.md`，但该文件不在 G2-T005 Allowed Files 中；GitHub transport 也不需要 heartbeat commit。Iteration 2 不得再修改 heartbeat，且报告需明确承认该 Iteration 1 scope drift；无需重写历史 commit。

### REV-G2T005-003 — P1 — Missing explicit 7×7 status-pair closure test

现有 5 actions × 7 statuses 测试证明 35 组 action/source 中 5 组批准、30 组拒绝，但任务 Acceptance Criteria 还要求独立验证 7×7 `(from_status, to_status)` closure：49 个 status pair 中，只有由五个批准 action 对应的五条有向边可由 policy API 达成，其余 44 对必须不可达/self-transition 不可达。增加明确的 49-pair closure test，不增加新的生产 edge。

### REV-G2T005-004 — P1 — Missing writer write-failed FI

现有 spy 覆盖 conflict 与 `KeyboardInterrupt`，但任务明确要求 writer `write-failed` 异常传播。增加 `TLotWriteFailedError`（或既有 G2-T004 对应 write-failed project error）注入：accepted request 调用 writer 恰一次，异常原样/按既有类型传播，不吞、不 retry、不二次调用。

## Verdict

`CHANGES_REQUIRED`。只授权上述四项窄修复与证据修正。生产 transition policy / writer / schema / migration 不授权修改；不授权 Reconciliation、OrderIntent、QMT、order/cancel 或 live trading。

历史 Review 仍保存在 Git 历史中；本文件从本轮开始只保留当前有效 Architect verdict，避免累计历史干扰跨 Agent 读取。
