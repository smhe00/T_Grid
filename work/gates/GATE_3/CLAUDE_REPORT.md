# Gate 3 / Claude Report — 策略算法离线模拟

## Status

`REVIEW_READY` — Gate 3（策略算法离线模拟）实现完成，等待架构师 Review（本会话内自审）。

## Scope（design §38）

实现全部离线策略数学与引擎，禁止连接真实交易接口：

- `src/tgrid/strategy/bars.py`：不可变 `Bar`（OHLCV + kind + price_basis）、`SessionWindow`
  （交易所本地时段窗口，§26.1/§27）。
- `src/tgrid/strategy/indicators.py`：`vwap20` / `ema20` / `atr14`（Wilder）/ `atr_pct`（§9/§10）。
- `src/tgrid/strategy/grid.py`：`grid_pct`（G = clip(max(G_min, K_ATR×ATR%), G_min, G_max)，§10）、
  `buy_level`（Buy_n = Anchor(1-G)^n，§11）、`exit_target_price`（Exit = Entry(1+G×ExitMultiplier)，§11/§15）、
  `legalize_price`（§18.1 按 price_tick 合法化，BUY 向下、SELL 向上，Decimal 精确防浮点噪声）。
- `src/tgrid/strategy/corporate_action.py`：`PriceBasis`（RAW/ADJUSTED，§7.1）、`CorporateActionFactor`、
  `adjust_historical_prices`（拆股/送转因子复权，指标只用单一复权口径）。
- `src/tgrid/strategy/quality.py`：`check_bar_quality` / `DataQualityGuard`（§26.2：新鲜度、缺bar、
  重复、乱序、价格/成交量合法、停牌）。
- `src/tgrid/strategy/halts.py`：`volatility_halt`（§28：DailyMove>K_halt×ATR% 或 Gap>2G）、
  `EventBlockRule` / `event_blocked`（§29 人工事件封锁窗口）。
- `src/tgrid/strategy/engine.py`：`AccumulateStrategy`（§12–§16/§31 状态机）：
  - `begin_day`：每日开盘前冻结 Anchor/ATR/Grid（VWAP20 优先，EMA20 回退）。
  - `on_bar`：数据质量 → 事件封锁 → 波动暂停 → 时段过滤 → 卖出评估（LIFO）→ 买入触发（§13）。
  - `record_buy_fill` / `record_sell_fill`：部分成交/实际成交价建仓，目标价按实际成交价计算（§24）。
  - 卖出门复用 Gate 2 `CorePositionGuard`（Core Floor / Available Volume / Reservation，INV-001/005/012）。
  - 容量 `max_t_lots`（INV-002）、目标上限 `target_qty`（INV-003）、挂单互斥（INV-004）、
    `pending` 标记与取消。

## Scenarios（design §38 必测）

- **Scenario A**（440→420→445）：BUY T → SELL T，CORE 不变 — PASS。
- **Scenario B**（440→420→400）：2 个 T-Lot 上限，再触发 → `T_CAPACITY_FULL` — PASS。
- **Scenario C**（440→400 gap）：`VOLATILITY_HALT`，当天持续 — PASS。
- **Scenario D**（T 仓存在 + Core Floor 不足）：`SELL_REJECTED`（CORE_FLOOR /
  INSUFFICIENT_AVAILABLE_VOLUME / SELL_RESERVATION_CONFLICT / POSITION_INVARIANT）— PASS。

## Evidence

- `work/reports/tests/G3-test-output.txt`：**110 项策略测试全部通过**；compileall exit 0；
  AST 禁止能力扫描 35 个 src 文件命中 0；完整回归 **748 tests OK**（638 + 110）。

## Boundary

- 不连接 QMT、不查询账号/行情、不下单/撤单；`live_trading_allowed=false`。
- 引擎输出 data-only `BarDecision`，不直接报单；执行层（Gate 4 SimBroker）负责成交/部分成交/撤单。
- 未实现：OrderIntent/Reservation 持久化、Crash Recovery、SAFE_MODE 编排、真实日历数据源
  （SessionWindow 为显式输入）、财报自动抓取（§29 人工配置）。

## Recommendation

REVIEW_READY（等待架构师独立 Review，本会话内由同一上下文自审后进入 Gate 4）。
