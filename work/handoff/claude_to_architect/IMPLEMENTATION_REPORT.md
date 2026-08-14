# Implementation Report — G2-T005 / Iteration 2

## Task
G2-T005 — T-Lot Business Transition Policy Guard。Iteration 2 只修 REV-G2T005-001..004，不扩大功能面。

## Summary
Iteration 1 已实现闭集策略层并推送 GitHub main（`94d6e90`）。架构师 Review 提出四点（REV-G2T005-001..004），
Iteration 2 完成：
- 新增显式 7×7 status-pair closure 测试（49 对：仅 5 条批准 directed edge 可达，44 对与全部
  self-transition 不可达）。
- 新增 writer write-failed FI：patch G2-T004 writer 抛既有 `TLotWriteFailedError`，断言恰好 1 call、
  不吞异常、不 retry、不二次调用、action→status/event_type 映射不变。
- 报告与 WORKFLOW_STATE 的 Git provenance 改为真实 GitHub main SHA（`6a7fa4c3...`），不再写
  "GitHub push deferred"。
- 未修改 `CLAUDE_HEARTBEAT.md`；Iteration 1 对该文件的修改作为已识别 scope drift 记录，不重写历史。

## Fix Request 逐项

### REV-G2T005-001 — GitHub provenance / reports — **FIXED**
- 交付的 `WORKFLOW_STATE.yaml` Git provenance 来自 `smhe00/T_Grid` 当前 GitHub main
  （`git_base_commit = git_head_commit = 6a7fa4c3d8c541754803a24205b224020b7b1a63`），不再使用无共同祖先的
  本地 monorepo SHA。
- 本报告如实描述：Iteration 1 已提交并 push 到 GitHub main（`94d6e90`）；Iteration 2 修改将再次 commit
  并 push 到 GitHub main（fast-forward from `6a7fa4c`）。不再写 "GitHub push deferred"。
- 未修改 `CLAUDE_HEARTBEAT.md`。Iteration 1 对它的修改（随 `94d6e90` 推送）记录为已识别 scope drift，
  保留历史，不重写。

### REV-G2T005-002 — 7×7 status-pair closure 测试 — **FIXED**
- `test_49_status_pair_closure`：遍历 5 action × 7 status，收集全部可达 (from_status, to_status) 边，
  断言恰好等于五条批准边集合：
  `PENDING_BUY→OPEN`、`OPEN→PENDING_SELL`、`PENDING_SELL→CLOSED`、`OPEN→SUSPENDED`、`SUSPENDED→OPEN`。
- 断言 49 对中可达数 = 5、其余 44 对不可达、7 个 self-transition 全部不可达。
- 仅验证 closure，未新增/改变生产 edge。

### REV-G2T005-003 — writer write-failed FI — **FIXED**
- `test_writer_write_failed_not_swallowed_not_retried`：patch writer 抛 `TLotWriteFailedError`，
  断言 writer 恰好 1 call、异常不被吞、不 retry、不二次调用，且调用参数保持 action→status/event_type
  映射（`BUY_FILL_CONFIRMED → new_status=OPEN / event_type=BUY_FILL_CONFIRMED`）不变。

### REV-G2T005-004 — Re-run evidence — **FIXED**
- 完整 unittest、compileall、AST forbidden/raw-SQL、`git diff --check`、Allowed Files diff-check 全部通过，
  完整输出见 `work/reports/tests/G2-T005-test-output.txt`。

## Files Changed（Iteration 2，均在 Allowed Files 内）
- `tests/unit/test_t_lot_transition_policy.py`：+2 项（49-pair closure、writer write-failed FI）。
- `work/reports/tests/G2-T005-test-output.txt`：重新生成（**618 项全部通过** + compileall + AST + raw-SQL）。
- `work/gates/GATE_2/CLAUDE_REPORT.md`、`work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md`、
  `work/handoff/claude_to_architect/TEST_REPORT.md`、`work/handoff/claude_to_architect/QUESTIONS.md`：Iteration 2。
- `work/control/WORKFLOW_STATE.yaml`：REVIEW_READY / iteration 2 / handoff_seq=5 / 新 handoff_id /
  authorized_next=[] / GitHub provenance。

未修改 `CLAUDE_HEARTBEAT.md` 及任何生产代码（`t_lot_transition_policy.py`/`__init__.py` 与 Iteration 1 一致）。

## Reuse Evidence
- `apply_t_lot_transition` 继续直接调用 G2-T004 `transition_t_lot_status`；Iteration 2 未复制 SQL/CAS/rollback，
  未新增抽象。异常仍继承 `TLotWriterError` → `PersistenceError` 层。

## Test Commands / Results
```text
python -m unittest discover -s tests -p "test_*.py" -v   -> Ran 618 tests ... OK（616 基线 + 2 新增）
python -m compileall -q src tests                         -> exit 0
AST scan src/tgrid（25 文件）                             -> PASS，forbidden=0
policy 模块 raw-SQL token 扫描                            -> none
git diff --check（本任务文件）                            -> exit 0
```
完整输出：`work/reports/tests/G2-T005-test-output.txt`。

## Failure Injection
- 49-pair closure：可达边精确等于 5 条批准边，44 对与 self-transition 不可达。
- writer write-failed：`TLotWriteFailedError` 传播、1 call、不 retry、映射不变。
- 既有 Iteration 1 FI（矩阵、manual/no-op、dunder/secret、stale conflict、writer spy 0/1）保持通过。

## Git Diff Summary
- Iteration 1：已 push GitHub main `94d6e90`。
- Iteration 2：基于 GitHub main `6a7fa4c` fast-forward 提交并 push（完成后 GitHub main 指向新提交，
  父为 `6a7fa4c`）。仅含 Iteration 2 Allowed Files。

## Known Issues
NONE

## Questions
NONE

## Recommendation
REVIEW_READY
