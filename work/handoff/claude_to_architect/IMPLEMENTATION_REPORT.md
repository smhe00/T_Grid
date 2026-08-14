# Implementation Report

## Task
G0-T002 — SQLite 初始化与迁移安全基础（Iteration 4，响应 CHANGES_REQUIRED）

## Summary
Iteration 4 只修复 `FIX_REQUEST.md` 的 Iteration 4 Active Fix Request：REV-G0T002-001 的遗留问题——partial unique index 被误判为完整 name 唯一约束。

## Iteration 4 Fix

### REV-G0T002-001（OPEN）— partial unique index 被误判为完整 name 唯一约束 → FIXED
`src/tgrid/persistence/database.py::_get_unique_index_column_sets` 增加对 `PRAGMA index_list` 返回的 `partial` 标志（row[4]）的判断：`partial=1` 的唯一索引被跳过，不再计入列集合。因此只有**覆盖恰好 `("name",)` 且 `partial=0`** 的 UNIQUE index 才能满足契约。
- `CREATE UNIQUE INDEX ... ON schema_migrations(name) WHERE version > 100` → 被跳过 → `SchemaVersionError`。
- 合法内联 `name TEXT UNIQUE` → 仍是 partial=0 单列唯一 → 接受。
- Iteration 3 已通过的 wrong-column、composite、永真 CHECK 行为探针及合法 history 无副作用性质保持不变。

## Files Changed（Iteration 4）
- `src/tgrid/persistence/database.py` — `_get_unique_index_column_sets` 增加 partial 过滤。
- `tests/unit/test_persistence.py` — 新增 `test_partial_unique_name_index_rejected`。
- `work/reports/tests/G0-T002-test-output.txt` — 重新生成，含 partial 独立探针。

## Design Mapping
不变；继续落实 §30 fail-closed 与协议 §22 的结构化/行为验证原则。

## Deviations
NONE

## Tests Added（Iteration 4）
- `TestSchemaContractValidation.test_partial_unique_name_index_rejected`

## Test Commands
```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
```

## Test Results
101 项全部通过（`Ran 101 tests ... OK`）；`compileall` 退出码 0。完整输出见 `work/reports/tests/G0-T002-test-output.txt`。

## Failure Injection（累计）
Iteration 1/2/3 的 15 项 + Iteration 4：partial unique index（`WHERE version > 100`）→ REJECTED；合法 bootstrap → ACCEPTED 且 history 不变。

全部 fail closed，不删除损坏文件、不自动降级、不泄漏裸异常。

## Invariant Check
1–10 全部满足；UNIQUE(name) 验证现要求 partial=0。

## Static / Type / Lint Check
`compileall` 退出码 0；AST 扫描 `src/tgrid/` 无 `ast.Assert`、无 `xtquant`、无 `order_stock`/`cancel_order`。

## Git Diff Summary
未 commit（`git_head_commit` 保持基线 `80c498c`）。变更仅限 Allowed Files。未修改权威文档、`CURRENT_TASK.md`、`ARCHITECT_HEARTBEAT.md`、`GATE_0/TASK.md`、`work/design/**`，未触碰父目录。

## Known Issues
NONE

## Questions
NONE

## Recommendation
REVIEW_READY
