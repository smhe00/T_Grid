# TGrid

**TGrid 是一个面向 MiniQMT / XtQuant 的低频做 T 交易引擎。**

它的目标不是替代长期投资，也不是做高频网格，而是在**明确保护长期核心持仓（Core Position）**的前提下，用小批量、低频的“先买后卖”交易尝试获取额外的波动收益。

> 设计目标：`长期核心持仓收益 + 低频波动交易增厚`。设计文档给出的收益增强目标约为 **1%–3%/年**，这是系统设计目标，不是收益承诺。

## 适合什么场景

TGrid 更适合这样的使用方式：你已经有一只准备长期持有的股票，希望长期底仓不被交易程序破坏，同时允许系统在价格波动中额外买入少量 T 仓，反弹后再卖出对应 T 仓。

V1 使用 `ACCUMULATE` 模式：**先买后卖**。它不做裸卖、不做高频、不做盘口预测、不用机器学习猜涨跌，也不会自动改变你的长期 `core_qty`。

一个典型例子：

```text
长期持仓 5,000 股
│
├─ Core Position 4,000 股   ← TGrid 永远不能主动卖出
│
└─ 可用于低频做 T 的空间
      ↓
价格相对 Anchor 下跌到触发区间
      ↓
额外买入 100 股 T-Lot
      ↓
价格反弹达到退出条件
      ↓
卖出这 100 股 T-Lot
```

系统的优先级始终是：

```text
安全性 > 底仓完整 > 状态一致性 > 交易收益 > 交易频率
```

## TGrid 会帮你做什么

TGrid 已经具备从策略判断到安全执行的完整基础链路，包括：

- 为每只证券维护 `core_qty / target_qty / t_unit / max_t_lots` 等约束；
- 使用 VWAP、ATR 等信息形成低频买入间距和退出价格；
- 维护每一笔 T-Lot，并区分长期 Core Position 与临时 T 仓；
- 在卖出前检查 Core Floor、可用持仓、T+1/可卖量和 reservation；
- 在买入前检查资金、单笔上限、当日风险和共享资金占用；
- 对订单做持久化、幂等、部分成交、撤单、重启恢复和异常状态处理；
- 多个独立策略进程使用同一账户时，共享账户级资金保护；
- 同一账户、同一证券存在未解决订单时，阻止第二个策略重复进入；
- 出现 `UNKNOWN / CANCEL_REJECTED / QUARANTINED` 等不确定状态时 fail closed，而不是盲目重发订单。

