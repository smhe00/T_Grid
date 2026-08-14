# QMT 低频做T交易引擎开发设计文档 V1.1

## 0. 文档状态

**项目代号：** TGrid  
**目标平台：** MiniQMT / XtQuant  
**设计角色：** ChatGPT — 总体架构、算法、Gate Review  
**实现角色：** Claude — 编码、单元测试、阶段报告  
**首批验证标的：** 腾讯控股港股通、美的集团A股  
**V1交易模式：** `ACCUMULATE`，只允许“先买后卖”的低频做T  
**默认模式：** `LIVE_TRADING = false`  
**V1.1修订重点：** Corporate Action、事件队列串行化、订单幂等、持仓/资金Reservation、人工交易检测、交易日历与数据质量保护

---

# 1. 项目目标

TGrid不是普通机械网格交易程序。

系统目标是：

$$
长期核心持仓收益
+
低频波动交易增厚
$$

在**绝不破坏长期底仓**的前提下，尝试增加约：

$$
1\%\sim3\%/年
$$

的持仓收益增强。

系统优先级：

$$
安全性
>
底仓完整
>
状态一致性
>
交易收益
>
交易频率
$$

核心设计原则：

$$
\boxed{
任何做T行为都不能改变长期投资逻辑
}
$$

---

# 2. V1明确不做什么

V1禁止以下功能：

- 不做高频交易；
- 不做Tick级抢单；
- 不做盘口预测；
- 不做机器学习预测；
- 不做趋势追涨；
- 不允许Martingale无限补仓；
- 不允许T模块主动止损长期资产；
- 不允许卖出核心底仓；
- 不做自动基本面判断；
- 不做跨证券资金最优分配；
- 不做自动调整 `core_qty`；
- 不做裸卖；
- 不允许程序自动从 `ACCUMULATE` 切换成 `NEUTRAL/DISTRIBUTE`；
- Gate 5以前禁止真实下单。

---

# 3. 总体架构

系统拆成八个核心模块：

```text
                   ┌──────────────────────┐
                   │     QMT / XtQuant    │
                   │ 行情 / 账户 / 交易   │
                   └──────────┬───────────┘
                              │
                 ┌────────────▼────────────┐
                 │       QMT Adapter       │
                 │ MarketData / Broker API │
                 └────────────┬────────────┘
                              │
         ┌────────────────────▼────────────────────┐
         │               Engine                    │
         │          单线程策略事件循环             │
         └───────┬────────────┬────────────┬──────┘
                 │            │            │
        ┌────────▼───┐ ┌──────▼─────┐ ┌────▼────────┐
        │ Grid Engine │ │ Risk Engine│ │Position Mgr │
        └────────┬───┘ └──────┬─────┘ └────┬────────┘
                 │            │            │
                 └────────────┼────────────┘
                              │
                   ┌──────────▼──────────┐
                   │    T-Lot Ledger     │
                   │      SQLite         │
                   └──────────┬──────────┘
                              │
                     ┌────────▼────────┐
                     │ Reporting/Audit │
                     └─────────────────┘
```

---


# 3.1 V1.1事件模型：单一事件队列

QMT 行情、订单、成交、连接状态等回调可能来自不同线程。

V1.1要求：

```text
QMT Callback
    ↓
Event Queue
    ↓
Single Strategy/Event Thread
    ↓
State Machine
    ↓
Risk Engine
    ↓
Broker Adapter
```

Callback线程**禁止直接**：

```text
修改 T-Lot
修改 Position State
写策略状态到DB
发送订单
改变 Reservation
```

Callback只允许：

```python
event_queue.put(event)
```

所有策略状态变更、订单意图生成、Reservation变更必须由唯一事件线程串行执行。

该原则用于降低并发与竞态风险。

---

# 4. 第一原则：Core Position

每只证券必须显式配置：

```yaml
core_qty:
target_qty:
t_unit:
max_t_lots:
```

定义：

- `core_qty`：绝对不可由T模块卖出的底仓；
- `target_qty`：长期战略目标上限；
- `t_unit`：一次T交易单位；
- `max_t_lots`：同时允许存在多少个T批次。

最重要的不变量：

$$
\boxed{
Position_{after\ sell}\ge CoreQty
}
$$

代码层必须有**至少两道独立、显式、不可被优化关闭的生产级保护**。

禁止使用 Python `assert` 作为资金安全或底仓安全机制。

```python
if current_volume - sell_qty < core_qty:
    raise CoreFloorViolation(...)
```

以及：

```python
if can_use_volume < sell_qty:
    raise InsufficientAvailableVolume(...)
```

V1.1进一步引入卖出数量预留：

