# GATE 5 实机验证报告（真实 MiniQMT 影子运行）

> **状态：`SUPERSEDED`（NODEA-R4-003，2026-08-15）**
> 本报告记录的 10 日回放结果（含 +13.3 PnL 与 `LIVE VERIFIED` 措辞）是在
> NODEA-R4-001（无 look-ahead 日线）、逐日因子、可信策略/对账配置之前的旧运行，
> **不作为当前 Gate-5 验收证据**。当前代码的实机重跑证据需用新 CLI 重新生成
> （见 `GATE5_RUNBOOK.md`）。下文保留为历史记录。

## Status

`SUPERSEDED` — 原 `LIVE VERIFIED`（`2026-08-15`）已因 NODEA-R4 修复作废。

## 环境（已脱敏，AUD-R1-005）

- QMT：MiniQMT 模拟交易端（sp3 build），xtdata 连接成功。
- Python：仓库 venv（含 xtquant），`PYTHONPATH=src`。
- 账户：simulation 环境（数量、资金、路径、端口等运行时细节不在此文档披露）。
- 命令：`python scripts/gate5_shadow_live.py --config config/gate1_qmt.local.json --out
  work/reports/shadow/10day-2026-08-14 --date 2026-08-14 --code 510300.SH --run-days 10`

## 证据分类（AUD-R1-004）

本次运行证据类别为：

```text
REAL_QMT_HISTORICAL_REPLAY + REAL_BROKER_SNAPSHOT
```

使用真实 MiniQMT 行情数据与真实券商持仓快照，但 5m bar 来自历史回放（单次运行内重放
10 个交易日的已下载 bar）。**这不是**跨 10 个自然日的连续实时 live-soak；若后续执行
实时连续运行，将作为独立证据类别另行记录。

## 运行结果（510300.SH，10 个交易日历史回放）

| 交付物 | 结果 |
|--------|------|
| Shadow Orders | **4 条**（2 WOULD_BUY + 2 WOULD_SELL，见下） |
| Signal Log | 480 条（逐 5m bar 决策 + 原因） |
| Reconciliation Report | 真实对账（real broker vs local expected）delta=0 |
| Shadow Delta | 影子假设活动单独报告（AUD-R1-003） |
| Daily Report | anchor=4.6869, ATR%=1.74%, G=1.2%, Realized T PnL=**+13.3**, halt=NONE |

### Shadow Orders（真实行情触发）

| # | 方向 | 数量 | 限价 | 时间 | 触发 |
|---|------|------|------|------|------|
| 1 | WOULD_BUY | 100 | 4.651 | 08-03 09:45 | Buy_1 = anchor(1-G) |
| 2 | WOULD_BUY | 100 | 4.595 | 08-03 14:05 | Buy_2 = anchor(1-G)² |
| 3 | WOULD_SELL | 100 | 4.659 | 08-04 13:40 | LIFO 退出（最新 lot 目标价） |
| 4 | WOULD_SELL | 100 | 4.668 | 08-04 14:10 | LIFO 退出（剩余 lot） |

- 完整 ACCUMULATE 循环：下跌建 2 仓（max_t_lots=2 容量生效，后续下跌触发
  `T_CAPACITY_FULL` 正确拒绝）→ 反弹按 LIFO 平仓 → 影子持仓归零。
- 期间无 EVENT_BLOCK / VOLATILITY_HALT / DATA_HALT（数据质量守护正常放行午休 11:30–13:00）。

## 本次实机验证发现并修复的问题

1. **`get_trading_calendar` 不被该 QMT 客户端实现**（"function not realize"，ErrorID 300000）：
   交易日历改用 `get_trading_dates`（可用）。已在运行器与文档中记录该客户端限制。
2. **数据质量守护把午休（11:30→13:00）误报为缺 bar（DATA_HALT）**：修复
   `tgrid.strategy.quality`，`check_bar_quality` / `DataQualityGuard` 新增可选
   `session`（SessionWindow），跨午休的间隔按计划内处理；跨交易日边界（隔夜）不再误报
   MISSING；`_iso_seconds` 改为真实日历秒（修复跨日乱序误判）。均有回归测试。
3. **Shadow 运行必须逐日冻结 basis**（设计 §9）：多日 5m 数据不能用单日 anchor 一次喂完，
   否则产生虚假 VOLATILITY_HALT。运行器改为按交易日循环 `begin_day`。
4. **Shadow 位置模型**：策略视角必须使用"真实券商持仓 + 结算释放的影子可卖量"的有效持仓；
   影子假设活动与真实对账分离（AUD-R1-003）；真实对账比较 real broker vs
   Core+Strategic+OpenT（INV-005/006）。
5. **violations 语义**：只统计真实风控/不变量失败（CORE_FLOOR / POSITION_INVARIANT /
   T_CAPACITY_FULL 等），常规门（TIME_WINDOW / PRICE_ABOVE_BUY_LEVEL）不算违规。

## 验证证据

- `work/reports/shadow/10day-2026-08-14/{shadow_orders,signal_log,reconciliation,
  shadow_delta,daily_report,evidence}.json`
- `work/reports/shadow/2026-08-14/*.json`（单日运行）
- 测试：`python -m unittest discover -s tests -p "test_*.py"` → 全量通过（含
  AUD-R1-001/002/003/007 聚焦测试）。

## 结论

Gate 5 影子模式已用真实 MiniQMT 行情与账户快照完成 10 个交易日历史回放验证：
信号生成、LIFO 退出、容量限制、数据质量、T+1 结算、复权口径、真实/影子对账分离
全部符合设计 §40 与独立审计要求（AUD-R1-001..007）。
`live_trading_allowed=false`，全程未发送任何真实订单。
