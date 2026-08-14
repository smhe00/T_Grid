# Gate 2 / Claude Report — G2-T006

## Status
G2-T006 **Offline Position Reconciliation Decision Engine 实现完成**，交付 `REVIEW_READY`，等待架构师
Review。将 commit + push 到 GitHub main（fast-forward from `2d83624`）。

## 实现内容
- `src/tgrid/position/reconciliation.py`（新增）：`reconcile_position(symbol_config, *, symbol,
  broker_position, strategic_extra, open_t_lot_position) -> PositionReconciliationResult`。
  - `LocalExpectedPosition = CoreQty + StrategicExtra + OpenTLotPosition`，Core 唯一来自 frozen
    `SymbolConfig.core_qty`。
  - 决策优先级：输入无效 → `PositionInvariantError`；`broker<core` → `SAFE_MODE/CORE_FLOOR_BREACH`；
    其它非零 delta → `SAFE_MODE/BROKER_POSITION_MISMATCH`；精确相等 → `RECONCILED/MATCH`。
  - 结果 frozen/data-only；不重分类任何 delta；无 QMT/SQLite/SAFE_MODE 持久化/启动编排。
- `src/tgrid/position/__init__.py`：仅导出本任务批准的 reconcile/result/常量。

## 关键行为
- 严格输入校验（exact SymbolConfig、exact 非空 str、exact 非负 int），恶意 dunder/secret 隔离。
- 决策矩阵、t_unit-like delta 不推断、broker<core 优先级均经独立 FI 验证。

## 证据
- `work/reports/tests/G2-T006-test-output.txt`（**638 项全部通过** + compileall exit 0 + PACKAGE_SCAN PASS
  + NEW_MODULE_SCAN PASS + 独立 FI 重放全文）。
- 本任务文件 `git diff --check` exit 0。

## 范围遵守
未修改 `manager.py` / `persistence/**` / `models.py` / 既有测试；未连接 QMT、未访问账号/行情、未实现
OrderIntent/Reconciliation 编排/SAFE_MODE 持久化；`live_trading_allowed=false`。

## Recommendation
REVIEW_READY（等待 Desktop ChatGPT 独立 Review）。
