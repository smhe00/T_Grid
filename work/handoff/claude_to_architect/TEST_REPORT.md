# Test Report — G2-T005 / Iteration 2

## Task
G2-T005 — T-Lot Business Transition Policy Guard。Iteration 2 修 REV-G2T005-001..004。

## Environment
- 默认 Python 3.12.10；全部测试使用临时 SQLite 文件，无真实 DB / QMT / 账号访问。

## Commands Run（完整输出见 `work/reports/tests/G2-T005-test-output.txt`）

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p "test_*.py" -v` | **618 项全部 OK**（616 基线 + 2 新增） |
| `python -m compileall -q src tests` | 退出 0 |
| AST 扫描 `src/tgrid/**/*.py`（25 文件） | PASS：assert=0 / xtquant=0 / order-cancel=0 |
| policy 模块 raw-SQL token 扫描 | none |
| `git diff --check`（本任务文件） | exit 0 |

## Iteration 2 新增测试

### REV-G2T005-002 — 7×7 status-pair closure
`test_49_status_pair_closure`：遍历 5 action × 7 status，可达 (from,to) 边集合精确等于 5 条批准边：
`PENDING_BUY→OPEN`、`OPEN→PENDING_SELL`、`PENDING_SELL→CLOSED`、`OPEN→SUSPENDED`、`SUSPENDED→OPEN`。
49 对中可达数=5，其余 44 对不可达，7 个 self-transition 不可达。

### REV-G2T005-003 — writer write-failed FI
`test_writer_write_failed_not_swallowed_not_retried`：patch writer 抛 `TLotWriteFailedError`，断言
writer 恰好 1 call、异常不被吞、不 retry、不二次调用、调用参数映射（BUY_FILL_CONFIRMED → OPEN /
event_type=BUY_FILL_CONFIRMED）不变。

## Iteration 1（保持）
- 五条批准边 resolver/apply；全 action×status 矩阵；self-transition；unknown action；manual/no-op 三动作；
  terminal source；wrong source；空/NULL/非 exact-str/str subclass/bool/bytes/container；恶意 `__eq__`；
  SQLite 集成（批准边 DB/audit 一致、拒绝零写入、stale conflict）；writer spy（reject 0 / accept 1、
  conflict/BaseException 传播）；AST/raw-SQL 无。

## 结果汇总
| 检查项 | 结果 |
|---|---|
| 618 项 unittest | OK |
| compileall | exit 0 |
| AST 安全扫描 + raw-SQL | PASS / none |
| 49-pair closure | 仅 5 条批准边可达，44 对与 self 不可达 |
| write-failed FI | 1 call、不吞、不 retry、映射不变 |
| 无真实 QMT/DB/账号访问 | 通过（仅临时文件） |

## 结论
全部检查通过。REVIEW_READY。
