# GATE 6 / GATE 7 人工验证步骤（真实资金阶段）

> Gate 6 是**首次允许真实订单**的 Gate，Gate 7 是 V1 正式运行。二者必须由用户在真实
> MiniQMT 环境中人工执行；本仓库代码已提供全部离线逻辑（策略/风控/执行/Shadow），
> 此文档只列出人工验证清单与硬性边界。

## 硬性边界（任何情况不得违反）

- `live_trading=true` 必须由**人工显式配置并二次确认**（§41）。
- 默认 `LIVE_TRADING = FALSE`（INV-009）；无真实下单代码路径在本仓库中。
- Core Floor（INV-001）、T Capacity（INV-002）、Target Ceiling（INV-003）、
  单方向单挂单（INV-004）、无静默对账（INV-006）、无自动止损（INV-007）全部保持。

## GATE 6 — 极小真实资金验证（§41）

范围（只能更小，不能更大）：

```text
1 symbol
1 t_unit            （如 100 股）
max_t_lots = 1
禁止多股票 / 多 T-Lot / 自动 Strategic Buy
```

人工验证清单：

1. **真实成交**：一次 BUY 成交，T-Lot 按实际成交价/数量入账（§24）。
2. **部分成交**：构造或等待部分成交，验证 T-Lot qty 按真实成交数量而非委托数量。
3. **成交回调**：callback 只入队，唯一事件线程处理（§3.1，INV-014）。
4. **实际费用**：fees 正确记录并计入 realized PnL。
5. **撤单**：超时/人工撤单 → 重新查询订单/成交（§25，禁止 cancel 后假设未成交）。
6. **T+1 / can_use_volume**：验证 `can_use_qty` 与卖出预留公式（§4/§18.3）。
7. **港股通订单行为**：0700.HK 的 lot_size / price_tick / 最小报价验证。
8. **程序重启**：下单后杀掉进程，重启后 Broker Orders + Trades + OrderIntent 重建状态（§23）。
9. 每日检查 `Core Floor Violations = 0`。

## GATE 7 — V1 正式运行（§42）

范围：

```text
多个配置证券
max_t_lots <= 2
ACCUMULATE only
per-symbol max_t_capital
global minimum_cash_buffer
```

仍禁止：NEUTRAL / DISTRIBUTE / 自动正T / 动态 CoreQty / AI 预测。

人工验证清单：

1. 每交易日生成 §46 每日运行报告（Date/Equity/Available Cash/各 symbol Core/Strategic/T/
   Broker/Anchor/ATR/Grid/Buy Levels/Targets/Orders/Trades/Realized PnL/Fees/Violations）。
2. 长期绩效指标（§47）：T Enhancement、TCapitalReturn、Max T Capital、Stuck>20d/>60d。
3. 成功标准（§48）：Core Violation = 0、Unknown Position = 0、Duplicate Order = 0、
   Unreconciled Trade = 0、Unexpected Live Order = 0，且 NetTProfit > 0。
4. Kill Switch（§30）人工演练：触发后停止新单、保留日志、查询当前订单、可选撤销挂单，
   绝不自动平仓。
5. SUSPENDED 批次（§16.1）：占用容量、超期 Review 项进入每日报告、人工动作四选一。

## 退出/回退

- 任何不变量违反 → 立即进入 SAFE_MODE / 停止，保留证据，人工修复后再继续。
- 未完成 Gate 6 全部清单之前，不得进入 Gate 7。