$$
AvailableTQty
=
\min(
CanUseVolume,\,
Position-CoreQty
)
-
ReservedSellQty
$$

只有：

```python
sell_qty <= available_t_qty
```

才允许创建卖出 Order Intent。

任何一条失败：

```text
ORDER_REJECTED
reason = CORE_FLOOR / INSUFFICIENT_AVAILABLE_VOLUME / SELL_RESERVATION_CONFLICT
```

**该约束禁止通过配置热更新绕过。**

---

# 5. Position Manager

Position Manager管理三种概念持仓：

```text
Broker Position
Core Position
Virtual T Position
```

满足：

$$
BrokerPosition
=
CorePosition
+
StrategicExtraPosition
+
OpenTLotPosition
$$

注意：

券商/QMT只知道“总共持有多少股”。

例如：

```text
腾讯总持仓：700
```

TGrid内部必须知道：

```text
CORE      = 600
T001      = 100 @ 421.00
```

否则无法可靠判断哪100股可以卖。

---

# 6. T-Lot 虚拟批次账本

使用 SQLite。

核心表：

```sql
CREATE TABLE t_lots (
    id              TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    qty             INTEGER NOT NULL,

    entry_price     REAL NOT NULL,
    entry_time      TEXT NOT NULL,

    target_price    REAL,
    grid_pct        REAL,

    status          TEXT NOT NULL,

    exit_price      REAL,
    exit_time       TEXT,

    entry_order_id  TEXT,
    exit_order_id   TEXT,

    realized_pnl    REAL,
    fees            REAL,

    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
```

允许状态：

```text
PENDING_BUY
OPEN
PENDING_SELL
CLOSED
SUSPENDED
CONVERTED_TO_STRATEGIC
ERROR
```

禁止直接删除历史批次。

所有状态变化必须保留Audit Log。

---

# 7. T批次平仓规则

V1采用：

$$
\boxed{LIFO}
$$

后进先出。

例如：

```text
T001: 100 @430
T002: 100 @410
```

价格反弹到430时：

优先平：

```text
T002
```

而不是T001。

理由：

$$
410\rightarrow430
$$

已经获得足够波动收益，可以更快释放增量资本。

---


# 7.1 Corporate Action 企业行动处理

V1.1新增企业行动处理要求。

系统必须明确区分：

```text
RAW_PRICE       # 实盘交易价格、盘口、委托价格
ADJUSTED_PRICE  # 历史指标计算价格
```

`VWAP20`、`EMA20`、`ATR14` 必须使用**统一复权口径**，不得混用。

企业行动至少包括：

```text
现金分红
送股
转增
拆股
合股
配股
其他导致价格或数量跳变的事件
```

### 规则

1. 现金分红等仅影响价格连续性的事件：
   - 历史指标使用统一复权数据；
   - 实盘委托仍使用真实未复权价格。

2. 任何导致**股份数量变化**的企业行动：
   - symbol 进入 `CORPORATE_ACTION_HALT`；
   - 禁止新开T仓；
   - 重新查询 Broker Position；
   - 更新 CoreQty / T-Lot qty / entry_price / target_price 的等价经济口径；
   - 完成对账后方可恢复。

3. 禁止静默调整 T-Lot。

T-Lot调整必须写入 Audit Log，并记录：

```text
corporate_action_type
effective_date
pre_qty
post_qty
pre_entry_price
post_entry_price
adjustment_factor
```

---

# 8. 行情驱动方式

V1使用：

$$
5分钟K线
$$

而不是Tick。

策略事件：

```python
on_5m_bar(symbol, bar)
```

V1禁止：

```python
on_tick -> trade
```

Tick可以用于：

- 获取最新价；
- 获取委托价格；
- 滑点判断；

但不能直接生成交易信号。

---

# 9. Anchor定义

每日开盘前计算一次：

$$
Anchor=VWAP_{20}
$$

或数据不足时：

$$
Anchor=EMA_{20}
$$

V1优先：

```text
VWAP20
```

每日：

```text
09:xx PRE_MARKET
calculate anchor
freeze anchor
```

当天禁止动态漂移。

即：

```python
daily_anchor[symbol]
```

全天固定。

第二天重新计算。

---

# 10. ATR波动率

计算：

$$
ATR_{14}
$$

并标准化：

$$
ATR\%=\frac{ATR_{14}}{Close}
$$

网格宽度：

$$
G=
clip\left(
\max(
G_{min},
K_{ATR}\times ATR\%,
K_{cost}\times Cost
),
G_{min},
G_{max}
\right)
$$

建议初值：

```yaml
atr_period: 14
atr_k: 1.20

min_grid: 0.040
max_grid: 0.080

cost_multiple: 4.0
```

