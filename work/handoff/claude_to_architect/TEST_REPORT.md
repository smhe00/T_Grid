# Test Report — G2-T005

## Task
G2-T005 — T-Lot Business Transition Policy Guard（闭集 action → 唯一状态边，复用 G2-T004 writer）。

## Environment
- 默认 Python 3.12.10；全部测试使用临时 SQLite 文件，无真实 DB / QMT / 账号访问。

## Commands Run（完整输出见 `work/reports/tests/G2-T005-test-output.txt`）

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p "test_*.py" -v` | **616 项全部 OK**（597 基线 + 19 新增） |
| `python -m compileall -q src tests` | 退出 0 |
| AST 扫描 `src/tgrid/**/*.py`（25 文件） | PASS：assert=0 / xtquant=0 / order-cancel=0 |
| policy 模块 raw-SQL token 扫描 | none（BEGIN/UPDATE/INSERT INTO/DELETE FROM/COMMIT/ROLLBACK） |
| `git diff --check`（本任务文件） | exit 0 |
| 独立 policy FI 重放 | 全部符合边界 |

## 独立 Failure Injection 重放（artifact 内全文）

| 输入 | 结果 |
|---|---|
| 五条批准边 resolver | 5/5 正确 |
| 全 action×status 矩阵（35 组合） | 5 批准 + **30 拒绝**，self-transition 全拒绝 |
| KEEP_SUSPENDED / CONVERT_TO_STRATEGIC / MANUAL_EXIT | 全部 rejected，DB 不变（SUSPENDED、audits=0） |
| 恶意 `__eq__` 注入 | 不调用 dunder，cause/context None，无 secret |
| writer spy | reject 0 call；success 恰 1 call |
| stale source | 底层 `TLotStatusConflictError`，无 retry，status=PENDING_SELL、audits=1 |
| terminal source（CLOSED/CONVERTED_TO_STRATEGIC/ERROR） | 全部 rejected |

## 新增测试覆盖（`tests/unit/test_t_lot_transition_policy.py`，19 项）

### resolver（纯函数）
- 五条批准边 → frozen plan，event_type 固定映射；全矩阵负向；self-transition；unknown action；
  manual/no-op 三动作；terminal source；wrong source；空/NULL/非 exact-str/str subclass/bool/bytes/
  container 拒绝；恶意 action/status `__eq__` 不被调用，异常图干净。

### apply（SQLite 集成）
- 五条批准边逐条 apply → DB status 与 audit（event_type/from/to）完全一致。
- 拒绝边零 DB 写入（lot/history 逐值不变、0 audit）；manual/no-op apply → DB 不变。
- stale source 走底层 CAS conflict，值不变。

### writer spy / 异常
- reject → writer 0 call；success → writer 恰 1 call 且参数为 plan 推导值。
- writer conflict / BaseException 不吞、不重试、恰好一次。

### AST / 范围
- 新模块无 raw SQL token、无 `assert`、无 xtquant、无 order/cancel；现有回归（597）保持通过。

## 结果汇总
| 检查项 | 结果 |
|---|---|
| 616 项 unittest | OK |
| compileall | exit 0 |
| AST 安全扫描 + raw-SQL 扫描 | PASS / none |
| 独立 FI 重放 | 全部符合边界 |
| 无真实 QMT/DB/账号访问 | 通过（仅临时文件） |

## 结论
全部检查通过。REVIEW_READY。
