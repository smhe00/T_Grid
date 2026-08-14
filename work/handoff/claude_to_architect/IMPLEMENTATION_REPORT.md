# Implementation Report

## Task
G0-T003 — 结构化 JSONL Logging 基础（Iteration 3，响应 CHANGES_REQUIRED）

## Summary
Iteration 3 只修复 `FIX_REQUEST.md` 的 Iteration 3 Active Fix Request 两项并发生命周期问题：REV-G0T003-006（emit/shutdown 竞态）与 REV-G0T003-007（同名 logger 并发配置）。

## Iteration 3 Fixes（逐 Issue 回复）

### REV-G0T003-006（P0）— emit 与 shutdown 竞态可重开文件并写入 → FIXED
引入 per-logger 可重入锁 `_get_logger_lock(name)`（`_logger_locks` dict + guard）。`emit()` 在「`_resolve_configured_handler` + `_validate_and_dump` + `handler.handle`」整段持有该锁；`shutdown_logger()` 与 `configure_jsonl_logger()` 的 drop/close 也在同一把锁内执行。因此：
- emit 先开始时，shutdown 会阻塞等待该 emit 完整结束，再 close 并返回。
- shutdown 先完成时，后续 emit 的 `_resolve_configured_handler` 发现 registry 已空，抛 `LoggingEmitError`，绝不重开文件。
- 无 sleep，全部用 RLock 确定排序。

### REV-G0T003-007（P1）— 同名 logger 并发配置产生多个 handler → FIXED
`configure_jsonl_logger()` 的整个状态转换（open → drop → add → register）在同一把 per-logger 锁内串行。任意并发配置同一名称后，logger 恰好挂一个 TGrid-owned handler，且 registry 指向同一对象；被替换/失败的 handler 均关闭。

## Files Changed（Iteration 3）
- `src/tgrid/reporting/logging.py` — 新增 per-logger 锁与三个生命周期函数加锁。
- `tests/unit/test_logging.py` — 新增 `TestLifecycleConcurrency`（3 项确定性交错测试）。
- `work/reports/tests/G0-T003-test-output.txt` — 重新生成。

## Design Mapping
不变；强化日志生命周期契约与并发安全（协议 §22 原子/健壮控制、§34 INV-010 fail-closed）。

## Deviations
NONE

## Tests Added（Iteration 3）
- `TestLifecycleConcurrency.test_emit_shutdown_race_shutdown_waits_for_emit`（Event 控制交错：shutdown 等待 in-flight emit，旧路径不重建）。
- `TestLifecycleConcurrency.test_emit_after_shutdown_does_not_reopen_file`。
- `TestLifecycleConcurrency.test_concurrent_configure_same_name_single_handler`（4 线程并发配置同名，最终单 handler、registry 一致、可 shutdown）。

## Test Commands
```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
```

## Test Results
142 项全部通过（`Ran 142 tests ... OK`）；`compileall` 退出码 0。完整输出见 `work/reports/tests/G0-T003-test-output.txt`。

## Failure Injection（累计）
Iteration 1 的 7 项 + Iteration 2 的 5 项 + Iteration 3：emit/shutdown 确定性交错、并发同名配置。

全部 fail closed，无静默丢日志、无 handler 泄漏、无半行 JSON。

## Invariant Check
1–7 全部满足；新增：per-logger 原子顺序（emit vs shutdown vs configure）、并发配置单 handler。

## Static / Type / Lint Check
`compileall` 退出码 0；AST 扫描 `src/tgrid/`（10 文件）无 `ast.Assert`、无 `xtquant` import、无 `order_stock`/`cancel_order`。

## Git Diff Summary
未 commit（`git_head_commit` 保持基线 `e91b327`）。变更仅限 Allowed Files。未修改权威文档、`CURRENT_TASK.md`、`ARCHITECT_HEARTBEAT.md`、`GATE_0/TASK.md`、`work/design/**`，未触碰父目录。

## Known Issues
NONE

## Questions
NONE

## Recommendation
REVIEW_READY
