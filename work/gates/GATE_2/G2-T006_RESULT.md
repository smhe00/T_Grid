# G2-T006 Result — PASS

## Status

`PASS`（Architect independent review，`2026-08-15T04:00:00+08:00`）。

G2-T006 仅验收离线 Position Reconciliation 决策引擎：用外部提供的 Broker 持仓与本地期望分解
（`LocalExpected = CoreQty + StrategicExtra + OpenTLot`）比较，返回不可变决策。
任何无法解释的 delta 进入 `SAFE_MODE`，绝不猜测为 Strategic/T-Lot/人工交易。
纯决策原语：不连接 QMT、不查询 SQLite、不持久化 SAFE_MODE、不做启动编排。

## Scope Delivered

- `src/tgrid/position/reconciliation.py`（新增）：
  - `reconcile_position(symbol_config, *, symbol, broker_position, strategic_extra,
    open_t_lot_position) -> PositionReconciliationResult`。
  - Core 唯一权威来自 frozen `SymbolConfig.core_qty`，无第二个 core 输入。
  - 决策优先级：输入无效 → `PositionInvariantError`；`broker < core` →
    `SAFE_MODE/CORE_FLOOR_BREACH`（最高优先）；其它非零 delta →
    `SAFE_MODE/BROKER_POSITION_MISMATCH`；精确相等 → `RECONCILED/MATCH`。
  - 结果 frozen/data-only：symbol/decision/reason/broker/local_expected/delta/core/strategic/open_t。
- `src/tgrid/position/__init__.py`：仅导出本任务批准的 reconcile/result/常量。
- `tests/unit/test_position_reconciliation.py`（新增，20 项）。

## Independent Verification

- 完整回归：**638 tests OK**（含本任务 20 项）；compileall exit 0。
- AST 禁止能力扫描：25 个 `src` Python 文件，assert/QMT/order/cancel/download/subscribe 命中 0。
- 独立失败注入重放：
  - `Broker=600, Local=600` → RECONCILED/MATCH；`Broker=700, Local=600` → SAFE_MODE/MISMATCH
    delta=+100；`Broker=600, Local=700` → SAFE_MODE/MISMATCH delta=-100；
    `Broker=400, core=600` → SAFE_MODE/CORE_FLOOR_BREACH（优先级覆盖其它 delta）。
  - t_unit 级 delta 不推断、不重分类；恶意 int/str subclass 与 FakeConfig 在零属性读取前拒绝；
    结果 frozen，components 原值保留。
- diff-check clean；无 QMT/SQLite/SAFE_MODE 持久化/启动编排；`live_trading_allowed=false`。

## Deliberate Boundary（保持）

- 不实现 Reconciliation 编排、Crash Recovery、SAFE_MODE 持久化、OrderIntent、人工交易分类。
- 不修改 `manager.py` / `persistence/**` / `models.py` / 既有测试。

## Independent Architect Review

- 决策矩阵与设计 §21–22（Broker 是持仓事实来源、SQLite 是意图事实来源、禁止静默修复）、
  §22.1（未知持仓变化 → SAFE_MODE，禁止自动归类）、§4/INV-001 一致。
- broker<core 优先级满足 INV-001（Core Floor）最高优先级原则。
- `REV` 无未决项；`G2-T006 PASS`。
