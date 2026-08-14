# Gate 2 / Claude Report — G2-T001

## Status
G2-T001 **Iteration 2 修复完成**（REV-G2T001-001 至 -004 全部 FIXED），交付 `REVIEW_READY / iteration=2`。

## Iteration 2 修复内容

### REV-G2T001-001（P0）— Strategic Position 隔离
- T 模块的 protected floor 改为 `Core + StrategicExtra`（design §17、INV-008）；`available_t_qty` 与
  `validate_t_sell` 均不得超过实际 `open_t_lot_position`，且仍受 `can_use_qty` 与 `reserved_sell_qty` 限制
  （reservation 只扣减一次）。
- strategic-only（T=0）任何正卖出拒绝；mixed 最多只卖 Open T-Lot quantity；失败后快照不变；Strategic
  不被自动重分类。

### REV-G2T001-002（P1）— 真实复用 SymbolConfig
- 新增 `snapshot_from_symbol_config`：公开、受测的构造路径，core 只来自 `SymbolConfig.core_qty`，签名
  无第二份 core 输入（inspect.signature 证明）；严格校验 exact `SymbolConfig` 类型、配置保持 frozen、
  非法 core 拒绝；未复制配置校验、未新增第二套配置类。

### REV-G2T001-003（P1）— 字段重命名
- `open_t_lots` → `open_t_lot_position`（与设计 `OpenTLotPosition` 一致、无歧义、无旧 alias）；测试/文档
  /报告同步。

### REV-G2T001-004（P1）— 撤销越权文件
- 撤销 `src/tgrid/risk/__init__.py` 的 G2-T001 改动；顶层 `tgrid.__init__` 保留为批准公共导出。

## 证据
- `work/reports/tests/G2-T001-test-output.txt`（**523 项全部通过** + compileall exit 0 + AST 23 文件扫描
  PASS + Iteration 2 Failure Injection 摘要）。
- `git diff --check -- :/T_Grid` exit 0；HEAD == 基线 `20e00c1`。

## 范围遵守
未连接 QMT、未访问账号/行情、未修改既有 Adapter/Probe/integrations/persistence/reverse_repo、
未实现 Ledger/DB/Reconciliation/OrderIntent/Reservation；`live_trading_allowed=false`；未 commit/push。

## Recommendation
REVIEW_READY（等待 Desktop ChatGPT 独立 Review）。
