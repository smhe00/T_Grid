# Gate 5 / Claude Report — Shadow 模式（WOULD_BUY / WOULD_SELL）

## Status

`REVIEW_READY` — Gate 5（Shadow 模式代码与报告生成器）实现完成，等待架构师 Review
（本会话内自审）。真实 QMT 的 5 交易日影子运行属于用户环境人工执行步骤（本仓提供全部离线逻辑）。

## Scope（design §40）

MarketData/BrokerQuery = REAL（调用方接入 Gate 1 只读 Adapter），Execution = SHADOW：

- `src/tgrid/shadow/engine.py`：`ShadowEngine` — 策略全管线（复用 Gate 3 ACCUMULATE 引擎 +
  风控）产出 **WOULD_BUY / WOULD_SELL** 记录，绝不调用任何券商接口（INV-009）。
  - `ShadowOrder`（WOULD 订单）、`SignalRecord`（信号日志）、`ReconciliationRow`
    （shadow vs broker 对账）、`DailyReport`（§46 每日报告行）。
  - `build_shadow_reports`：一次性组装 Shadow Orders / Signal Log / Reconciliation
    Report / Daily Report 四份 §40 交付物（data-only dict）。
  - `assume_fill_price` 假设模型：调用方可选择按限价/收盘价回填影子持仓与影子 PnL，
    不接券商也能评估"本来会发生什么"。
- `src/tgrid/shadow/__init__.py`：导出批准面。

## Design §40 交付物

1. Shadow Orders — 每条 WOULD_BUY/WOULD_SELL（symbol/side/qty/limit/时间/decision/reason）。
2. Signal Log — 每个 bar 的决策与原因。
3. Reconciliation Report — 影子持仓 vs 券商持仓 delta，delta≠0 即不一致。
4. Daily Report — anchor/ATR%/Grid/Open T Lots/Realized T PnL/Shadow Orders/Halt/Violations。

## Evidence

- `work/reports/tests/G5-test-output.txt`：**11 项 shadow 测试全部通过**；compileall exit 0；
  shadow 源码 AST 扫描无 order_stock/cancel_order_stock/cancel_order；完整回归
  **794 tests OK**（783 + 11）。

## Boundary

- 不连接 QMT、不读真实账号/行情（真实接入由用户环境执行）、不下单/撤单；`live_trading_allowed=false`。
- 未实现：真实 QMT 5 交易日影子运行编排（用户人工执行，见 GATE_5_RUNBOOK）、Kill Switch CLI、
  每日报告落盘服务。

## Recommendation

REVIEW_READY（等待架构师独立 Review；通过后编写 Gate 5 人工运行手册与 Gate 6/7 文档化步骤）。
