# Gate 3 Architect Review

## Verdict

`GATE 3 PASS`（Architect independent review，`2026-08-15T05:00:00+08:00`）。

Gate 3（策略算法离线模拟）验收通过，允许进入 Gate 4（Execution Dry Run）。

## Scope Reviewed

- 指标数学：`vwap20` / `ema20` / `atr14`（Wilder 平滑）/ `atr_pct` — 纯函数、fail-closed、
  长度不足/零成交量显式拒绝（§9/§10）。
- 自适应网格：`grid_pct` 截断公式、几何买入线 `Buy_n = Anchor(1-G)^n`、成本退出价
  `Exit = Entry(1+G×ExitMultiplier)`、`price_tick` 合法化（§10/§11/§18.1，Decimal 精确）。
- 复权口径：`PriceBasis` RAW/ADJUSTED 严格区分，`adjust_historical_prices` 不可变复权，
  指标连续性测试通过（§7.1）。
- 数据质量守护：新鲜度/缺bar/重复/乱序/价格与成交量合法/停牌 7 类问题，全部 → `DATA_HALT`（§26.2）。
- 波动暂停与事件封锁：`DailyMove>K_halt×ATR%`、`Gap>2G`、人工事件窗口 `[d-before, d+after]`（§28/§29）。
- ACCUMULATE 引擎：每日冻结 Anchor（VWAP20→EMA20 回退）、5m bar 决策流、LIFO 退出、
  `max_t_lots` 容量（INV-002）、`target_qty` 上限（INV-003）、挂单互斥（INV-004）、
  卖出门复用 Gate 2 `CorePositionGuard`（INV-001/005/012）、数据/事件/波动暂停只禁新开不禁目标退出。

## Independent Verification

- 完整回归：**748 tests OK**（638 既有 + 110 策略）；compileall exit 0。
- AST 禁止能力扫描：35 个 `src` Python 文件，assert/order/cancel/download/subscribe/xtquant 命中 0。
- 设计 §38 四场景独立重放：A（买入→卖出→CORE 不变）、B（2 lot 上限 → T_CAPACITY_FULL）、
  C（gap → VOLATILITY_HALT 且当日持续）、D（SELL_REJECTED 四种原因矩阵）全部符合预期。
- 关键不变量抽查：`legalize_price` 无浮点噪声（420.0/0.2 == 420.0）；复权后 VWAP20/ATR14 与
  连续序列一致；LIFO 选最新 lot；卖 fill 必须匹配 LIFO；frozen 结果不可变。

## Boundary Acknowledged

- 未连接 QMT、未查询账号/行情、未下单/撤单；`live_trading_allowed=false`。
- 引擎输出 data-only `BarDecision`，成交/部分成交/撤单由 Gate 4 SimBroker 执行层处理。
- 未实现 OrderIntent/Reservation 持久化、Crash Recovery、SAFE_MODE 编排、真实日历数据源。

## Next Gate

进入 **GATE 4 — Execution Dry Run**：SimBroker 全链路（行情→信号→订单→部分成交→成交→T-Lot→
卖出→PnL），模拟 reject/partial fill/timeout/cancel failure/limited reprice/duplicate callback/
out-of-order callback/concurrent intent/reserved 冲突/crash after broker send/restart/disconnect。
