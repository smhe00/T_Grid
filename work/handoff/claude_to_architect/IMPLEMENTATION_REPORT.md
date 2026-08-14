# Implementation Report

## Task
G0-T004 — 离线 CLI 与 Startup/Shutdown 编排（Iteration 4，响应 CHANGES_REQUIRED）

## Summary
Iteration 4 只修复 `FIX_REQUEST.md` 的 Iteration 4 Active Fix Request：REV-G0T004-006（最外层 cleanup 不是嵌套 finally，logger 仍可泄漏）。

## Iteration 4 Fix

### REV-G0T004-006（P0）— 最外层 cleanup 不是嵌套 finally，logger 仍可泄漏 → FIXED
将 DB close（`_close_db()`）与条件性 `shutdown_complete` emit 包在内层 `try` 中，`shutdown_logger()` 置于对应的最外层 `finally`。任何 `BaseException`（`SystemExit`/`GeneratorExit`）从 `_close_db()` 或 shutdown emit 抛出时，先执行 `finally` 中的 logger shutdown，再原样向外传播，不吞掉、不转换。
- DB close 抛 `SystemExit(9)` → 原样传播，logger shutdown 调用一次，registry 空。
- `shutdown_complete` emit 抛 `GeneratorExit` → 原样传播，logger shutdown 调用一次，registry 空。
- 保持 Iteration 3 的 failure-event KeyboardInterrupt、startup SystemExit/GeneratorExit 修复不变。

## Files Changed（Iteration 4）
- `src/tgrid/main.py` — cleanup 重构为嵌套 try/finally。
- `tests/unit/test_cli.py` — 新增 `TestIteration4Fixes`（2 项）。
- `work/reports/tests/G0-T004-test-output.txt` — 重新生成。

## Design Mapping
不变；最终确立「logger shutdown 为最外层 finally，任何 BaseException 不可跳过」的资源生命周期。

## Deviations
NONE

## Tests Added（Iteration 4）
`TestIteration4Fixes`：DB close SystemExit(9) 仍 shutdown logger、shutdown_complete GeneratorExit 仍 shutdown logger。

## Test Commands
```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
python -m tgrid --help
python -m tgrid --version
```

## Test Results
178 项全部通过（`Ran 178 tests ... OK`）；`compileall` 退出码 0；CLI smoke 退出 0；AST 扫描 `AST_SCAN_OK`。完整输出见 `work/reports/tests/G0-T004-test-output.txt`。

## Failure Injection（累计）
Iteration 1/2/3 的 13 项 + Iteration 4：DB close SystemExit、shutdown_complete GeneratorExit。

全部 fail closed，无 traceback、无伪成功、无敏感泄漏、资源清理完整（含所有 BaseException 路径）。

## Invariant Check
1–7 全部满足；新增：logger shutdown 为最外层 finally，SystemExit/GeneratorExit 传播前仍清理。

## Static / Type / Lint Check
`compileall` 退出码 0；AST 扫描 `src/tgrid/`（12 文件）无 `ast.Assert`、无 `xtquant` import、无 `order_stock`/`cancel_order`。

## Git Diff Summary
未 commit（`git_head_commit` 保持基线 `b8cebc2`）。变更仅限 Allowed Files。未修改权威文档、`CURRENT_TASK.md`、`ARCHITECT_HEARTBEAT.md`、`GATE_0/TASK.md`、`work/design/**`，未触碰父目录。

## Known Issues
NONE

## Questions
NONE

## Recommendation
REVIEW_READY
