# Implementation Report — G2-T002

## Task
G2-T002 — 事务化 T-Lot Ledger Schema（migration v2 + 语义 schema verifier）。Iteration 2 只修
REV-G2T002-001..005；不实现 CRUD/Audit/Reconciliation/OrderIntent/QMT/交易。

## Summary
Iteration 1 的 545 项回归通过但 SQLite 独立 FI 发现 schema/verifier 缺陷。Iteration 2 完成：

- 数据库级类型语义：`id` 显式 NOT NULL；`qty` 必须是 `typeof='integer'` 且 > 0；price 字段非 NULL 时
  必须是 integer/real storage class 且为正；文本不能利用 storage-class 排序绕过 `> 0`。
- 财务语义：`realized_pnl` 允许负数/零/正数（只要求 numeric storage type）；`fees` 允许零、拒绝负数和文本。
- probe 隔离：每个约束 probe 使用与现有行确认不冲突的独立 ID；不再依赖未声明的保留 ID namespace；
  PK 冲突不能再造成"健康库被拒"或"弱化约束假通过"。
- verifier 覆盖补齐：NULL id、空 id/symbol/side/entry_time/created_at/updated_at、fractional qty、
  文本价格、非法 review_status 全部行为式探测；review_status 允许集合与 NULL 行为验证。
- `tests/unit/test_cli.py` 只保留三条机械断言更新（一条 user_version、两条 migration history count
  1→2），REV-G2T002-005。

## Files Changed
- `src/tgrid/persistence/migrations.py`：`T_LOT_LEDGER_STATEMENTS` 增加 storage-class 与 NOT NULL
  约束（id NOT NULL、qty `typeof` integer、price/fees `typeof` numeric guard、realized_pnl 任意数值、
  fees `>= 0`）。
- `src/tgrid/persistence/database.py`：`_T_LOTS_COLUMNS` 的 id notnull 0→1；`_verify_t_lot_constraints`
  重写为"唯一 probe id + 逐字段目标探针 + 财务/ review 接受探针"；新增 `_valid_t_lot_row`/`_insert_row`/
  `_pick_probe_id`/`_expect_accept`；`_verify_t_lot_no_delete_trigger` 使用非冲突 probe id 与参数化 DELETE。
- `tests/unit/test_t_lot_schema.py`：直接插入测试扩展（NULL/空 id、fractional/文本 qty、文本价格、
  realized_pnl 任意数值、fees 零/负/文本、review_status 集合）；tampered schema 模板化并预置冲突 ID；
  新增 legacy probe ID 预置、弱化 id/entry_price-type/review_status tamper 测试；verifier probe 前后
  逐值不变验证。
- `tests/unit/test_persistence.py`：schema v2 预期（history 2 条、user_version=2）；未弱化 Gate 0 测试。
- `tests/unit/test_cli.py`：仅三条断言 1→2（REV-G2T002-005 授权）。
- `work/reports/tests/G2-T002-test-output.txt`：完整 unittest + compileall + AST + diff-check + 独立 FI 重放。

## Design Mapping
- §6 T-Lot 字段与状态：全字段 + 7 状态枚举；qty 为整数股数、entry_price 为正 REAL；realized_pnl/fees
  为 REAL（可零/负 pnl，fees 非负）。
- §16.1 review 字段：5 个 review 字段；review_status 枚举与 NULL 允许。
- §21–23 启动 SQLite、禁止静默修复：initialize 每次语义验证、行为式探针、不自动修复。
- INV-002/005/008/010/011：数据库级约束、fail-closed、无 assert、无 QMT。

## Reuse Evidence
- 复用现有 `Migration`/`MIGRATIONS`/`initialize`/`open_database`/SAVEPOINT-rollback probe 模式；
  未另建 migration runner 或 SQLite wrapper。
- 约束验证保持行为式 probe（REV-G0T002-003 模式），未回退到 DDL 文本匹配。
- reverse_repo 无 TGrid T-Lot schema；未复制其执行日志/脚本。