实际参数以后通过回测决定。

---

# 11. 几何网格

第$n$层买入线：

$$
Buy_n=Anchor(1-G)^n
$$

卖出参考线：

$$
Sell_n=Anchor(1+G)^n
$$

但**卖出T仓不直接依赖Anchor**。

T仓真正退出价格根据自身成本产生：

$$
ExitPrice=EntryPrice\times(1+G\times ExitMultiplier)
$$

建议：

```yaml
exit_multiple: 1.10~1.20
```

避免过小价差。

---

# 12. V1 ACCUMULATE模式

V1只有：

```text
ACCUMULATE
```

核心行为：

```text
价格下跌
    ↓
建立T仓
    ↓
反弹
    ↓
卖掉对应T仓
```

即：

```text
CORE 600
 ↓
BUY 100
 ↓
700
 ↓
SELL T 100
 ↓
600
```

严禁：

```text
600
 ↓
SELL CORE
 ↓
500
 ↓
等待低价买回
```

V1禁止这种“先卖后买”。

---

# 13. 新建T仓规则

同时满足以下条件才允许新开：

```text
strategy_enabled == true
mode == ACCUMULATE
state == IDLE
not EVENT_BLOCK
not VOLATILITY_HALT
not pending_order
open_t_lots < max_t_lots
position < target_qty
available_cash sufficient
```

价格触发：

$$
Price \le BuyLevel_n
$$

其中：

$$
n=OpenTLots+1
$$

---

# 14. 最大T仓约束

禁止无限补仓。

例如：

```yaml
t_unit: 100
max_t_lots: 2
```

则：

$$
MaxTPosition=200
$$

即：

```text
600
↓
700
↓
800
STOP
```

即使价格继续跌：

```text
不允许第三笔T仓
```

之后进入：

```text
T_CAPACITY_FULL
```

由长期战略模块或人工决策决定是否追加长期仓。

---

# 15. T仓退出

每个OPEN批次单独计算：

$$
Target_i=Entry_i(1+G_i\times ExitMultiplier)
$$

当：

$$
Price\ge Target_i
$$

进入：

```text
SELL_CANDIDATE
```

选择：

```text
LIFO
```

随后进行：

```text
Core Floor Check
Available Volume Check
Pending Order Check
Risk Check
```

全部通过才允许卖出。

---

# 16. T仓“失败”处理

V1禁止价格止损。

例如：

```text
430 BUY
↓
410
↓
390
```

不能自动：

```text
390 SELL
```

而应：

```text
OPEN
 ↓
超过异常条件
 ↓
SUSPENDED
```

再进入：

```text
REVIEW_REQUIRED
```

后续只能由人工/长期策略决定：

```text
KEEP
CONVERT_TO_STRATEGIC
EXIT_FOR_FUNDAMENTAL_REASON
```

T模块无权决定。

---


# 16.1 SUSPENDED批次审阅机制

`SUSPENDED` T-Lot 仍然占用 `max_t_lots` 容量。

禁止通过“忽略Suspended批次”继续新开T仓，从而形成变相无限补仓。

T-Lot增加：

```text
suspended_at
review_due_at
last_reviewed_at
review_reason
review_status
```

每日运行报告必须输出超期Review项。

人工允许的动作仅为：

```text
RESUME_T
KEEP_SUSPENDED
CONVERT_TO_STRATEGIC
MANUAL_EXIT
```

其中：

`CONVERT_TO_STRATEGIC` 和 `MANUAL_EXIT` 必须显式人工确认。

V1.1禁止按持有天数自动止损、自动转战略仓或自动摊薄。

---

# 17. Strategic Position与T Position隔离

这是整个架构的关键。

例如长期投资模块认为：

```text
腾讯410：战略加仓200股
```

则：

```text
StrategicLot
```

不能进入T-Lot Ledger。

即使后面：

```text
410 -> 440
```

T模块也不能自动卖。

所以必须明确：

```text
TRADE_REASON:
T_GRID
STRATEGIC_BUY
MANUAL
```

任何订单都有来源标签。

---

# 18. Order Tag

所有TGrid订单必须使用：

```text
strategy_name = "TGRID"
```

并设置唯一：

```text
order_remark
```

例如：

```text
TG_0700_B01
TG_0700_S01
```

V1不允许管理其他人工订单。

---


# 18.1 交易单位与最小价格变动

通用引擎不得假设所有证券都是100股一手。

每个symbol必须具备：

```yaml
lot_size:
price_tick:
```

并在配置校验时满足：

$$
tUnit \bmod lotSize = 0
$$

订单价格必须按 `price_tick` 合法化。

任何不合法的数量或价格：

```text
CONFIG_ERROR / ORDER_REJECTED
```

