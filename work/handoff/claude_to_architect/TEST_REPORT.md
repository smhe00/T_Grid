# Test Report — G1-T005 / Iteration 2

## Task
G1-T005 — 离线 Gate 1 只读集成探针编排器（Iteration 2 修复 REV-G1T005-001）

## Environment
- Python 3.12.10
- 基线：`81e1abcc6e50bae7629335a2e40633ba3a870bff`
- 全部测试使用 fake client 构造真实 Adapter；无 XtQuant import、无连接、无真实账号/行情访问。

## Commands Run（完整输出见 `work/reports/tests/G1-T005-test-output.txt`，435 行）

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p "test_*.py" -v` | **402 项全部 OK**（396 + 6 本模块新增） |
| `python -m compileall -q src tests` | 退出 0 |
| AST 扫描 `src/tgrid/**/*.py`（19 文件） | PASS：无 assert、无 xtquant import、无 order/cancel/download/subscribe 调用、无动态 getattr/call 绕过 |
| Cleanup-priority probe | ordinary+cleanup-KI/SystemExit/GeneratorExit/ordinary 全固定错误；all-success+cleanup-KI 原样传播 |
| `git diff --check -- :/T_Grid` | exit 0 |
| HEAD 与基线 | `81e1abc...` == base，一致 |

## Iteration 2 新增测试（`TestCleanupBaseExceptionPriority`，6 项，REV-G1T005-001）

| 测试 | 注入 | 断言 |
|---|---|---|
| ordinary_primary_cleanup_keyboard_interrupt | 主 `RuntimeError(PRIMARY_SECRET)` + cleanup `KeyboardInterrupt(CLEANUP_KI_SECRET)` | `"trader.query_asset failed; cleanup failed"`；cause/context None；双方 secret 不泄漏；stop 一次 |
| ordinary_primary_cleanup_system_exit | 主普通异常 + cleanup `SystemExit(9)` | 固定错误；cause/context None；stop 一次 |
| ordinary_primary_cleanup_generator_exit | 主普通异常 + cleanup `GeneratorExit()` | 固定错误；stop 一次 |
| ordinary_primary_cleanup_ordinary_exception | 主 `RuntimeError(PRIMARY_SECRET)` + cleanup `RuntimeError(CLEANUP_SECRET)` | 固定错误；双方 secret 不泄漏；stop 一次 |
| primary_base_exception_cleanup_base_exception_primary_wins | 主 `KeyboardInterrupt` + cleanup `SystemExit(7)` | 主 KI 传播；stop 一次 |
| all_success_cleanup_base_exception_propagates | 全成功 + cleanup `GeneratorExit()` | cleanup GeneratorExit 原样传播；stop 一次 |

## 结果汇总
| 检查项 | 结果 |
|---|---|
| 402 项 unittest | OK |
| compileall | exit 0 |
| AST 安全扫描 | PASS（19 文件） |
| cleanup 优先级（REV-G1T005-001） | PASS（普通主失败下 cleanup 任意异常不覆盖/不泄漏；主 BaseException 优先；全成功+cleanup BaseException 原样传播） |
| stop 至多一次 | PASS |
| 无真实 QMT/账号/行情访问 | 通过（仅 fake client） |

## 结论
REV-G1T005-001 已修复并有笛卡尔回归证据。REVIEW_READY（iteration=2）。
