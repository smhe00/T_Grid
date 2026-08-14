# Test Report — G1-T003 / Iteration 2

## Task
G1-T003 — 离线依赖注入的 MarketData 查询只读 Adapter 边界（Iteration 2 修复 REV-G1T003-001）

## Environment
- Python 3.12.10
- 基线：`a2f5fa3cb826e14a89bc478492f900d93d25b9fa`
- 全部测试使用 fake client，无 XtQuant import、无订阅/下载/连接、无真实行情/账号访问。

## Commands Run（完整输出见 `work/reports/tests/G1-T003-test-output.txt`，357 行）

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p "test_*.py" -v` | **325 项全部 OK**（223 Gate 0 + 64 qmt_readonly + 38 本模块） |
| `python -m compileall -q src tests` | 退出 0 |
| AST 扫描 `src/tgrid/**/*.py`（16 文件） | PASS：无 assert、无 xtquant import、无 order/cancel/subscribe/download 调用、无动态 getattr/call 绕过 |
| 单次快照 probe | len_bomb 不受影响；first-pass/secret 异常图干净且底层 0；changing 仅 1 pass |
| `git diff --check -- :/T_Grid` | exit 0 |
| HEAD 与基线 | `a2f5fa3...` == base，一致 |

## Iteration 2 新增测试（`TestSingleSnapshotSequence`，5 项，REV-G1T003-001）

| 测试 | 注入 | 断言 |
|---|---|---|
| len_bomb_is_unaffected | `LenBombSequence`（`__len__` 抛 `LEN_SECRET_7A`） | 单次物化不触发 `__len__`；底层收到 `['600000.SH']`，无 secret |
| first_pass_iterator_bomb | iterator 首个 `next()` 抛 `FIRST_PASS_SECRET_9B` | `MarketDataValidationError`；cause/context None；底层调用 0 |
| changing_sequence_uses_first_snapshot_only | 第一次返回 `['600000.SH']`、第二次返回 `['']` | 仅 1 次 pass；底层收到已验证的 `['600000.SH']`，不含 `['']` |
| secret_iterator_exception_not_leaked | iterator 抛 `ITERATOR_SECRET_XYZ` | cause/context None；stdout/stderr 无 secret；底层调用 0 |
| market_data_snapshot_shared | changing sequence 作 stock_list | 仅 1 次 pass；底层收到已验证 snapshot |

## 结果汇总
| 检查项 | 结果 |
|---|---|
| 325 项 unittest | OK |
| compileall | exit 0 |
| AST 安全扫描 | PASS（16 文件） |
| 单次快照（REV-G1T003-001） | PASS（len bomb 免疫、first-pass/secret 干净、changing 只观察一次、底层只收已验证值） |
| 无真实行情/账号/连接访问 | 通过（仅 fake client） |

## 结论
REV-G1T003-001 已修复并有确定性回归证据。REVIEW_READY（iteration=2）。
