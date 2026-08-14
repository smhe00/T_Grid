# Implementation Report — G2-T001 / Iteration 2

## Task
G2-T001 — 离线不可变 Core Position Guard（Iteration 2 修复 REV-G2T001-001 至 -004）

## Summary
仅离线修复四个问题：Strategic Position 隔离、真实 SymbolConfig 复用、字段重命名、撤销越权文件。
未实现 Ledger/DB/Reconciliation/OrderIntent/QMT/交易。

## Files Changed（Iteration 2 增量）
- `src/tgrid/position/manager.py`：
  - `PositionSnapshot`：字段 `open_t_lots` → `open_t_lot_position`；T 模块 protected floor =
    `Core + StrategicExtra`；`available_t_qty = min(can_use, open_t_lot_position) - reserved`；
    `validate_t_sell` 第 1 项改为 `qty > open_t_lot_position` → `CoreFloorViolation`。
  - 新增 `snapshot_from_symbol_config`：core 只来自 `SymbolConfig.core_qty`（exact 类型校验、无第二 core
    输入、配置 frozen、非法 core 拒绝）。
- `src/tgrid/position/__init__.py`、`src/tgrid/__init__.py`：导出 `snapshot_from_symbol_config`。
- `src/tgrid/risk/__init__.py`：**撤销** G2-T001 改动（移出 Allowed Files）。
- `tests/unit/test_position_manager.py`：新增 `TestStrategicIsolation`（5 项）、`TestSymbolConfigBinding`
  （5 项），字段重命名同步。
- `work/reports/tests/G2-T001-test-output.txt` 重新生成（523 项 + 全部扫描）。

## Design Mapping
- §17 / INV-008（Strategic/Core 禁止 T 模块自动退出）：protected floor = Core + StrategicExtra，
  `validate_t_sell` 只允许卖 open T-lot quantity。
- §4 / INV-005 / §50：可用数量非负、双数量保护、CorePositionGuard 最高优先级。
- §5（Broker = Core + Strategic + OpenTLot）：构造时精确分解校验。
- 复用 `SymbolConfig`（REV-002）：core 输入唯一来源。

## Deviations
NONE

## Tests Added（Iteration 2，9 项净增）
- strategic-only / mixed / reserved-mixed 三组 Strategic 隔离 FI；T=0 任何正卖出拒绝、mixed 最多卖 open
  T-lot、失败后快照不变。
- SymbolConfig 绑定：core 取自 config、无第二 core 输入（inspect.signature）、wrong type 拒绝、config
  frozen、非 plain-int core 拒绝。

## Test Commands / Results
```text
python -m unittest discover -s tests -p "test_*.py" -v   -> Ran 523 tests ... OK（514 基线 + 9 净增）
python -m compileall -q src tests                         -> exit 0
AST scan src/tgrid（23 文件）                             -> PASS
git diff --check -- :/T_Grid                              -> exit 0
```
完整输出：`work/reports/tests/G2-T001-test-output.txt`。

## Failure Injection（Iteration 2）
- strategic-only/mixed/reserved-mixed 全矩阵；T=0 任何正卖出拒绝。
- `snapshot_from_symbol_config` 的 core 漂移不可达、wrong type、frozen、非法 core。
- 字段重命名无旧 alias；risk/__init__.py 越权改动已撤销。

## Invariant Check
1. 数量 plain int / symbol 非空 plain string：通过。
2. 分解精确相等：通过。
3. 快照 frozen：通过。
4. Broker<Core → CoreFloorViolation；可用数量非负：通过。
5. T 卖出量正 plain int、依次 Core Floor / 可用量 / 预留检查、互不替代：通过。
6. Strategic/Core 不被重分类或修改：通过（REV-001）。
7. 无 assert、fail-closed：通过。
8. `live_trading_allowed=false`，无 XtQuant/order/cancel：通过。

## Static / Type / Lint Check
- AST 扫描 23 文件：无 `ast.Assert`、无字面 xtquant import、无 order/cancel/download/subscribe 调用。
- `git diff --check -- :/T_Grid`：exit 0。

## Git Diff Summary
- HEAD == 基线 `20e00c14b9a71b1800ce54fe2a69ee6903b39fa4`。
- 变更仅限本任务 Allowed Files + 协议控制/报告文件；父目录/reverse_repo 未改动；未 commit/push。

## Known Issues
NONE

## Questions
NONE

## Recommendation
REVIEW_READY
