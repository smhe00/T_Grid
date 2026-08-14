# Implementation Report — G2-T003

## Task
G2-T003 — Append-Only T-Lot Audit Log Schema（migration v3 + 行为式 verifier）。Iteration 2 只修
REV-G2T003-001..002；不实现 writer/CRUD/状态转换/Reconciliation/OrderIntent/QMT/交易。

## Summary
Iteration 1 的 578 项回归通过但独立 FI 发现：dangling-FK probe 使用固定字符串 `__tgrid_probe_no_such_lot`
作为 t_lot_id，一旦合法用户 T-Lot 使用该 id，外键探针变成合法引用，健康数据库被误判为缺失外键。Iteration 2
将该探针改为通过现有 collision-safe helper 选择已确认不存在的 t_lots.id；并按 REV-G2T003-002 确认保留
Iteration 1 对 test_t_lot_schema.py 的机械版本预期更新。

## Review Issues — Iteration 2 逐项回复

### REV-G2T003-001 — 固定 dangling-FK probe ID 会拒绝健康数据库 — **FIXED**
- `_verify_t_lot_audit_log_constraints` 现在先
  `dangling_lot_id = _pick_probe_id(conn, "t_lots", "__tgrid_probe_no_such_lot")`，从 t_lots.id 中选取
  已确认不存在的值用于 dangling probe；不再依赖固定字符串或保留 ID namespace。
- 新增回归 `test_preinserted_fixed_dangling_value_initialize_succeeds`：预置 id 为
  `__tgrid_probe_no_such_lot` 的合法 T-Lot 与 audit 行后，健康 initialize 通过，t_lots/audit 全行、
  migration history、user_version 全部逐值不变。
- `test_missing_foreign_key_rejected` 在缺外键的伪造 v3 schema 中预置同一冲突 id，verifier 仍因真正
  dangling probe 被接受（非 PK 冲突/无关约束）而拒绝弱 schema。
- 所有成功/失败路径仍在 `BEGIN...ROLLBACK` 内，零 probe 残留。
- 独立重放（artifact 内全文）：`initialize_OK True`、`rows_unchanged`、
  `missing_fk_with_conflict -> REJECTED (SchemaVersionError)`。

### REV-G2T003-002 — 确认必要的既有 T-Lot 测试版本更新 — **FIXED（architect-authorized）**
- Iteration 2 明确授权保留 Iteration 1 对 `tests/unit/test_t_lot_schema.py` 的精确机械 diff：
  MAX_SCHEMA_VERSION、MIGRATIONS、fresh/upgrade/reopen/rollback 后的 latest version/history 从 2 扩展到 3。
- 该文件其它约束、tamper、probe 或业务断言未改动；`git diff tests/unit/test_t_lot_schema.py` 可复核。
- 报告标记为 architect-authorized scope correction，不再是 unresolved question（QUESTIONS.md 已更新）。

## Files Changed（Iteration 2 增量）
- `src/tgrid/persistence/database.py`：dangling-FK probe 改用 `_pick_probe_id` 选取非冲突 t_lots.id。
- `tests/unit/test_t_lot_audit_schema.py`：新增 `test_preinserted_fixed_dangling_value_initialize_succeeds`；
  `test_missing_foreign_key_rejected` 预置冲突 id。
- `work/reports/tests/G2-T003-test-output.txt`：重新生成（**579 项全部通过** + compileall + AST +
  diff-check + Iteration 2 独立 FI 重放）。

（Iteration 1 已交付的 migration 3 / audit verifier / 测试 / test_cli 与 test_persistence 版本更新保持不变。）

## Design Mapping
- §6 所有状态变化必须保留 Audit Log：`t_lot_audit_log` + 两个 immutable trigger。
- §7.1 Corporate Action 调整写 Audit Log：`details_json` 非空文本承载 payload（业务解析后续实现）。
- §21–23 启动 SQLite、禁止静默修复：行为式 verifier、fail-closed、不自动修复。
- INV-002/005/008/010/011：数据库级约束、无 assert、无 QMT。

## Reuse Evidence
- 复用现有 `Migration`/`MIGRATIONS`/`initialize`/`_verify_columns`/SAVEPOINT-rollback 模式。
- dangling 探针复用 G2-T002 的 `_pick_probe_id`（collision-safe）与 `_expect_integrity`，未复制近似实现。

## Tests Added（Iteration 2 增量）
- `test_preinserted_fixed_dangling_value_initialize_succeeds`（1 项）：预置固定 dangling 值后健康
  initialize 通过，全行/history/user_version 逐值不变。
- `test_missing_foreign_key_rejected` 扩展：预置冲突 id 后弱 schema 仍被拒绝。

## Test Commands / Results
```text
python -m unittest discover -s tests -p "test_*.py" -v   -> Ran 579 tests ... OK（578 基线 + 1 新增）
python -m compileall -q src tests                         -> exit 0
AST scan src/tgrid（23 文件）                             -> PASS，forbidden=0
git diff --check（本任务文件）                            -> exit 0
独立 FI 重放（REV-G2T003-001）                            -> 健康库通过且不变；缺外键 tamper 仍拒绝
```
完整输出：`work/reports/tests/G2-T003-test-output.txt`。

## Failure Injection
- 健康 v3 DB 预置 `__tgrid_probe_no_such_lot` 合法 T-Lot + audit 行 → initialize 通过、逐值不变。
- 缺外键伪造 schema 预置同一冲突 id → verifier 仍拒绝（SchemaVersionError）。
- 其余 Iteration 1 FI（rollback/tamper/immutable trigger/零残留）保持通过。

## Invariant Check
1. Migration 3 单事务原子：通过。
2. v2→v3 不删不改既有 metadata/history/t_lots/trigger：通过。
3. 合法 audit 行只能引用已存在 T-Lot；悬空 t_lot_id 数据库层拒绝：通过（collision-safe dangling probe）。
4. audit 行禁止 UPDATE/DELETE、无 bypass helper：通过。
5. from/to status 为 NULL 或七状态；未知/大小写/空拒绝：通过。
6. 所有 probe 用非冲突 ID、完整 rollback、不改用户行/history/user_version：通过。
7. 缺表/列/外键/弱化约束/同名不拦截 trigger 均 fail closed：通过。
8. 无 assert、SQLite 异常进入 PersistenceError 层：通过。
9. `live_trading_allowed=false`，无 QMT/order/cancel/download/subscribe：通过。

## Static / Type / Lint Check
- AST 扫描 23 文件：无 `ast.Assert`、无 xtquant import、无 order/cancel 调用。
- `git diff --check`（本任务文件）：exit 0。

## Git Diff Summary
- HEAD == 基线 `aa13ef9d9a556e0b837b95ba80c78fdddc41ca6d`。
- Iteration 2 变更：database.py（dangling probe 修复）+ test_t_lot_audit_schema.py（回归/扩展）+ 证据/报告/
  控制文件；父目录/reverse_repo 未改动；未 commit/push。

## Known Issues
NONE

## Questions
NONE（REV-G2T003-002 已由架构师授权；见 QUESTIONS.md）。

## Recommendation
REVIEW_READY
