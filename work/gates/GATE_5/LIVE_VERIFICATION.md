# GATE 5 实机验证报告（真实 MiniQMT 影子运行）

## Status

`LIVE VERIFIED` — `2026-08-15`，连接真实 MiniQMT（simulation 环境）完成 Gate 5 Shadow 运行。

## 环境

- QMT：国金证券 QMT 交易端（`D:\国金证券QMT交易端\userdata_mini`），xtdata 连接成功
  （`127.0.0.1:58610`，sp3）。
- Python：`D:\gitee\miniQMT\.venv`（含 xtquant），`PYTHONPATH=src`。
- 账户：simulation 环境，可用资金 ¥6,407,462.06；持仓 511010.SH × 25400。
- 命令：`python scripts/gate5_shadow_live.py --config config/gate1_qmt.local.json --out
  work/reports/shadow/10day-2026-08-14 --date 2026-08-14 --code 510300.SH --run-days 10`

## 运行结果（510300.SH，10 个连续交易日）

| 交付物 | 结果 |
|--------|------|
| Shadow Orders | **4 条**（2 WOULD_BUY + 2 WOULD_SELL，见下） |
| Signal Log | 480 条（逐 5m bar 决策 + 原因） |
| Reconciliation Report | shadow=0 vs broker=0，**delta=0，完全一致** |
| Daily Report | anchor=4.6869, ATR%=1.74%, G=1.2%, Realized T PnL=**+13.3**, halt=NONE |

### Shadow Orders（真实行情触发）

| # | 方向 | 数量 | 限价 | 时间 | 触发 |
|---|------|------|------|------|------|
| 1 | WOULD_BUY | 100 | 4.651 | 08-03 09:45 | Buy_1 = anchor(1-G) |
| 2 | WOULD_BUY | 100 | 4.595 | 08-03 14:05 | Buy_2 = anchor(1-G)² |
| 3 | WOULD_SELL | 100 | 4.659 | 08-04 13:40 | LIFO 退出（最新 lot 目标价） |
| 4 | WOULD_SELL | 100 | 4.668 | 08-04 14:10 | LIFO 退出（剩余 lot） |

- 完整 ACCUMULATE 循环：下跌建 2 仓（max_t_lots=2 容量生效，后续 40 次下跌触发
  `T_CAPACITY_FULL` 正确拒绝）→ 反弹按 LIFO 平仓 → 影子持仓归零 → 对账一致。
- 期间无 EVENT_BLOCK / VOLATILITY_HALT / DATA_HALT（数据质量守护正常放行午休 11:30–13:00）。

## 本次实机验证发现并修复的问题

1. **`get_trading_calendar` 不被该 QMT 客户端实现**（"function not realize"，ErrorID 300000）：
   Gate 1 固定 15 步探针因此无法完整通过。处理：交易日历改用 `get_trading_dates`（可用）。
   已在 Gate 5 运行器与文档中记录该客户端限制。
2. **数据质量守护把午休（11:30→13:00）误报为缺 bar（DATA_HALT）**：修复
   `tgrid.strategy.quality`，`check_bar_quality` / `DataQualityGuard` 新增可选
   `session`（SessionWindow），跨午休的间隔按计划内处理，不再触发 MISSING_BAR
   （新增 5 项回归测试）。
3. **Shadow 运行必须逐日冻结 basis**（设计 §9）：多日 5m 数据不能用单日 anchor 一次喂完，
   否则产生虚假 VOLATILITY_HALT。运行器改为按交易日循环 `begin_day`。
4. **Shadow 位置模型**：策略视角必须使用"真实券商持仓 + 影子成交"的有效持仓，保持
   Broker=Core+Strategic+OpenT 分解（INV-005）；对账仍与真实券商持仓比较。
5. **violations 语义**：只统计真实风控/不变量失败（CORE_FLOOR / POSITION_INVARIANT /
   T_CAPACITY_FULL 等），常规门（TIME_WINDOW / PRICE_ABOVE_BUY_LEVEL）不算违规。

## 验证证据

- `work/reports/shadow/10day-2026-08-14/{shadow_orders,signal_log,reconciliation,daily_report}.json`
- `work/reports/shadow/2026-08-14/*.json`（单日 511010.SH 运行，0 违规）
- 测试：`python -m unittest discover -s tests -p "test_*.py"` → **799 tests OK**。

## 结论

Gate 5 影子模式已用真实 MiniQMT 行情与账户完成 10 个交易日连续验证：
信号生成、LIFO 退出、容量限制、数据质量、对账全部符合设计 §40。
`live_trading_allowed=false`，全程未发送任何真实订单。
