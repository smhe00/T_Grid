# Gate 2 / Claude Report — G2-T005

## Status
G2-T005 **T-Lot Business Transition Policy Guard 实现完成**，交付 `REVIEW_READY`，等待架构师 Review。

## 实现内容
- `src/tgrid/persistence/t_lot_transition_policy.py`（新增）：
  - `resolve_t_lot_transition(action, expected_status)`：纯函数，五条批准边闭集 → frozen
    `TLotTransitionPlan`；unknown/wrong-source/self/terminal/manual-noop 全部 fail closed。
  - `apply_t_lot_transition(...)`：先解析策略（拒绝零 DB 写入），再恰好一次调用 G2-T004
    `transition_t_lot_status`；event_type 由 action 固定映射，调用者不得覆盖。
  - `KEEP_SUSPENDED`（no-op，拒绝）、`CONVERT_TO_STRATEGIC` / `MANUAL_EXIT`（需显式人工授权，拒绝）。
- `src/tgrid/persistence/__init__.py`：仅导出本任务批准的 resolver/apply/plan/exceptions。

## 关键行为
- 全 5×7 矩阵：5 批准 + 30 拒绝（含 self-transition 与 terminal outbound）。
- writer spy：reject 0 call / accept 恰 1 call；writer 异常不吞、不重试。
- 恶意 dunder/secret 注入全部隔离；policy 模块无 raw SQL token、无 assert、无 QMT。

## 证据
- `work/reports/tests/G2-T005-test-output.txt`（**616 项全部通过** + compileall exit 0 + AST PASS（25 文件）
  + raw-SQL token=none + 独立 FI 重放全文）。
- 本任务文件 `git diff --check` exit 0。

## 范围遵守
未修改 `t_lot_writer.py`/`migrations.py`/`database.py` 及任何既有测试；未连接 QMT、未访问账号/行情、
未实现 OrderIntent/Reconciliation/人工授权；`live_trading_allowed=false`。

## Git 状态说明
本地 Git 仓库（miniQMT monorepo）与 GitHub `T_Grid` 无共同祖先，无法安全执行协议要求的
ff-only merge / 普通 push。本任务**未 commit/push**；交付物与状态已在本地工作区就绪，GitHub 侧推送
方式由用户/架构师决定。

## Recommendation
REVIEW_READY（等待 Desktop ChatGPT 独立 Review）。
