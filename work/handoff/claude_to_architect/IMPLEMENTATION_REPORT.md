# Implementation Report

## Task
G0-T001 — 项目骨架与配置安全基础（Iteration 3，响应 CHANGES_REQUIRED）

## Summary
Iteration 3 只修复 `FIX_REQUEST.md` 的 Iteration 3 Active Fixes：REV-G0-006（P1）与 REV-G0-007（P1）。历史 REV-G0-001..005 已关闭，未重复修改。

## Iteration 3 Fixes（逐 Issue 回复）

### REV-G0-006（P1）— Strict YAML Loader 泄漏原始 TypeError → FIXED
`src/tgrid/config.py::_construct_mapping_strict` 改为在插入 mapping 前显式 `hash(key)` 校验键可哈希性；不可哈希键（如 sequence/list/dict 键）直接抛出携带 line/column 的 `ConfigError`（"key must be a hashable scalar"），并以 `from None` 屏蔽内部 `TypeError` 上下文，不再让 `mapping[key] = ...` 泄漏裸 `TypeError`。
新增测试：`test_unhashable_sequence_key_rejected`（含 line 与 "key" 信息）、`test_unhashable_key_does_not_leak_type_error`（确认抛 `ConfigError` 而非 `TypeError`）。

### REV-G0-007（P1）— 缺少 root 层重复键回归测试 → FIXED
新增 `test_duplicate_root_global_rejected`：文件级注入 root 层重复 `global` 段，断言抛 `ConfigError` 且错误包含 `duplicate`、键名 `global` 与位置 `line` 信息。

## Files Changed（Iteration 3）
- `src/tgrid/config.py` — `_construct_mapping_strict` 显式键可哈希性校验。
- `tests/unit/test_config.py` — 新增 3 项测试（REV-G0-006 ×2、REV-G0-007 ×1）。
- 交接控制文件与报告（见下）。

## Design Mapping
不变（同 Iteration 1/2）；本轮仅加强 fail-closed 边界（设计 §34 INV-010，协议 §22 原子/健壮控制文件解析）。

## Deviations
NONE

## Tests Added（Iteration 3）
- `TestDuplicateKeys.test_duplicate_root_global_rejected`
- `TestDuplicateKeys.test_unhashable_sequence_key_rejected`
- `TestDuplicateKeys.test_unhashable_key_does_not_leak_type_error`

## Test Commands
```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
```

## Test Results
61 项全部通过（`Ran 61 tests ... OK`）；`compileall` 退出码 0。完整输出见 `work/reports/tests/G0-T001-test-output.txt`。

## Failure Injection（累计）
Iteration 1 的 7 项 + Iteration 2 的重复键/枚举/只读映射 + Iteration 3：unhashable sequence key（`? [a, b] : value`）、root 层重复 `global`。全部抛出明确 `ConfigError`，无裸 `TypeError` 泄漏。

## Invariant Check
1–10 全部满足；新增边界：不可哈希/非标量 mapping key fail-closed（统一 `ConfigError`）。

## Static / Type / Lint Check
`compileall` 退出码 0；AST 扫描确认源码无 `ast.Assert`、无 `xtquant` import、无 `order_stock`/`cancel_order`。

## Git Diff Summary
T_Grid 目录整体未跟踪（`?? ./`），无 commit。变更仅限 Allowed Files 与架构师既有控制文件；未修改权威文档、`CURRENT_TASK.md`、`ARCHITECT_HEARTBEAT.md`、`GATE_0/TASK.md`、`work/design/**`，未触碰父目录。

## Known Issues
NONE

## Questions
NONE

## Recommendation
REVIEW_READY