不得自动向不透明方向修正。

---


# 18.2 Order Intent 与订单幂等

V1.1新增生产级订单幂等设计。

任何报单必须遵循：

```text
Signal
 ↓
Risk Check
 ↓
Reserve Position / Cash
 ↓
DB Transaction:
    Create OrderIntent UUID
    State = READY_TO_SEND
COMMIT
 ↓
Broker.send()
 ↓
Record BrokerOrderId
```

禁止：

```text
先向券商报单
再把订单意图写入DB
```

否则程序在报单成功、DB写入前崩溃时可能重复报单。

每个 Order Intent 必须具有唯一：

```text
client_order_key
```

并写入：

```text
strategy_name
order_remark
```

重启恢复时必须通过：

```text
Broker Orders
+
Broker Trades
+
OrderIntent
```

进行匹配。

任何无法唯一匹配的订单：

```text
ORDER_RECONCILIATION_ERROR
→ SAFE_MODE
```

---
# 18.3 Position / Cash Reservation

为了防止并发订单透支底仓或现金，V1.1增加 Reservation。

### 卖出预留

$$
AvailableTQty
=
\min(
CanUseVolume,\,
Position-CoreQty
)
-
ReservedSellQty
$$

### 买入资金预留

$$
StrategyCashAvailable
=
BrokerAvailableCash
-
ReservedCash
-
MinimumCashBuffer
$$

创建 Order Intent 与 Reservation 必须处于**同一原子事务语义**中。

订单拒绝、撤销、确认失败后，Reservation必须按真实订单状态释放。

禁止基于“预计未成交”提前释放。

---

# 19. QMT Broker Adapter

统一封装：

```python
class Broker:
    query_asset()
    query_positions()
    query_position(symbol)
    query_orders()
    query_trades()

    place_buy(...)
    place_sell(...)

    cancel_order(...)
```

业务代码不得直接调用：

```python
xt_trader.order_stock(...)
```

必须全部经过：

```python
BrokerAdapter
```

---

# 20. MarketData Adapter

统一封装：

```python
class MarketData:
    subscribe(symbol)
    get_daily_bars(symbol, count)
    get_5m_bars(symbol, count)
    get_latest_quote(symbol)
```

底层使用：

```text
xtdata
```

策略层不得直接调用xtdata。

---

# 21. 启动对账 Reconciliation

每次程序启动：

```text
1. Connect QMT
2. Query Asset
3. Query Positions
4. Query Orders
5. Query Trades
6. Load SQLite
7. Reconcile
8. PASS后才启动策略
```

重点检查：

$$
BrokerPosition\stackrel{?}{=}LocalExpectedPosition
$$

如果不一致：

```text
SAFE_MODE
```

禁止下单。

---

# 22. Reconciliation原则

Broker永远是：

$$
\boxed{Position\ Source\ of\ Truth}
$$

SQLite永远是：

$$
\boxed{Strategy\ Intent\ Source\ of\ Truth}
$$

二者不允许静默修复。

例如：

```text
Broker = 700
DB expected = 600
```

系统不得自行认为：

```text
多出来100就是T仓
```

必须：

```text
RECONCILIATION_ERROR
```

等待人工确认。

---


# 22.1 人工交易与外部持仓变化检测

程序运行期间允许用户手工交易，但TGrid不得自动猜测其意图。

例如：

```text
Broker Position = 900
DB Expected      = 700
```

系统不得自动将多出的200股认定为：

```text
Strategic Position
```

必须进入：

```text
MANUAL_POSITION_CHANGE_DETECTED
→ symbol SAFE_MODE
```

等待人工分类：

```text
STRATEGIC
MANUAL
OTHER
```

完成显式确认和重新对账后才恢复自动交易。

---

# 23. Crash Recovery

必须支持：

```text
下单后程序崩溃
成交后程序未收到callback
电脑重启
MiniQMT重启
网络断开
```

恢复方式不能依赖callback历史。

启动后必须通过：

```text
orders
+
trades
+
positions
+
DB
```

重建状态。

因此：

> callback用于实时效率，不作为唯一事实来源。

---

# 24. 委托管理

V1采用限价委托。

状态：

```text
NEW
SUBMITTED
PARTIAL
FILLED
CANCEL_REQUESTED
CANCELED
REJECTED
UNKNOWN
```

必须支持部分成交。

例如：

```text
BUY 100
成交 60
剩余 40
```

不能直接建立：

```text
TLOT qty=100
```

必须按真实成交数量记录。

---

# 25. 委托超时与有限改价

配置：

```yaml
order_timeout_seconds: 120
max_reprice_attempts: 2
allow_chase: false
signal_valid_seconds: 600
```

