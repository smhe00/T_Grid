# Test Report — G2-T004

## Task
G2-T004 — Atomic T-Lot Status Transition Writer。Iteration 2 修复 REV-G2T004-001..003。

## Environment
- 默认 Python 3.12.10；全部测试使用临时 SQLite 文件，无真实 DB / QMT / 账号访问。

## Commands Run（完整输出见 `work/reports/tests/G2-T004-test-output.txt`）

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p "test_*.py" -v` | **597 项全部 OK**（592 基线 + 5 新增） |
| `python -m compileall -q src tests` | 退出 0 |
| AST 扫描 `src/tgrid/**/*.py`（24 文件） | PASS：assert=0 / xtquant import=0 / order-cancel=0 |
| `git diff --check`（本任务文件） | exit 0 |
| 独立 FI 重放（REV-G2T004-001..003） | 全部符合边界 |
| HEAD 与基线 | `3fd560c...` == base |

## 独立 Failure Injection 重放（artifact 内全文）

| 输入 | 结果 |
|---|---|
| KI/SE/GE 注入 audit insert 点 | 传播原对象（`propagated=True`）、`cause/context=None`、rollback（in_txn=False、status=OPEN、audits=0） |
| RuntimeError secret | `TLotWriteFailedError`、`cause/context=None`、`secret_in_msg=False`、status=OPEN、audits=0 |
| COMMIT+ROLLBACK 双失败 | 连接失效（`conn_closed=True`）、主异常转换、无 secret |
| 恶意 status `__eq__` | `TLotWriterInputError`、不调用 dunder、无 secret、audits=0 |
| 两连接确定性 CAS 竞争 | conn1 成功、conn2 `TLotStatusConflictError`、final status=SUSPENDED、audits=1、无 active txn |

## 新增/扩展测试（`tests/unit/test_t_lot_writer.py`，18 项）

### Iteration 2 增量
- `test_base_exception_at_audit_insert_propagates_and_rolls_back`：KI/SE/GE 三类注入 audit insert 点，
  原对象/类型传播，rollback 后 lot/audit/in_transaction 正确，异常图干净。
- `test_runtime_error_secret_converted_and_rolled_back`：非 sqlite RuntimeError secret → 转
  `TLotWriteFailedError`，message/`__cause__`/`__context__` 无 secret，rollback。
- `test_primary_failure_with_rollback_failure_invalidates_connection`：COMMIT+ROLLBACK 均失败 → 连接
  关闭（不可 commit），主异常转换且干净。
- `test_base_exception_primary_with_rollback_failure`：KI 主失败 + ROLLBACK 失败 → KI 传播且连接失效。
- `test_malicious_status_dunder_not_called`：恶意 `__eq__` 不被调用，`TLotWriterInputError`。
- `test_two_connections_deterministic_cas_race`：Event/线程驱动真实争锁，conn1 胜、conn2 conflict、
  一条 audit、无 active txn、无 sleep。

### Iteration 1（保持）
- happy path、validation、duplicate/constraint/commit rollback、active-transaction 拒绝、异常层级、
  writer 模块 AST。

## 结果汇总
| 检查项 | 结果 |
|---|---|
| 597 项 unittest | OK |
| compileall | exit 0 |
| AST 安全扫描 | PASS（24 文件） |
| REV-G2T004-001..003 独立 FI 重放 | 全部符合边界 |
| BaseException/rollback-failure/确定性竞争 | PASS |
| 无真实 QMT/DB/账号访问 | 通过（仅临时文件） |

## 结论
全部检查通过。REVIEW_READY。