## Review Issues — Iteration 2 逐项回复

### REV-G2T002-001 — SQLite 约束接受 NULL ID、fractional qty 与文本价格 — **FIXED**
- `id TEXT NOT NULL PRIMARY KEY CHECK(length(trim(id)) > 0)`：显式 NOT NULL + 非空。
- `qty INTEGER NOT NULL CHECK(typeof(qty) = 'integer' AND qty > 0)`：拒绝 1.5、0、负数、非数值文本。
- `entry_price`/`target_price`/`grid_pct`/`exit_price` 非 NULL 时
  `typeof(...) IN ('integer','real')` 且为正：文本 `'abc'` 不再能靠 storage-class 排序通过。
- 直接插入测试：`test_null_and_empty_id_rejected`、`test_fractional_qty_rejected`、
  `test_text_entry_price_rejected`、`test_optional_price_fields_positive_numeric_when_present`。
- tampered-schema 测试：`test_fake_weak_id_length_check_rejected`、`test_fake_weak_numeric_type_guard_rejected`。
- 独立重放：`NULL_ID/EMPTY_ID/FRACTIONAL_QTY/QTY_TEXT/TEXT_ENTRY_PRICE/TEXT_TARGET_PRICE/STATUS_LOWERCASE`
  全部 REJECTED。

### REV-G2T002-002 — 固定 probe ID 既拒绝健康数据库又制造约束假阳性 — **FIXED**
- `_pick_probe_id` 先 `SELECT id FROM t_lots` 排除现有（含事务内已插入）行，再返回非冲突 ID；约束
  probes 各用独立 ID，PK 冲突不可能成为目标约束证据。
- 不再依赖保留 ID namespace：合法预置 `__tgrid_probe_valid/bad/delete` 后 initialize 通过且行内容、
  migration history、user_version 逐值不变（`test_preinserted_legacy_probe_ids_initialize_succeeds`）。
- 弱化 qty/status schema 并预置冲突 ID 仍被 verifier 识别（`test_fake_weakened_qty_constraint_rejected`、
  `test_fake_always_true_status_constraint_rejected`，均含 `__tgrid_probe_bad` 行）。
- 所有 probe 在 `BEGIN...ROLLBACK` 内，失败也回滚，不残留行。

### REV-G2T002-003 — realized PnL 与 fees 的财务语义错误 — **FIXED**
- `realized_pnl CHECK(realized_pnl IS NULL OR typeof(realized_pnl) IN ('integer','real'))`：负/零/正均接受。
- `fees CHECK(fees IS NULL OR (typeof(fees) IN ('integer','real') AND fees >= 0))`：零接受、负数/文本拒绝。
- 直接插入测试：`test_realized_pnl_accepts_any_numeric_rejects_text`、`test_fees_accepts_zero_and_positive_rejects_negative_and_text`。
- verifier 接受探针覆盖 pnl=-1.5/0/5 与 fees=0/0.5。
- 独立重放：`REALIZED_PNL_NEG/ZERO/POS ACCEPTED`；`FEES_ZERO/POS ACCEPTED`，`FEES_NEG/FEES_TEXT REJECTED`。

### REV-G2T002-004 — 行为 verifier 覆盖不足 — **FIXED**
- `_verify_t_lot_constraints` 现在逐字段探测：NULL id、空 id/symbol/side/entry_time/created_at/updated_at、
  qty=0/-1/1.5/文本、entry_price=0/-1/文本、target/grid/exit price=0/文本、status 空/小写/未知/部分、
  realized_pnl 文本、fees 负/文本、review_status 非法。
- review_status 允许集合（NULL、PENDING、RESUME_T、KEEP_SUSPENDED、CONVERT_TO_STRATEGIC、MANUAL_EXIT）
  全部接受、非法拒绝（`_verify_t_lot_constraints` 接受探针 + `test_review_status_null_and_allowed_accepted_invalid_rejected`）。