超时：

```text
Cancel
↓
Query Order
↓
Query Trade
↓
Reconcile
```

禁止：

```text
Cancel之后立即认为未成交
```

必须重新查询实际状态。

### 买入T仓

默认原则：

> 买不到可以放弃，不追价。

### T仓退出

达到 `Target_i` 后可允许有限改价，但必须满足：

```text
price >= minimum_acceptable_exit
reprice_attempts <= max_reprice_attempts
```

超过允许次数后保持 T-Lot `OPEN`，等待下一次有效信号。

V1.1禁止无限追价与自动切换市价单。

---

# 26. Pending Order互斥

每个：

```text
symbol + direction
```

默认同时只允许一个有效策略委托。

例如已有：

```text
0700 BUY pending
```

不能再次：

```text
0700 BUY
```

防止行情callback重复触发造成重复下单。

---


# 26.1 Exchange Calendar 与时区

系统不得使用本机 `datetime.now()` 直接判断市场状态。

每个symbol必须关联交易所日历：

```text
SSE
SZSE
HKEX
```

策略时间统一转换为：

```text
exchange local time
```

必须识别：

```text
交易日
节假日
午休
半日市
停牌
异常闭市
```

---
# 26.2 Data Quality Guard

任何用于策略计算的行情数据必须检查：

```text
timestamp freshness
missing bars
stale quote
price validity
volume validity
suspension
duplicate bar
out-of-order bar
```

发现数据质量异常：

```text
DATA_HALT
```

禁止新开T仓。

不得使用过期行情继续触发网格。

---

# 27. 交易时间过滤

V1建议：

```yaml
skip_open_minutes: 15
skip_close_minutes: 15
```

开盘前15分钟：

```text
禁止新开T仓
```

收盘前15分钟：

```text
禁止新开T仓
```

已有T仓是否允许退出，可配置：

```yaml
allow_exit_near_close: true
```

---

# 28. Volatility Halt

定义：

$$
DailyMove>K_{halt}\times ATR\%
$$

例如：

```yaml
volatility_halt_atr: 2.5
```

或者：

$$
Gap > 2G
$$

则：

```text
VOLATILITY_HALT
```

当天禁止新开T仓。

目的：

> 区分正常波动和信息冲击。

---

# 29. Event Block

系统保留：

```yaml
event_block:
```

V1可以先人工配置，例如：

```yaml
events:
  0700.HK:
    - 2026-08-12
```

默认：

```yaml
block_before_days: 1
block_after_days: 1
```

V1不要求自动抓取财报日。

---

# 30. Kill Switch

必须支持全局：

```text
KILL_SWITCH
```

触发来源：

```text
CLI
config
exception
reconciliation error
QMT disconnect
position violation
database error
```

触发后：

```text
停止新下单
保留日志
查询当前订单
可选撤销TGrid挂单
```

不得自动平仓。

---

# 31. 状态机

全局：

```text
STARTUP
   ↓
CONNECTING
   ↓
RECONCILING
   ↓
READY
   ↓
RUNNING
```

异常：

```text
RUNNING
 ↓
SAFE_MODE
```

或：

```text
RUNNING
 ↓
HALTED
```

单证券：

```text
IDLE
 │
 ├── BUY_TRIGGER
 │       ↓
 │   BUY_PENDING
 │       ↓
 │      OPEN
 │       ↓
 │ SELL_TRIGGER
 │       ↓
 │ SELL_PENDING
 │       ↓
 │     CLOSED
 │
 ├── EVENT_BLOCK
 ├── VOLATILITY_HALT
 └── REVIEW_REQUIRED
```

---

# 32. 配置文件

建议：

```yaml
global:
  live_trading: false
  database: data/tgrid.db
  log_dir: logs
  bar_period: 5m
  order_timeout_seconds: 120
  skip_open_minutes: 15
  skip_close_minutes: 15
  volatility_halt_atr: 2.5

symbols:
  0700.HK:
    enabled: true
    mode: ACCUMULATE
    core_qty: 600
    target_qty: 1100
    t_unit: 100
    max_t_lots: 2
    anchor: VWAP20
    atr_period: 14
    atr_k: 1.20
    min_grid: 0.040
    max_grid: 0.080
    exit_multiple: 1.15

  000333.SZ:
    enabled: false
    mode: ACCUMULATE
    core_qty: 0
    target_qty: 5300
    t_unit: 100
    max_t_lots: 2
    anchor: VWAP20
    atr_period: 14
    atr_k: 1.20
    min_grid: 0.035
    max_grid: 0.070
    exit_multiple: 1.15
```

注意：配置文件中的示例数量**仅用于当前验证**，策略代码绝不能写死腾讯或美的。

