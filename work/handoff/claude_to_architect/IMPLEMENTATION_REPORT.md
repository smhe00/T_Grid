# Implementation Report — G2-T006

## Task
G2-T006 — Offline Position Reconciliation Decision Engine（纯离线、fail-closed 对账决策层，单 symbol）。
不连接 QMT、不查 SQLite、不持久化 SAFE_MODE、不实现启动编排。

## Summary
新增 `reconcile_position(symbol_config, *, symbol, broker_position, strategic_extra,
open_t_lot_position) -> PositionReconciliationResult`：以 `SymbolConfig.core_qty` 为唯一 Core 来源，
`LocalExpectedPosition = CoreQty + StrategicExtra + OpenTLotPosition`，按决策优先级返回不可变结果：
1. 输入无效 → `PositionInvariantError`（fail closed，无结果）；
2. `broker < core` → `SAFE_MODE/CORE_FLOOR_BREACH`；
3. 其它 `delta != 0` → `SAFE_MODE/BROKER_POSITION_MISMATCH`；
4. 精确相等 → `RECONCILED/MATCH`。

## Files Changed
- `src/tgrid/position/reconciliation.py`（新增）：`reconcile_position`、frozen
  `PositionReconciliationResult`、决策/原因常量；输入校验（exact SymbolConfig、exact 非空 str、exact
  非负 int）。
- `src/tgrid/position/__init__.py`：仅导出本任务批准的 reconcile/result/常量。
- `tests/unit/test_position_reconciliation.py`（新增，20 项）。
- `work/reports/tests/G2-T006-test-output.txt`（新增完整证据）。

未修改 `manager.py`、任何 `persistence/**`、`models.py` 及既有测试。

## Decision / Reason Matrix
| broker_position | core_qty | strategic_extra | open_t_lot_position | LocalExpected | decision / reason | delta |
|---|---|---|---|---|---|---|
| 600 | 600 | 0 | 0 | 600 | RECONCILED / MATCH | 0 |
| 700 | 600 | 100 | 0 | 700 | RECONCILED / MATCH | 0 |
| 700 | 600 | 0 | 100 | 700 | RECONCILED / MATCH | 0 |
| 800 | 600 | 100 | 100 | 800 | RECONCILED / MATCH | 0 |
| 700 | 600 | 0 | 0 | 600 | SAFE_MODE / BROKER_POSITION_MISMATCH | +100 |
| 600 | 600 | 100 | 0 | 700 | SAFE_MODE / BROKER_POSITION_MISMATCH | -100 |
| 500 | 600 | 0 | 100 | 700 | SAFE_MODE / CORE_FLOOR_BREACH | -200（优先级） |
| 60000 | 600 | 0 | 0 | 600 | SAFE_MODE / BROKER_POSITION_MISMATCH | +59400 |

## Core Source Authority
- Core 唯一来自 frozen `SymbolConfig.core_qty`；无第二份调用方 core 参数/覆盖。
- `reconcile_position` 严格 `type(symbol_config) is SymbolConfig`，fake/subclass 对象在读取任何属性前被拒绝。

## Mismatch Non-Reclassification Evidence
- 任意正/负 delta（含等于 `t_unit` 的 +100）一律 `BROKER_POSITION_MISMATCH`，不做 Strategic/T-Lot/人工成交推断。
- 不修改、不重分类 `strategic_extra` / `open_t_lot_position`；结果仅含校验后的组件值与决策。

## Reuse Evidence
- 复用 frozen `SymbolConfig`（core_qty 唯一来源）。
- 输入拒绝复用现有 `PositionInvariantError`（position-domain 异常层），未建新的异常根。
- 未使用 `PositionSnapshot`（其强制相等语义不能表达对账差异）；未改动已 PASS 的 `manager.py`。

## Tests Added（20 项）
1. zero-only / core+strategic / core+T / mixed 精确相等 → RECONCILED/MATCH，expected/delta 正确。
2. 结果 frozen dataclass，变异失败（FrozenInstanceError）。
3. 正/负 delta、t_unit-like +100 不重分类、大 delta → SAFE_MODE/BROKER_POSITION_MISMATCH。
4. `broker < core` 优先级 → CORE_FLOOR_BREACH（即使同时存在 mismatch）。
5. core=0/broker=0 合法匹配。
6. 负数量、bool/float/str/bytes/list/dict/int-subclass、fake/subclass SymbolConfig、None → `PositionInvariantError`。
7. 空/空白/非 str/str-subclass symbol → `PositionInvariantError`。
8. 恶意 quantity `__int__/__index__/__eq__`、恶意 symbol `__str__/__eq__` 不执行，异常图无 secret。
9. 输入组件不变、结果 data-only、无 mutation/repair callback。
10. AST：新模块无 assert/sqlite3/xtquant/order/cancel/download/subscribe/socket/filesystem/network。

## Failure Injection
- EvilInt / EvilStr / FakeConfig / subclass / None 注入 → `PositionInvariantError`，`__cause__/__context__` None、无 secret。
- broker<core 与 mismatch 并存 → 优先级取 CORE_FLOOR_BREACH。
- 大 delta 与 t_unit-like delta → 一律 mismatch，不推断。
- 独立重放（artifact 内全文）全部符合边界。

## Test Commands / Results
```text
python -m unittest discover -s tests -p "test_*.py" -v   -> Ran 638 tests ... OK（618 基线 + 20 新增）
python -m compileall -q src tests                         -> exit 0
PACKAGE_SCAN（26 文件）                                   -> PASS，assert/xtquant/order-cancel=0
NEW_MODULE_SCAN（reconciliation.py）                      -> asserts=0，sqlite/open/network token=none
git diff --check（本任务文件）                            -> exit 0
```
完整输出：`work/reports/tests/G2-T006-test-output.txt`。

## Invariant Check
1. Core 唯一来源 `SymbolConfig.core_qty`，无 alternate core：通过。
2. 数量 exact 非负 int，拒绝 bool/float/str/bytes/容器/int-subclass/任意对象：通过。
3. symbol exact 非空 str，拒绝 subclass/空白：通过。
4. 拒绝时不调用未知对象 dunder：通过（type check 先行）。
5. mismatch 不改变/重分类 strategic_extra/open_t_lot_position：通过。
6. broker<core 优先级恒为 CORE_FLOOR_BREACH：通过。
7. 其它非零 delta 恒为 BROKER_POSITION_MISMATCH（与 t_unit 无关）：通过。
8. 精确相等 RECONCILED/MATCH：通过。
9. 结果 frozen/data-only，无 callable/connection/cursor/client/config mutator：通过。
10. 无 QMT/SQLite/filesystem/network/order/cancel/download/subscribe，无 assert 安全机制：通过。
11. `live_trading_allowed=false`：通过。

## Known Issues
NONE

## Questions
NONE

## Recommendation
REVIEW_READY
