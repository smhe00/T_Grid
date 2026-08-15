# Gate 4 / Claude Report — Execution Dry Run

## Status

`REVIEW_READY` — Gate 4（Execution Dry Run）实现完成，等待架构师 Review（本会话内自审）。

## Scope（design §39）

建立完整离线执行链路（行情→信号→订单→部分成交→成交→T-Lot→卖出→PnL），全部失败注入可复现：

- `src/tgrid/persistence/migrations.py`：migration 4 `order_intents`（§18.2，client_order_key
  幂等主键 + §24 状态 CHECK + 禁删触发器）、migration 5 `order_reservations`（§18.3，BUY 现金 /
  SELL 数量预留 + FK + 禁删触发器）。`MAX_SCHEMA_VERSION` 5，`database.py` 新增行为化 schema
  验证（列结构、CHECK、FK、触发器、约束探针）。
- `src/tgrid/execution/models.py`：`OrderIntent` / `Reservation` frozen 数据模型 +
  §24 单一状态集合。
- `src/tgrid/execution/store.py`：`ExecutionStore` — `create_intent_with_reservation`
  （意图+预留同一 `BEGIN IMMEDIATE` 事务，INV-013/§18.3）、状态流转（terminal 禁转）、
  预留 release、`reserved_sell_qty` / `reserved_cash` 汇总。
- `src/tgrid/execution/simbroker.py`：`SimBroker` — 确定性脚本（FILL/PARTIAL/REJECT/TIMEOUT/
  CANCEL_FAIL）、断线、独立订单/成交账本（§23 恢复输入）。
- `src/tgrid/execution/executor.py`：`ExecutionEngine` — 意图先写后报单（§18.2 三步）、
  预留冲突门（§18.3）、poll（tick 后读）、timeout→cancel→re-query→reconcile（§25）、
  cancel 失败不假设（§25）、`fill_price` 回填（§24 实际成交价）。
- `src/tgrid/execution/recovery.py`：`reconcile_open_intents` — MATCHED / INTENT_ONLY /
  UNMATCHED_BROKER_ORDER（§23，重复报单风险 → SAFE_MODE 信号）。
- `src/tgrid/execution/dryrun.py`：`DryRunHarness` — 策略决策→执行→T-Lot→PnL 全链路封装，
  PnL = (exit-entry)×qty - fees。

## §39 Failure Matrix（全部覆盖）

reject / partial fill / timeout / cancel failure / limited reprice（cancel→re-query 语义）/
duplicate callback（terminal no-op）/ out-of-order callback（LIFO 强制 + poll 幂等）/
concurrent buy/sell intent（pending_order_keys + 预留冲突）/ reserved cash conflict /
reserved sell conflict / crash after broker send before local write（INTENT_ONLY/MATCHED 恢复）/
restart（DB + broker 账本重建）/ disconnect（报单前断线 → recoverable intent）。

## Evidence

- `work/reports/tests/G4-test-output.txt`：**35 项执行测试全部通过**；compileall exit 0；
  AST 禁止能力扫描 42 个 src 文件命中 0（order_stock/cancel_order_stock 未出现）；
  完整回归 **783 tests OK**（748 + 35）。
- 全链路：buy fill → lot → sell fill → PnL 记录（entry 按实际成交价、gross/fees/net）。

## Boundary

- 不连接 QMT、不查询真实账号/行情、不下单/撤单；`live_trading_allowed=false`。
- SimBroker 是注入的模拟券商；真实券商适配（order_stock 等）仍不存在。
- 未实现：SUSPENDED review 编排、Corporate Action 对账编排、Kill Switch CLI、每日运行报告生成。

## Recommendation

REVIEW_READY（等待架构师独立 Review，本会话内由同一上下文自审后进入 Gate 5 Shadow）。