---

# 33. 推荐目录结构

```text
tgrid/
│
├─ pyproject.toml
├─ README.md
│
├─ config/
│  ├─ config.example.yaml
│  └─ config.local.yaml
│
├─ src/tgrid/
│  ├─ main.py
│  ├─ config.py
│  ├─ models.py
│  ├─ adapters/
│  ├─ strategy/
│  ├─ risk/
│  ├─ position/
│  ├─ execution/
│  ├─ persistence/
│  └─ reporting/
│
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  ├─ scenarios/
│  └─ fixtures/
│
├─ scripts/
│  ├─ check_qmt.py
│  ├─ reconcile.py
│  └─ dry_run.py
│
├─ docs/
│  ├─ DESIGN.md
│  ├─ GATES.md
│  └─ OPERATIONS.md
│
└─ data/
   └─ .gitkeep
```

`data/`、真实配置、日志、账号信息不得提交Git。

---

# 34. 关键软件不变量

以下全部必须变成自动测试：

### INV-001 Core Floor

$$
PositionAfterSell\ge CoreQty
$$

### INV-002 T Capacity

$$
OpenTLots\le MaxTLots
$$

### INV-003 Target Ceiling

T模块不得主动使：

$$
Position>TargetQty
$$

### INV-004 Unique Order

单证券单方向不得存在重复策略挂单。

### INV-005 Broker Authority

实际持仓只认Broker。

### INV-006 No Silent Reconcile

持仓不一致禁止自动修复。

### INV-007 No Auto Stop Loss

ACCUMULATE T仓禁止价格止损。

### INV-008 No Core Lot Exit

Strategic/Core Lot禁止T模块退出。

### INV-009 Live Default OFF

没有明确开启：

```text
live_trading=true
```

绝不调用真实下单接口。

### INV-010 Fail Closed

任何未知异常：

```text
禁止新单
```

而不是继续运行。

---


## INV-011 No Assert Safety

生产风控不得依赖 Python `assert`。

## INV-012 Reservation Safety

任何有效 Order Intent 必须先占用对应：

```text
ReservedSellQty / ReservedCash
```

## INV-013 Idempotent Order Intent

同一 `client_order_key` 不得生成两个独立真实报单意图。

## INV-014 Callback Isolation

QMT callback不得直接修改策略状态或报单。

## INV-015 Corporate Action Safety

检测到股份数量变化企业行动时，必须进入 `CORPORATE_ACTION_HALT` 直至重新对账。

## INV-016 Manual Change Detection

未知人工/外部持仓变化必须进入 SAFE_MODE，不得静默归类。

## INV-017 Data Freshness

过期或异常行情不得触发新订单。

---

# 35. 开发Gate体系

Claude不得一次性实现全部系统。

必须按以下Gate推进。

## GATE 0 — 项目骨架

实现：

```text
目录结构
pyproject
配置读取
数据模型
logging
SQLite初始化
CLI
Event Queue骨架
显式Risk Exception类型
lot_size / price_tick配置校验
```

禁止QMT下单代码。

### 必测

```text
config validation
DB migration
logging
startup/shutdown
invalid config
```

### Gate 0验收

必须提交：

```text
docs/GATE_0_REPORT.md
```

包含：

```text
实施内容
文件列表
测试命令
测试结果
已知问题
下一Gate建议
```

**未获得总设计师PASS，不进入Gate 1。**

---

# 36. GATE 1 — QMT只读接入

只允许：

```text
连接QMT
读取行情
读取账户
读取持仓
读取委托
读取成交
读取/验证企业行动或复权数据能力
验证交易所日历/交易时段
验证行情新鲜度字段
```

禁止：

```text
order_stock
cancel_order
```

### 验收指标

真实MiniQMT环境下：

```text
连接成功
行情成功
资产成功
持仓成功
委托成功
成交成功
断线能识别
```

---

# 37. GATE 2 — Position + Ledger + Reconciliation

实现：

```text
Core Position Manager
T-Lot Ledger
Audit Log
Reconciliation
Crash Recovery
SAFE_MODE
OrderIntent
client_order_key
ReservedSellQty
ReservedCash
人工交易检测
Corporate Action状态模型
Suspended Review字段
```

完全不实现交易信号。

核心场景测试至少包括：

```text
Broker=600 DB=600 → PASS
Broker=700 DB expects600 → SAFE_MODE
Broker=600 DB expects700 → SAFE_MODE
DB损坏 → HALT
重复TLot → ERROR
程序崩溃重启 → 能恢复
```

---

# 38. GATE 3 — 策略算法离线模拟

实现：

