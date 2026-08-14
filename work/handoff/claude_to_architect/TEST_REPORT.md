# Test Report — G2-T002

## Task
G2-T002 — 事务化 T-Lot Ledger Schema（migration v2 + 语义 verifier）。Iteration 2 修复
REV-G2T002-001..005。

## Environment
- 默认 Python 3.12.10；全部测试使用临时 SQLite 文件，无真实 DB / QMT / 账号访问。

## Commands Run（完整输出见 `work/reports/tests/G2-T002-test-output.txt`）

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p "test_*.py" -v` | **555 项全部 OK**（545 基线 + 10 新增/拆分） |
| `python -m compileall -q src tests` | 退出 0 |
| AST 扫描 `src/tgrid/**/*.py`（23 文件） | PASS：assert=0 / xtquant import=0 / order-cancel=0 |
| `git diff --check -- :/T_Grid` | exit 0（仅 CRLF 提示） |
| 独立 SQLite FI 重放 | 全部符合 Review 边界 |
| HEAD 与基线 | `7270485...` == base |

## 独立 Review Failure Injection 重放（artifact 内全文）

| 输入 | 结果 |
|---|---|
| `NULL_ID` / `EMPTY_ID` | REJECTED |
| `FRACTIONAL_QTY` (1.5) / `QTY_TEXT` ("abc") | REJECTED |
| `TEXT_ENTRY_PRICE` / `TEXT_TARGET_PRICE` | REJECTED |
| `STATUS_LOWERCASE` ("open") | REJECTED |
| `REALIZED_PNL_NEG` / `_ZERO` / `_POS` | ACCEPTED |
| `FEES_ZERO` / `FEES_POS` | ACCEPTED |
| `FEES_NEG` / `FEES_TEXT` | REJECTED |
| 预置 `__tgrid_probe_valid/bad/delete` 后 initialize | 成功；行/history/user_version 逐值不变 |
| 弱化 qty/status + 冲突 ID 的伪造 v2 | REJECTED（SchemaVersionError） |

## 新增/扩展测试覆盖（`tests/unit/test_t_lot_schema.py`，32 项）

### Migration
- MAX_SCHEMA_VERSION=2；MIGRATIONS 精确 `[(1, bootstrap), (2, t_lot_ledger)]`。
- fresh DB：user_version=2、t_lots + no-delete trigger + 2 条 history。
- v1→v2 升级保留 metadata 标记；重开幂等；migration-2 非法 SQL 完整 rollback 后再升级。

### 约束（直接插入）
- NULL/空 id；空 symbol/side/entry_time/created_at/updated_at → 拒绝。
- qty 0 / -1 / 1.5 / "abc" → 拒绝。
- entry_price 0 / -1 / "abc" → 拒绝；target/grid/exit price 0 / -1 / "abc" → 拒绝。
- status 空/小写/未知/部分 → 拒绝；7 个合法状态接受。
- realized_pnl -1.5 / 0 / 5 → 接受；"abc" → 拒绝。
- fees 0 / 0.5 → 接受；-1 / "abc" → 拒绝。
- review_status NULL 与 5 个合法值接受；"BOGUS" → 拒绝。
- DELETE → 拒绝且原行保留。

### no-delete / tamper
- 删表 / 删 trigger / 删列 → SchemaVersionError。
- 弱化 qty、任意 status、弱化 id length、弱化 entry_price numeric-type、无 review_status CHECK、
  trigger 名在但行为不 abort → 全部 SchemaVersionError，且弱化 qty/status 测试预置了冲突 ID。
- legacy probe ID 预置后 initialize 通过，行/history/user_version 逐值不变。
- verifier probe 前后 `SELECT *` 全行 + history + user_version 完全不变。

## 既有测试更新
- `test_persistence.py`（授权）：history 2 条、user_version=2、FORBIDDEN_DOMAIN_TABLES 移除 t_lots。
- `test_cli.py`（Iteration 2 授权 REV-G2T002-005）：仅三条断言 1→2（一条 user_version、两条 history
  count）；`git diff` 证明无其他改动。

## 结果汇总
| 检查项 | 结果 |
|---|---|
| 555 项 unittest | OK |
| compileall | exit 0 |
| AST 安全扫描 | PASS（23 文件） |
| Review FI 独立重放 | 全部符合边界 |
| migration 原子/rollback/幂等/tamper | PASS |
| 约束/trigger/probe 隔离行为验证 | PASS |
| 无真实 QMT/DB/账号访问 | 通过（仅临时文件） |

## 结论
全部检查通过。REVIEW_READY。
