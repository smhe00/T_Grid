# G2-T001 Result — Iteration 2

## Status
`PASS`。Iteration 2 已关闭 REV-G2T001-001..004，并通过架构师独立复核；随本任务验收提交。

## Iteration 2 offline evidence
- 523 tests OK (514 + 9 net new); compileall 0; AST scan PASS (23 files);
  git diff --check clean; HEAD == 20e00c1.
- Evidence: work/reports/tests/G2-T001-test-output.txt

## REV outcomes
- 001: T module protected floor = Core + StrategicExtra; available_t_qty and
  validate_t_sell capped by open_t_lot_position (design §17, INV-008).
- 002: snapshot_from_symbol_config binds core from SymbolConfig.core_qty only.
- 003: open_t_lots -> open_t_lot_position (no legacy alias).
- 004: risk/__init__.py G2-T001 change reverted.

## Independent architect evidence
- 523 项 unittest 全部通过；compileall、diff-check 与 AST safety scan 通过。
- strategic-only：`available_t_qty=0`，sell 1/100 均 `CoreFloorViolation`。
- mixed strategic+T：最多只允许卖 `open_t_lot_position`；超出即拒绝。
- reserved mixed：边界量通过，超出 1 股为 `SellReservationConflict`。
- config factory 的签名不含第二个 core 参数，实际 core 精确来自 frozen `SymbolConfig.core_qty`。
- 旧 `open_t_lots` 字段不存在；`src/tgrid/risk/__init__.py` 无任务差异。

## Ruling
G2-T001 PASS。该裁决只覆盖离线 Position Snapshot / Core Position Guard，不证明 Ledger、对账或交易能力。