```text
ATR14
VWAP20
统一复权口径
Adaptive Grid
ACCUMULATE
LIFO
Max T Lots
Volatility Halt
Event Block
Data Quality Guard
Corporate Action指标连续性测试
```

使用历史K线/合成数据。

禁止连接真实交易接口。

必须覆盖：

### Scenario A

```text
440 -> 420 -> 445
```

预期：

```text
BUY T
SELL T
CORE unchanged
```

### Scenario B

```text
440 -> 420 -> 400
```

预期：

```text
2 T lots max
then stop
```

### Scenario C

```text
440 -> 400 gap
```

预期：

```text
VOLATILITY_HALT
```

### Scenario D

```text
T仓存在 + Core Floor不足
```

预期：

```text
SELL rejected
```

---

# 39. GATE 4 — Execution Dry Run

建立：

```text
SimBroker
```

完整跑：

```text
行情
→信号
→订单
→部分成交
→成交
→T-Lot
→卖出
→PnL
```

必须模拟：

```text
reject
partial fill
timeout
cancel failure
limited reprice
duplicate callback
out-of-order callback
concurrent buy/sell intent
reserved cash conflict
reserved sell conflict
crash after broker send before local broker_order_id write
restart
disconnect
```

目标：在没有真实资金的情况下，把交易执行系统打穿。

---

# 40. GATE 5 — QMT真实接口但禁止报单

连接真实QMT：

```text
MarketData = REAL
BrokerQuery = REAL
Execution = SHADOW
```

系统生成：

```text
WOULD_BUY
WOULD_SELL
```

但绝不下单。

至少连续运行：

$$
5个完整交易日
$$

输出：

```text
Shadow Orders
Signal Log
Reconciliation Report
Daily Report
```

只有全部一致才允许进入Gate 6。

---

# 41. GATE 6 — 极小真实资金验证

这是第一次允许真实订单。

初期只能：

```text
1 symbol
1 t_unit
max_t_lots = 1
```

例如：

```text
100股
```

禁止：

```text
多个股票
多TLot
自动Strategic Buy
```

必须人工：

```text
live_trading=true
```

并再次确认。

Gate 6重点验证：

```text
真实成交
部分成交
成交回调
实际费用
撤单
T+1/can_use_volume
港股通订单行为
程序重启
```

---

# 42. GATE 7 — V1正式运行

允许：

```text
多个配置证券
max_t_lots <= 2
ACCUMULATE only
per-symbol max_t_capital
global minimum_cash_buffer
```

仍禁止：

```text
NEUTRAL
DISTRIBUTE
自动正T
动态CoreQty
AI预测
```

V1稳定运行足够长时间以后，再讨论V2。

---

# 43. Gate Review流程

Claude每个Gate结束以后，只允许提交：

```text
代码
测试
Gate Report
```

不得自行继续下一Gate。

总设计师Review顺序：

```text
1. Architecture Review
2. Code Review
3. Invariant Review
4. Test Review
5. Failure Injection Review
6. PASS / CONDITIONAL PASS / FAIL
```

结果只有三种：

```text
PASS
CONDITIONAL_PASS
FAIL
```

只有：

```text
PASS
```

才进入下一Gate。

---

# 44. Claude开发纪律

1. 不得跨Gate实现。
2. 不得为了“代码更简洁”删除风险保护。
3. 不得自己改变策略数学定义。
4. 发现设计矛盾时必须 `STOP / WRITE ISSUE`，不得自行猜测。
5. 所有外部依赖必须说明用途。
6. QMT调用全部封装在Adapter层。
7. 交易算法必须能脱离QMT进行Unit Test。
8. 任何真实下单路径必须经过 `RiskEngine`。
9. 任何卖出必须经过 `CoreFloorGuard`。
10. 默认 `LIVE_TRADING = FALSE`。

---

# 45. Claude每Gate报告模板

```markdown
# Gate X Implementation Report

## 1. Scope
本Gate实现内容。

## 2. Files Changed
文件与目的。

## 3. Architecture Decisions
重要实现决定。

## 4. Deviations
与DESIGN.md不同的地方。
若无写 NONE。

## 5. Tests
测试名称、命令、结果。

## 6. Invariants
逐项说明涉及的不变量是否通过。

## 7. Failure Injection
模拟过哪些错误。

## 8. Known Issues
未解决问题。

## 9. Manual Verification
需要人工检查事项。

## 10. Gate Recommendation
READY_FOR_REVIEW / NOT_READY
```

---

# 46. 每日运行报告

```text
Date
Account Equity
Available Cash
Symbol
Core Qty
Strategic Qty
T Qty
Broker Qty
Anchor
ATR
Grid %
Buy Levels
Open T Lots
Target Prices
Orders
Trades
Realized T PnL
Fees
Net T PnL
T Capital Used
T Return
Core Floor Violations = 0
Warnings
Errors
Next Day State
```