底层安全执行由独立的 [`qmt-execution-core`](https://github.com/smhe00/qmt-execution-core) 负责；TGrid 主要负责策略、持仓模型、业务风险和 T-Lot 账本。

## 当前状态

截至 **2026-08-17**：

```text
Gate 0–5        已完成并审计
Core 0.4.1      已完成独立审计并锁定
TGrid Iter16    PASS_PRELIVE
Gate 6          已获得“模拟盘单笔闭环”授权
真实/实盘交易    未授权
live_trading_allowed = false
```

当前 Gate-6 授权只允许 **QMT simulation** 环境中的受控验证：默认 `510300.SH`、单笔 100 股 BUY、有限资金上限，完成查询 / 必要时撤单 / reconcile 后结束。它**不等价于实盘授权**。

仓库采用显式 Gate 控制。真正的当前授权范围以 [`work/control/CURRENT_TASK.md`](work/control/CURRENT_TASK.md) 和 [`work/control/WORKFLOW_STATE.yaml`](work/control/WORKFLOW_STATE.yaml) 为准，而不是以历史 README 或旧 Gate 文档为准。

## 快速开始

### 1. 安装

要求 Python `>=3.9`。

```bash
pip install -e .
python -m tgrid --help
```

### 2. 建立自己的配置

从示例开始：

```text
config/config.example.yaml
        ↓ 复制并修改
config/config.local.yaml
```

真实本地配置不要提交到 Git。

最重要的几个参数是：

| 参数 | 用户含义 |
|---|---|
| `core_qty` | 长期底仓硬下限，TGrid 不得主动卖穿 |
| `target_qty` | 该证券长期计划持仓上限 |
| `t_unit` | 每次低频做 T 的交易单位 |
| `max_t_lots` | 同时最多允许存在多少个 T 批次 |
| `max_t_capital` | 用于 T 仓的资金上限 |
| `anchor` | 价格基准，目前主要使用 VWAP20 |
| `min_grid / max_grid` | 做 T 的最小 / 最大价格间距 |
| `exit_multiple` | T-Lot 反弹退出条件相关参数 |

示例配置中的证券、数量和资金都只是示例，程序不会写死具体股票或持仓。

### 3. 先跑本地 Preflight

```bash
python -m tgrid preflight \
  --config config/config.local.yaml \
  --database data/tgrid.db \
  --log logs/preflight.jsonl
```

Preflight 只验证配置、本地 SQLite 和日志等基础条件，**不会连接 QMT，也不会产生交易**。

### 4. 在接入交易前先使用 Shadow / 模拟验证

推荐顺序：

```text
配置检查
  ↓
离线策略 / Dry Run
  ↓
Shadow（只产生 WOULD_BUY / WOULD_SELL）
  ↓
QMT Simulation Gate-6
  ↓
独立审计
  ↓
之后才讨论实盘授权
```

Shadow 运行说明见 [`work/gates/GATE_5/GATE5_RUNBOOK.md`](work/gates/GATE_5/GATE5_RUNBOOK.md)。

当前 Gate-6 simulation runner：

```bash
python scripts/gate6_sim_negative.py --help
python scripts/gate6_sim_live.py --help
```

Gate-6 positive runner 只用于已经完成本地 MiniQMT simulation 配置、账户 binding 和 Runtime Authority 初始化后的受控验证。第一次使用某个账户的 shared runtime 时，需要由 operator 显式初始化 Runtime Authority；普通策略进程不会自动创建或替换账户 coordination DB。

## 多策略 / 多账户时会发生什么

TGrid 支持一个账户运行多个独立策略进程，也支持多个账户。账户之间的协调数据彼此独立。

对于同一个账户：

```text
Strategy A ─┐
Strategy B ─┼─→ 同一 Account Runtime Authority
Strategy C ─┘           ↓
                 该账户唯一的 coordination DB
                    ├─ symbol claim
                    └─ shared BUY cash reservation
```

因此同一账户的不同证券可以并行执行，但同一证券存在 unresolved lifecycle 时不会被两个策略同时操作。BUY 资金也按账户共享，而不是每个策略各自假设自己拥有整笔现金。

Runtime Authority 会认证该账户对应 coordination DB 的 canonical path、`db_uuid` 和 `authority_id`。如果 DB 被误删后在原路径重新创建、身份不一致或 Authority 损坏，runtime 会拒绝启动，而不是静默采用一份新的空数据库。

## 数据和安全边界

TGrid 的安全原则不是“出错后尽量继续交易”，而是**无法确认时停止自动交易**。

需要特别注意：

- `core_qty` 应由用户根据自己的长期投资计划明确设置；TGrid 不替你决定长期仓位。
- 真实配置、账户信息、本地 QMT 路径和交易数据库不要提交到仓库。
- 不要手工删除或替换 Runtime Authority / coordination DB 来“解决”启动错误；应先查明是否存在 unresolved order / reservation。
- `UNKNOWN` 或其他 broker reality 不明确的状态需要 reconciliation，不能简单重启后再下一单。
- README 只说明使用方式，任何带 broker side effect 的验证仍受 Gate 控制文件约束。

## 我只想了解策略原理

完整策略与风险模型见：

- [`TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md`](TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md)

其中重点包括 Core Position、T-Lot、Anchor、ATR 自适应 Grid、数据质量、Corporate Action、Reservation、订单幂等和异常恢复。

## 我是开发者

README 不再展开类级 API、异常层级、SQLite migration、状态机和 Gate 审计细节。

开发、修改执行链路或做独立审计，请从：

> **[`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md)** 开始。

该文档会进一步指向总体设计、Gate 说明、当前任务/状态、测试入口以及公共 `qmt-execution-core`。

## 项目定位

TGrid 的核心原则可以压缩成一句话：

> **长期仓位由投资逻辑决定；TGrid 只负责在不破坏长期仓位的条件下，谨慎地利用短期波动。**
