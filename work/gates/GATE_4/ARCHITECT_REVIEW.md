# Gate 4 Architect Review

## Verdict

`GATE 4 PASS`（Architect independent review，`2026-08-15T06:00:00+08:00`）。

Gate 4（Execution Dry Run）验收通过，允许进入 Gate 5（Shadow 模式）。

## Scope Reviewed

- **OrderIntent 持久化（§18.2/INV-013）**：migration 4，`client_order_key` 幂等主键，意图先于报单
  写入，重复 key 硬拒绝；§24 状态集合单一来源（模型+DB CHECK 一致）。
- **Reservation（§18.3/INV-012）**：migration 5，意图+预留同一原子事务；SELL 预留数量、
  BUY 预留现金；仅按真实终态 release（poll/取消路径验证）；`reserved_sell_qty/reserved_cash`
  汇总正确。
- **SimBroker（§39）**：确定性脚本驱动 FILL/PARTIAL/REJECT/TIMEOUT/CANCEL_FAIL；断线；
  独立订单/成交账本供 §23 恢复。
- **Executor（§24/§25）**：poll 先 tick 后读（部分成交折叠）；timeout→cancel→re-query→
  reconcile，cancel 失败绝不假设未成交（预留保持）；实际成交价回填（§24）。
- **Recovery（§23）**：MATCHED / INTENT_ONLY / UNMATCHED_BROKER_ORDER 三分类；
  UNMATCHED 即重复报单风险（SAFE_MODE 输入）；INTENT_ONLY 不盲发。
- **DryRunHarness**：全链路 PnL（实际成交价 entry/exit，gross/fees/net）。

## Independent Verification

- 完整回归：**783 tests OK**（748 + 35 执行）；compileall exit 0。
- AST 禁止能力扫描：42 个 `src` Python 文件，`assert` / `order_stock` / `cancel_order_stock` /
  `xtquant` import 命中 0。
- §39 失败矩阵独立重放：reject、partial、timeout、cancel failure（预留保持）、duplicate
  callback no-op、concurrent intent、reserved cash/sell conflict（冲突单释放，不残留）、
  crash-after-send（INTENT_ONLY 恢复 + MATCHED）、restart（DB+broker 重建后 poll 到 FILLED）、
  disconnect（报单前断线 intent 可恢复且无 broker id）。
- schema 行为化探针：order_intents/order_reservations 列、CHECK、FK、禁删触发器、terminal
  禁转全部通过；migration 历史 = (1..5)。

## Invariants

- INV-009：无真实下单路径（SimBroker 注入，无 order_stock/cancel_order_stock）。
- INV-011：src AST assert 命中 0。
- INV-012/013：预留与意图原子、同 key 不重复报单。
- INV-004：pending_order_keys 支撑单方向单挂单；执行层不做策略互斥之外的猜测。

## Boundary Acknowledged

- 未连接 QMT、未读真实账号/行情、未下单/撤单；`live_trading_allowed=false`。
- 未实现 SUSPENDED review 编排、Corporate Action 对账编排、Kill Switch CLI、每日运行报告。

## Next Gate

进入 **GATE 5 — Shadow 模式**：真实 MarketData/BrokerQuery + SHADOW 执行（WOULD_BUY/WOULD_SELL，
绝不下单），Shadow Orders / Signal Log / Reconciliation Report / Daily Report 输出，至少
5 个交易日影子运行（真实环境由用户执行；本仓提供全部离线影子逻辑与报告生成器）。
