# Implementation Report — G1-T004 / Iteration 2

## Task
G1-T004 — 离线依赖注入的单路 Quote Subscription 只读生命周期边界（Iteration 2 修复 REV-G1T004-001）

## Summary
只修复 subscribe 未成功时错误调用 `unsubscribe_quote(None)` 的清理资格边界：cleanup 资格由“已验证并
保存有效 sequence id”这一事实决定，不能仅由 FAILED 状态推断。保持现有 API 和单路状态机不变，
不新增能力。

## Files Changed（Iteration 2 增量）
- `src/tgrid/adapters/quote_subscription_readonly.py`：
  - `stop()` 在状态检查后、调用底层前新增判定：若 `self._sequence_id is None` 则直接 return（不标记
    `_stop_attempted`），并在持有有效 id 时用局部变量 `seq` 调用 `unsubscribe_quote(seq)`。
  - 因此 subscribe 从未成功（普通异常 / BaseException / 负数 / 错误类型返回）后，`stop()` 绝不调用
    `unsubscribe_quote`；有效 id（含 0）的 ACTIVE stop 仍精确传一次。
- `tests/unit/test_quote_subscription_readonly.py`：
  - 新增 `_unsub_call_count(client)` helper：按方法名统计所有 unsubscribe 调用，不限于 id 42。
  - 更新 `test_stop_is_idempotent`、`test_unsubscribe_exception_safe_and_no_retry`、
    `test_failed_after_subscribe_cleanup_once`、`test_keyboard_interrupt_during_stop_propagates_once`、
    `test_replaced_stop_uses_frozen_callable` 改用 helper。
  - 新增 5 项：`test_sequence_id_zero_passed_exactly_once`、`test_sequence_id_positive_passed_exactly_once`、
    `test_stop_after_invalid_return_does_not_unsubscribe`、`test_stop_after_subscribe_exception_does_not_unsubscribe`、
    `test_keyboard_interrupt_during_subscribe_no_cleanup`。

## Deviations
NONE

## Tests Added（Iteration 2）
见 Files Changed；新增 5 项，全模块 46 项；全量 371 项通过。

## Test Commands / Results
```text
python -m unittest discover -s tests -p "test_*.py" -v   -> Ran 371 tests ... OK（含 5 项新增）
python -m compileall -q src tests                         -> exit 0
AST scan src/tgrid（17 文件）                             -> PASS
Cleanup-eligibility probe                                 -> negative/exception/KI 均 0 次 unsubscribe；valid seq 0/7 各精确一次
git diff --check -- :/T_Grid                              -> exit 0
```
完整输出：`work/reports/tests/G1-T004-test-output.txt`（404 行）。

## Failure Injection（Iteration 2）
- subscribe 返回 -1 / 抛普通异常 / 抛 KeyboardInterrupt 后调用 stop：断言 unsubscribe 调用数为 0，
  状态 FAILED，sequence_id None。
- 有效 sequence id 0 与正整数：ACTIVE stop 把精确 id 传入一次。

## Invariant Check
1. Gate 1 严格只读，离线 transport boundary：通过。
2. 两个底层调用固定、显式、可审计，无动态逃逸口：通过。
3. `live_trading_allowed=false`：通过。
4. 外部普通异常完整异常图不携带敏感信息；BaseException 不被吞掉：通过。
5. Lifecycle Contract 5（subscribe 从未成功则不调用 unsubscribe）：通过（迭代 2 修复）。

## Static / Type / Lint Check
- AST 扫描 17 文件：无 `ast.Assert`、无 `xtquant` import、无 order/cancel/download/subscribe 调用、
  无动态 getattr/call 绕过。
- `git diff --check -- :/T_Grid`：exit 0。

## Git Diff Summary
- HEAD == 基线 `6d6d30a831825b65588e4e6a1bbdc54febf14bee`。
- 变更仅限本任务 Allowed Files；父目录文件未改动；未 commit/push。

## Known Issues
NONE

## Questions
NONE

## Recommendation
REVIEW_READY（iteration=2）