---

# 47. 长期绩效指标

不要以胜率为主要指标。

核心指标：

$$
T\ Enhancement=
\frac{NetTProfit}{AverageCoreMarketValue}
$$

以及：

$$
TCapitalReturn=
\frac{NetTProfit}{AverageTCapitalUsed}
$$

还必须记录：

```text
Max T Capital
Average Holding Days
Median Holding Days
Open T Lots
Stuck > 20d
Stuck > 60d
Core Violation
Reconcile Failure
Order Failure
```

---

# 48. 成功标准

TGrid V1成功不是：

```text
胜率90%
```

而是：

```text
Core Violation = 0
Unknown Position = 0
Duplicate Order = 0
Unreconciled Trade = 0
Unexpected Live Order = 0
```

并且：

$$
NetTProfit>0
$$

长期目标：

$$
AnnualEnhancement\approx1\%\sim3\%
$$

但安全性指标拥有绝对优先级。

---

# 49. V2暂定方向

V1稳定后才考虑：

```text
NEUTRAL模式
DISTRIBUTE模式
先卖后买正T
趋势过滤
多时间尺度Anchor
估值输入
跨股票资金调度
组合风险预算
动态T Unit
Covered Call联动
策略参数自动回测
```

全部不属于当前开发范围。

---

# 50. 最重要的四个模块

整个系统无论将来增加多少功能，都不能破坏这四层：

$$
\boxed{CorePositionGuard}
$$

$$
\boxed{TLotLedger}
$$

$$
\boxed{AdaptiveGrid}
$$

$$
\boxed{RiskStateMachine}
$$

其中：

> **CorePositionGuard 是最高优先级。**

任何策略收益优化都不能绕开它。

---

# 51. Claude第一条执行指令

Claude当前只执行：

## GATE 0

实现：

```text
项目骨架
配置系统
核心数据模型
SQLite schema
日志
CLI
Event Queue骨架
显式Risk Exception类型
lot_size / price_tick配置校验
基础测试
```

明确禁止：

```text
QMT连接
行情
下单
策略计算
真实账号访问
```

完成后生成：

```text
docs/GATE_0_REPORT.md
```

然后停止。

等待架构Review。

---

# 52. 总设计原则

整个项目坚持：

$$
\boxed{先证明不会出错}
$$

然后：

$$
\boxed{再证明策略可以赚钱}
$$

最后才是：

$$
\boxed{扩大资金与标的}
$$

顺序绝不能反过来。


---

# 53. V1.1 修订说明

V1.1基于外部架构审计与总设计复核，在不改变V1核心策略原则的前提下，新增以下生产级要求：

1. **Corporate Action Policy**
   - 区分 RAW_PRICE 与 ADJUSTED_PRICE；
   - 统一历史指标复权口径；
   - 股份数量变化触发 `CORPORATE_ACTION_HALT`。

2. **Callback Isolation / Single Event Queue**
   - QMT回调只入队；
   - 唯一事件线程负责状态变更与报单。

3. **显式Core Floor风控**
   - 禁止使用 Python `assert` 作为生产风控。

4. **OrderIntent + Idempotency**
   - 先持久化订单意图，再真实报单；
   - 使用唯一 `client_order_key`；
   - 支持崩溃恢复和重复报单防护。

5. **Position / Cash Reservation**
   - 新增 `ReservedSellQty`、`ReservedCash`；
   - 防止并发信号透支底仓或现金。

6. **人工交易检测**
   - 未知持仓变化触发 symbol `SAFE_MODE`；
   - 禁止自动猜测为Strategic仓。

7. **有限改价执行策略**
   - 买不到可放弃；
   - T仓退出允许有限改价；
   - 禁止无限追价和自动市价单。

8. **Suspended Review SLA**
   - Suspended批次继续占用T容量；
   - 必须进入人工Review流程。

9. **交易单位与价格步长**
   - 每symbol配置 `lot_size`、`price_tick`；
   - 禁止策略代码写死100股。

10. **交易日历、时区、数据质量**
    - 使用交易所本地时间；
    - 检查缺失、过期、重复、乱序行情；
    - 异常进入 `DATA_HALT`。

11. **多标的资金安全**
    - V1不做跨证券最优配置；
    - 但必须支持 `minimum_cash_buffer` 和 `max_t_capital`。

V1.1仍保持以下核心边界不变：

```text
ACCUMULATE only
先买后卖
Core Position不可卖
Max T Lots有限
不自动价格止损
不自动基本面判断
Gate 5以前不真实报单
默认 LIVE_TRADING=false
```
