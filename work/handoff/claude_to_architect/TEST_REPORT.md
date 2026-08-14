# Test Report — G1-T004 / Iteration 2

## Task
G1-T004 — 离线依赖注入的单路 Quote Subscription 只读生命周期边界（Iteration 2 修复 REV-G1T004-001）

## Environment
- Python 3.12.10
- 基线：`6d6d30a831825b65588e4e6a1bbdc54febf14bee`
- 全部测试使用 fake client，无 XtQuant import、无连接、无真实订阅/行情接收。

## Commands Run（完整输出见 `work/reports/tests/G1-T004-test-output.txt`，404 行）

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p "test_*.py" -v` | **371 项全部 OK**（223 Gate 0 + 64 qmt + 38 marketdata + 46 本模块） |
| `python -m compileall -q src tests` | 退出 0 |
| AST 扫描 `src/tgrid/**/*.py`（17 文件） | PASS：无 assert、无 xtquant import、无 order/cancel/download/subscribe 调用、无动态 getattr/call 绕过 |
| Cleanup-eligibility probe | negative/exception/KeyboardInterrupt 均 0 次 unsubscribe；valid seq 0/7 各精确一次 |
| `git diff --check -- :/T_Grid` | exit 0 |
| HEAD 与基线 | `6d6d30a...` == base，一致 |

## Iteration 2 新增/更新测试（REV-G1T004-001）

### 新增 `_unsub_call_count(client)` helper
按方法名统计**所有** `unsubscribe_quote` 调用（不限于 id 42），使 `unsubscribe_quote(None)` 的误调用可被检出。

### 新增 5 项
| 测试 | 断言 |
|---|---|
| sequence_id_zero_passed_exactly_once | seq=0 的 ACTIVE stop → `("unsubscribe_quote", 0)` 一次 |
| sequence_id_positive_passed_exactly_once | seq=7 的 ACTIVE stop → `("unsubscribe_quote", 7)` 一次 |
| stop_after_invalid_return_does_not_unsubscribe | subscribe 返回 -1 后 stop → unsubscribe 调用数 0，状态 FAILED |
| stop_after_subscribe_exception_does_not_unsubscribe | subscribe 抛 RuntimeError 后 stop → unsubscribe 调用数 0 |
| keyboard_interrupt_during_subscribe_no_cleanup | subscribe 抛 KeyboardInterrupt 后 stop → unsubscribe 调用数 0 |

### 更新为统计所有 unsubscribe 调用
`test_stop_is_idempotent`、`test_unsubscribe_exception_safe_and_no_retry`、
`test_failed_after_subscribe_cleanup_once`、`test_keyboard_interrupt_during_stop_propagates_once`、
`test_replaced_stop_uses_frozen_callable` 改用 `_unsub_call_count`。

## 结果汇总
| 检查项 | 结果 |
|---|---|
| 371 项 unittest | OK |
| compileall | exit 0 |
| AST 安全扫描 | PASS（17 文件） |
| 清理资格边界（REV-G1T004-001） | PASS（subscribe 未成功 → 0 次 unsubscribe；有效 id 精确一次） |
| 异常图安全 / 不重试 | PASS |
| 无真实订阅/行情/账号/连接访问 | 通过（仅 fake client） |

## 结论
REV-G1T004-001 已修复并有确定性回归证据。REVIEW_READY（iteration=2）。
