# Test Report — G2-T003

## Task
G2-T003 — Append-Only T-Lot Audit Log Schema（migration v3 + 行为式 verifier）。Iteration 2 修复
REV-G2T003-001..002。

## Environment
- 默认 Python 3.12.10；全部测试使用临时 SQLite 文件，无真实 DB / QMT / 账号访问。

## Commands Run（完整输出见 `work/reports/tests/G2-T003-test-output.txt`）

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p "test_*.py" -v` | **579 项全部 OK**（578 基线 + 1 新增） |
| `python -m compileall -q src tests` | 退出 0 |
| AST 扫描 `src/tgrid/**/*.py`（23 文件） | PASS：assert=0 / xtquant import=0 / order-cancel=0 |
| `git diff --check`（本任务文件） | exit 0 |
| 独立 FI 重放（REV-G2T003-001） | 全部符合边界 |
| HEAD 与基线 | `aa13ef9...` == base |

## 独立 Failure Injection 重放（REV-G2T003-001，artifact 内全文）

| 输入 | 结果 |
|---|---|
| 健康 v3 DB 预置 id=`__tgrid_probe_no_such_lot` 的合法 T-Lot + audit 行后 initialize | **通过**；t_lots/audit 全行、history、user_version 逐值不变（`initialize_OK True`） |
| 缺外键伪造 schema 预置同一冲突 id | **REJECTED（SchemaVersionError）**（真正 dangling probe 被接受，非 PK 冲突假通过） |

## 新增/扩展测试（`tests/unit/test_t_lot_audit_schema.py`，24 项）

### Iteration 2 增量
- `test_preinserted_fixed_dangling_value_initialize_succeeds`：预置固定 dangling 值后健康 initialize
  通过，t_lots/audit 全行 + history + user_version 逐值不变。
- `test_missing_foreign_key_rejected`：缺外键 tamper 中预置 `__tgrid_probe_no_such_lot` 冲突 id，弱
  schema 仍被拒绝。

### Iteration 1（保持）
- Migration：MAX_SCHEMA_VERSION=3；MIGRATIONS 精确三迁移；fresh/v2→v3/幂等/rollback。
- 约束：合法最小行；悬空 t_lot_id；NULL/空必填字段；from/to status 合法+NULL 接受、非法拒绝。
- Immutable：UPDATE/DELETE 拒绝且原行逐值保持。
- Tamper：删表/trigger/列、弱化 status、缺/错外键、no-op update/delete trigger 全部 fail closed。
- legacy probe IDs 预置后 initialize 通过；verifier 零残留（全行/history/version 一致）。

## 既有测试更新
- `test_persistence.py`（授权）：history 3 条、user_version=3、FORBIDDEN_DOMAIN_TABLES 不含
  `t_lot_audit_log`。
- `test_cli.py`（授权）：仅一条 user_version 与两条 history count 2→3。
- `test_t_lot_schema.py`（REV-G2T003-002 架构师授权）：MAX_SCHEMA_VERSION/history/version 机械更新
  2→3，未弱化约束断言。

## 结果汇总
| 检查项 | 结果 |
|---|---|
| 579 项 unittest | OK |
| compileall | exit 0 |
| AST 安全扫描 | PASS（23 文件） |
| REV-G2T003-001 独立 FI 重放 | 健康库通过且不变；缺外键 tamper 仍拒绝 |
| migration/FK/immutable trigger/tamper | PASS |
| 无真实 QMT/DB/账号访问 | 通过（仅临时文件） |

## 结论
全部检查通过。REVIEW_READY。
