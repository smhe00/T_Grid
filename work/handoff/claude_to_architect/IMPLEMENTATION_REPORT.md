# Implementation Report — G1-T006 / Iteration 6

## Task
G1-T006 — 真实 MiniQMT 只读验收（Iteration 6 最小离线修复 REV-G1T006-019）

## Summary
删除 runner 复制的 cleanup helper 与公开 probe 注入，将完整生命周期委托给既有固定
`run_gate1_readonly_probe`。**未连接、查询或重跑任何 MiniQMT**。

## Files Changed（Iteration 6 增量）
- `src/tgrid/integrations/qmt_gate1_runtime.py`：
  - `run_gate1_readonly_acceptance` 删除 `probe` 参数；只做单次 config snapshot → runtime 构建 → 调用
    `_default_probe`（既有 `run_gate1_readonly_probe`）→ `_strict_summary` → 返回固定 literals。
  - 删除 runner 内自建 cleanup/异常优先级分支；`_attempt_stop` 仅保留在 `_build_runtime`（构建失败路径）。
- `tests/unit/test_gate1_qmt_runtime.py`：
  - 删除所有 public `probe=` 注入；改为 fake trader/xtdata 直接运行固定 Probe。
  - 新增：`test_runner_public_signature_has_no_probe_param`（inspect.signature）、
    `test_cleanup_runtime_error_is_safe_not_false_pass`、`test_cleanup_keyboard_interrupt_propagates_not_false_pass`、
    `test_fixed_probe_failure_cleans_up_once`、`test_runner_fixed_probe_failure_propagates_safely`；
    `_strict_summary` 恶意 iterable/非 plain bool 测试改为直接调用 `_strict_summary`。
- 证据：`work/reports/tests/G1-T006-test-output.txt` 重新生成（475 项 + 全部扫描）。

## Reuse / 复用说明
- 直接复用既有 `run_gate1_readonly_probe` 的完整生命周期（15 步 + at-most-once cleanup + 普通错误净化 +
  cleanup BaseException 传播，G1-T005 合同）与既有 Adapter 生命周期。
- 未新增平行 QMT helper/runner/生命周期状态机；复用为代码/模式复用，**不是交易执行授权**。

## Tests Added（Iteration 6）
- 固定 Probe 成功路径：底层 stop=1。
- cleanup RuntimeError → 安全失败（无 false PASS）；cleanup KeyboardInterrupt → 原样传播（无 false PASS）。
- 固定 Probe 失败（asset query / calendar 抛错）→ 安全 data-free 错误，secret 零泄漏。
- public runner 无 `probe` 参数（inspect.signature）。

## Test Commands / Results
```text
python -m unittest discover -s tests -p "test_*.py" -v   -> Ran 475 tests ... OK（473 基线 + 2 净增）
python -m compileall -q src tests                         -> exit 0
AST scan src/tgrid（21 文件）                             -> PASS（无 assert/字面 xtquant/order-cancel/subscribe/download）
Sensitive scan (G1-T006 deliverables)                     -> CLEAN
git diff --check -- :/T_Grid                              -> exit 0
```
完整输出：`work/reports/tests/G1-T006-test-output.txt`。

## Failure Injection（Iteration 6）
- probe 注入不可达（无参数）。
- cleanup RuntimeError/KeyboardInterrupt：固定 Probe 合同生效，无 false PASS、无 secret 泄漏。
- 固定 Probe 的 asset/calendar 失败：safe data-free error。

## Invariant Check
1. Gate 1 严格只读；本轮零 QMT 访问：通过。
2. 唯一真实入口只调用固定 Probe，无替换路径：通过。
3. cleanup 全委托固定 Probe（G1-T005 合同），runner 零重复生命周期：通过。
4. strict summary 零未知迭代；输出零敏感数据：通过。
5. 复用既有合同，无新 abstraction；`live_trading_allowed=false`：通过。

## Static / Type / Lint Check
- AST 扫描 21 文件：无 `ast.Assert`、无字面 xtquant import、无 order/cancel/download/subscribe 调用。
- `git diff --check -- :/T_Grid`：exit 0。

## Git Diff Summary
- HEAD == 基线 `237d31292ede492c4552d2e6da7c528df539d844`。
- 变更仅限本任务 Allowed Files；父目录/reverse_repo 未改动；未 commit/push。

## Known Issues
- 模拟客户端不支持 `get_trading_calendar` / `get_trading_period`（环境能力缺口，待架构师裁决）。

## Questions
NONE

## Recommendation
REVIEW_READY（等待架构师离线 Review；最终真实运行需另行授权）。
