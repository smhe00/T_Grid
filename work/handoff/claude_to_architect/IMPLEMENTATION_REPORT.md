# Implementation Report — G1-T005 / Iteration 2

## Task
G1-T005 — 离线 Gate 1 只读集成探针编排器（Iteration 2 修复 REV-G1T005-001）

## Summary
只修复普通主操作失败叠加 cleanup BaseException 时主错误被覆盖与 cleanup secret 泄漏的问题：
`_cleanup()` 改为永不传播、把任意 cleanup 异常作为返回值，由调用方按优先级决定；保持固定 15 步与
现有 API 不变。

## Files Changed（Iteration 2 增量）
- `src/tgrid/probes/gate1_readonly.py`：
  - `_cleanup()` 改为 `-> Optional[BaseException]`：`trader.stop()` 成功返回 None；任何异常（普通或
    BaseException）**捕获后作为返回值返回，绝不传播**。
  - 普通主失败分支：`cleanup_exc = _cleanup()`；随后 except 块外若 `cleanup_exc is not None` 抛
    `Gate1ProbeExecutionError("<op> failed; cleanup failed")`，否则 `"<op> failed"`。
  - 主 BaseException 分支：`_cleanup()`（吞掉任何 cleanup 异常）后 `raise` 原样传播主 BaseException。
  - 全部主成功路径：`cleanup_exc` 若为 BaseException 则 `raise cleanup_exc` 原样传播（仅无主失败时）；
    普通异常抛 `"cleanup failed"`。
- `tests/unit/test_gate1_readonly_probe.py`：新增 `TestCleanupBaseExceptionPriority`（6 项，31 项总计）。

## Deviations
NONE

## Tests Added（Iteration 2）
`TestCleanupBaseExceptionPriority`（REV-G1T005-001）：
1. `test_ordinary_primary_cleanup_keyboard_interrupt`：主 RuntimeError + cleanup KI → 固定错误，双方
   secret 均不出现，stop 一次。
2. `test_ordinary_primary_cleanup_system_exit`：cleanup SystemExit(9) → 固定错误，cause/context None。
3. `test_ordinary_primary_cleanup_generator_exit`：cleanup GeneratorExit → 固定错误。
4. `test_ordinary_primary_cleanup_ordinary_exception`：cleanup 普通异常 → 固定错误，双方 secret 不出现。
5. `test_primary_base_exception_cleanup_base_exception_primary_wins`：主 KI + cleanup SystemExit →
   主 KI 传播，stop 一次。
6. `test_all_success_cleanup_base_exception_propagates`：全成功 + cleanup GeneratorExit → 原样传播。

原有 25 项保持通过；全量 402 项通过。

## Test Commands / Results
```text
python -m unittest discover -s tests -p "test_*.py" -v   -> Ran 402 tests ... OK（含 6 项新增）
python -m compileall -q src tests                         -> exit 0
AST scan src/tgrid（19 文件）                             -> PASS
Cleanup-priority probe                                    -> ordinary+cleanup-KI/SystemExit/GeneratorExit/ordinary 全固定错误；all-success+KI 传播
git diff --check -- :/T_Grid                              -> exit 0
```
完整输出：`work/reports/tests/G1-T005-test-output.txt`（435 行）。

## Failure Injection（Iteration 2）
- 普通主失败（query_asset RuntimeError）+ cleanup 抛 KI/SystemExit/GeneratorExit/普通异常：全部折叠为
  固定 `"<op> failed; cleanup failed"`，cause/context None，主/cleanup secret 均不泄漏。
- 主 KI + cleanup SystemExit：主 KI 优先。
- 全成功 + cleanup KI：cleanup BaseException 原样传播。

## Invariant Check
1. Gate 1 严格只读，离线 transport boundary：通过。
2. 只调用两个批准 Adapter 的固定公共只读方法，无动态逃逸口：通过。
3. `live_trading_allowed=false`：通过。
4. 外部普通异常完整异常图不携带敏感信息；BaseException 不被吞掉：通过（优先级正确）。
5. Failure Contract 3/5（普通主失败下 cleanup 不得覆盖/泄漏）：通过（迭代 2 修复）。

## Static / Type / Lint Check
- AST 扫描 19 文件：无 `ast.Assert`、无 `xtquant` import、无 order/cancel/download/subscribe 调用、
  无动态 getattr/call 绕过。
- `git diff --check -- :/T_Grid`：exit 0。

## Git Diff Summary
- HEAD == 基线 `81e1abcc6e50bae7629335a2e40633ba3a870bff`。
- 变更仅限本任务 Allowed Files；父目录文件未改动；未 commit/push。

## Known Issues
NONE

## Questions
NONE

## Recommendation
REVIEW_READY（iteration=2）
