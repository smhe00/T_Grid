# Implementation Report

## Task
G0-T005 — 单一 Event Queue 骨架（Iteration 4，响应 CHANGES_REQUIRED）

## Summary
Iteration 4 只修复 `FIX_REQUEST.md` 的 Iteration 4 Active Fix Request：REV-G0T005-005（join 缓存未启动 worker）与 REV-G0T005-006（测试遗留 daemon 控制线程）。

## Iteration 4 Fixes（逐 Issue 回复）

### REV-G0T005-005（P0）— join 缓存未启动 worker，start failure 后仍调用 Thread.join → FIXED
`join()` 重构：等待 `_starting` handshake 结束后，在**同一 lock 内重新读取 `_worker`**，再决定是否 join。
- start 失败路径清空 `_worker` 后，并发 join 醒来重新读取为 `None` → 安全返回 `True`（无实际 OS 线程），绝不调用 `Thread.join()` 于未启动线程，不泄漏 `RuntimeError: cannot join thread before it is started`。
- FAILED 状态由 `state`/`failure_type`/`raise_if_failed()` 表达。
- 新增确定性测试：`test_concurrent_join_after_start_failure_returns_true`（start 暂停→fail + 并发 join，start 抛安全项目异常、join 返回 True 无异常、FAILED/failure_type 正确、唯一 secret 不出现）与 `test_stop_and_start_failure_interleaved_no_deadlock`（stop+start failure+join 交错，无死锁、无虚假 RUNNING、无活线程、无未处理线程异常）。

### REV-G0T005-006（P1）— 测试遗留永不结束的 daemon 控制线程 → FIXED
删除不可清理的 `test_bounded_join_returns_false_when_start_never_completes`（无限循环 daemon controller），替换为 `test_bounded_join_returns_false_while_start_paused_then_recovers`：用可释放 Event 暂停 start，验证 bounded join 返回 False，再 `stop()` + `release` + join 所有控制/worker 线程；测试结束断言 controller 与目标 thread_name 均无存活线程。

## Files Changed（Iteration 4）
- `src/tgrid/events.py` — `join()` 在 handshake 后锁内重读 `_worker`。
- `tests/unit/test_events.py` — 新增 `TestIteration4Fixes`（2 项）；重写泄露测试。
- `work/reports/tests/G0-T005-test-output.txt` — 重新生成。

## Design Mapping
不变；完善 start/join handshake 竞态与测试可清理性（协议 §22 原子/健壮、§34 fail-closed）。

## Deviations
NONE

## Tests Added（Iteration 4）
- `TestIteration4Fixes.test_concurrent_join_after_start_failure_returns_true`
- `TestIteration4Fixes.test_stop_and_start_failure_interleaved_no_deadlock`
- 重写 `TestIteration3Fixes.test_bounded_join_returns_false_while_start_paused_then_recovers`

## Test Commands
```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
```

## Test Results
223 项全部通过（`Ran 223 tests ... OK`；221 项迭代3回归 + 新增 2 项）；`compileall` 退出码 0。完整输出见 `work/reports/tests/G0-T005-test-output.txt`（无未处理线程异常）。

## Failure Injection（累计）
Iteration 1/2/3 的 12 类 + Iteration 4：start failure + 并发 join、stop + start failure + join 交错、start 暂停可恢复 bounded join。

全部 fail closed，无裸 threading 异常、无 secret、无死锁、无活线程泄漏。

## Invariant Check
1–9 全部满足；新增：join 在 handshake 后锁内重读 worker、start failure 后 join 安全返回 True、测试无遗留线程。

## Static / Type / Lint Check
`compileall` 退出码 0；AST 扫描 `src/tgrid/` 无 `ast.Assert`、无 `xtquant` import、无 `order_stock`/`cancel_order`。

## Git Diff Summary
未 commit（`git_head_commit` 保持基线 `f59801e`）。变更仅限 Allowed Files。未修改权威文档、`CURRENT_TASK.md`、`ARCHITECT_HEARTBEAT.md`、`GATE_0/TASK.md`、`work/design/**`，未触碰父目录。

## Known Issues
NONE

## Questions
NONE

## Recommendation
REVIEW_READY