- 每个 probe 只改一个字段且 ID 唯一，异常确由目标字段触发。
- 用户行、migration history、user_version 在 probe 前后逐值不变
  （`test_verifier_probe_leaves_no_rows_or_history_changes` 对比 `SELECT *` 全行 + history + user_version）。
- SQLite 意外异常仍由 `initialize` 转换为 PersistenceError 层。

### REV-G2T002-005 — test_cli.py 超出 Iteration 1 Allowed Files — **FIXED**
- Iteration 2 仅授权保留三条精确断言更新：`test_cli.py` 中一条 `PRAGMA user_version` 与两条
  `schema_migrations COUNT` 从 1 改为 2；其余内容未改动（`git diff tests/unit/test_cli.py` 仅 3 行）。

## Deviations
NONE（相对 Iteration 2 授权范围无偏差）。

## Tests Added
`tests/unit/test_t_lot_schema.py` 由 22 项扩展至 32 项；新增：
- NULL/空 id、fractional/文本 qty、文本 entry_price、文本可选价格。
- realized_pnl 任意数值、fees 零/负/文本、review_status 集合。
- legacy probe ID 预置、弱化 id/entry_price-type/review_status tamper。
- verifier probe 前后全行/history/user_version 逐值不变。

## Test Commands / Results
```text
python -m unittest discover -s tests -p "test_*.py" -v   -> Ran 555 tests ... OK（545 基线 + 10 新增/拆分）
python -m compileall -q src tests                         -> exit 0
AST scan src/tgrid（23 文件）                             -> PASS，forbidden=0
git diff --check -- :/T_Grid                              -> exit 0（仅 CRLF 提示）
独立 SQLite FI 重放                                       -> 全部符合 Review 边界
```
完整输出：`work/reports/tests/G2-T002-test-output.txt`。

## Failure Injection
- migration-2 中途非法 SQL → 完整 rollback 到干净 v1，修复后可再升级（既有测试保持）。
- `CHECK(qty>0 OR 1=1)` / 任意 status / 弱化 id length / 弱化 entry_price numeric-type / 无 review_status
  CHECK 的伪造 v2 → 语义 verifier 拒绝（非字符串误判）。
- 同名但允许删除的 trigger → 行为 delete probe 拒绝。
- 非空 t_lots + legacy probe ID 上运行 verifier → 不删不改真实行，initialize 通过。
- 独立重放见 artifact：弱化 qty/status + 冲突 ID 均 REJECTED。

## Invariant Check
1. Migration 2 单事务原子：通过（rollback 探针）。
2. v1→v2 不删不改 migration 1 / metadata：通过（标记保留）。
3. 重开幂等：通过。
4. DELETE t_lots 数据库层拒绝、无 bypass helper：通过。
5. status 仅 7 值，未知/大小写/空数据库层拒绝：通过。
6. qty 正整数语义、price 为正 numeric；非法 probe 不留测试行：通过。
7. 版本/history/schema/trigger/约束一致否则 PersistenceError 子类：通过。
8. 不自动修复被篡改的表/trigger：通过。
9. 无 assert、SQLite 异常 fail closed：通过。
10. `live_trading_allowed=false`，无 QMT/order/cancel：通过。

## Static / Type / Lint Check
- AST 扫描 23 文件：无 `ast.Assert`、无字面 xtquant import、无 order/cancel/download/subscribe 调用。
- `git diff --check -- :/T_Grid`：exit 0。

## Git Diff Summary
- HEAD == 基线 `72704850a8344eb1173108497402984242f5075f`。
- 变更：2 生产文件（migrations/database）+ 2 测试文件（test_t_lot_schema 新增、test_persistence 授权更新）
  + test_cli.py 三条断言（Iteration 2 授权）+ 报告/证据/控制文件；父目录/reverse_repo 未改动；未 commit/push。

## Known Issues
NONE

## Questions
见 `QUESTIONS.md`（test_cli.py 问题已由 REV-G2T002-005 授权解决，无阻塞问题）。

## Recommendation
REVIEW_READY
