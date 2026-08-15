# TGrid

QMT 低频做 T 交易引擎（开发中）。

> **当前状态：Gate 0–5 已通过（离线）。** 本仓库已有配置、风险异常、SQLite 持久化（migration
> 1–5：bootstrap / t_lot_ledger / t_lot_audit_log / order_intents / order_reservations）、
> 只读 QMT Adapter 边界（Gate 1）、Position + Ledger + Reconciliation（Gate 2）、离线策略算法
> （Gate 3）、Execution Dry Run（Gate 4）、Shadow 模式（Gate 5）。**没有任何真实下单能力**：
> 执行层只通过注入的 SimBroker 干跑，Shadow 只产出 WOULD_BUY/WOULD_SELL；
> `live_trading_allowed=false`，真实 QMT 接入需人工执行 Gate 6/7（见
> `work/gates/GATE_6/GATE67_MANUAL_CHECKLIST.md`）。

## 已实现（G0 / G1 / G2 / G3 / G4 / G5）

- `tgrid.config.load_config(path)`：从调用方显式传入的 YAML 路径读取并校验配置，返回有类型的 `RootConfig`。
- 配置数据模型（`GlobalConfig` / `SymbolConfig` / `RootConfig`），全部为不可变 dataclass。
- 显式风险异常类型（`ConfigError`、`RiskError`、`CoreFloorViolation`、`InsufficientAvailableVolume`、`SellReservationConflict`、`CashReservationConflict`）。
- 严格 fail-closed 校验：未知字段、缺失必填字段、错误根结构、非法类型/范围、bool 冒充整数、NaN/Infinity 都会被拒绝。
- 示例配置 `config/config.example.yaml`（仅含 `0700.HK` 与 `000333.SZ` 示例数量，代码不写死任何证券或数量）。
- `tgrid.persistence`（SQLite 基础，仅标准库 `sqlite3`）：显式路径打开、`PRAGMA foreign_keys=ON`、`busy_timeout`、完整性检查、有序事务化幂等 migration、schema 版本一致性校验，以及 `PersistenceError` / `DatabaseOpenError` / `DatabaseIntegrityError` / `SchemaVersionError` / `MigrationError` 异常。当前只有 `schema_migrations` 与 `application_metadata` 两张基础表，不含任何交易领域表。
- `tgrid.reporting`（结构化 JSONL 日志，仅标准库）：`configure_jsonl_logger(name, path)` 显式路径配置、`emit(logger, event, message, level, context)` 写入单行可解析 JSON、`shutdown_logger(name)` 幂等关闭。输出 UTF-8 JSONL（`schema_version`/`timestamp`/`level`/`logger`/`event`/`message`/`context`），中文/换行/引号无损 round-trip；配置/序列化/写入失败抛 `LoggingError` / `LoggingConfigError` / `LoggingEmitError`，不静默吞错、不留半行。
- `tgrid.events`（单消费者 Event Queue 骨架，仅标准库）：线程安全、容量有界、FIFO、单 worker 的 `EventQueue`，生命周期 `NEW → RUNNING → STOPPING → STOPPED`（handler 抛异常 → `FAILED`）。非阻塞 `enqueue`（满队列抛 `EventQueueFull`）、graceful `stop` + drain、有界 `join`、`raise_if_failed()`。异常：`EventQueueError` / `EventQueueConfigError` / `EventQueueLifecycleError` / `EventQueueFull` / `EventQueueWorkerError`。为后续 QMT callback 隔离提供线程边界，不含 QMT/策略/订单能力。
- `tgrid.adapters.qmt_readonly`（只读 Trader Adapter 边界，G1-T002）：`ReadOnlyTraderAdapter` + `ReadOnlyTraderState`，只接受依赖注入 client、只调用固定只读方法，显式状态机与安全异常；无通用转发、无 order/cancel 面、不 import XtQuant。异常：`QmtReadOnlyError` / `QmtAdapterConfigError` / `QmtAdapterLifecycleError` / `QmtConnectionError` / `QmtQueryError`。
- `tgrid.adapters.marketdata_readonly`（只读 MarketData 查询 Adapter 边界，G1-T003）：`ReadOnlyMarketDataAdapter`，构造时冻结 8 个固定只读查询 callable，参数先校验（失败抛 `MarketDataValidationError` 且不调用底层）、序列参数单次快照、外部异常安全转 `MarketDataQueryError`（cause/context 干净）；无订阅/下载/连接/账号/交易面、不 import XtQuant。异常：`MarketDataReadOnlyError` / `MarketDataAdapterConfigError` / `MarketDataValidationError` / `MarketDataQueryError`。
- `tgrid.adapters.quote_subscription_readonly`（单路 Quote Subscription 只读生命周期 Adapter，G1-T004）：`ReadOnlyQuoteSubscriptionAdapter` + `QuoteSubscriptionState`，每实例最多一个 `subscribe_quote` 订阅、`unsubscribe_quote` 至多一次清理，显式状态/sequence id/failure_type；参数验证（`QuoteSubscriptionValidationError`）、外部异常安全转 `QuoteSubscriptionError` 层级（cause/context 干净）；无 download/query/account/connect/order/cancel、不执行 callback、不 import XtQuant。异常：`QuoteSubscriptionError` / `QuoteSubscriptionConfigError` / `QuoteSubscriptionValidationError` / `QuoteSubscriptionLifecycleError` / `QuoteSubscriptionStartError` / `QuoteSubscriptionStopError`。
- `tgrid.probes.gate1_readonly`（Gate 1 只读集成探针编排器，G1-T005）：`run_gate1_readonly_probe` 按固定顺序组合 `ReadOnlyTraderAdapter` + `ReadOnlyMarketDataAdapter` 的 15 个只读操作并 `trader.stop()` 至多一次，返回 `Gate1ReadOnlyProbeSummary`（固定 operation name tuple + cleanup 布尔，无业务数据）；精确类型校验、失败/清理安全异常（cause/context 干净）、BaseException 先清理后传播。异常：`Gate1ProbeError` / `Gate1ProbeConfigError` / `Gate1ProbeExecutionError`。
- `tgrid.integrations.qmt_gate1_runtime`（Gate 1 只读 XtQuant Runtime Bridge，G1-T006）：生产 `src/tgrid` 中唯一授权 importlib 延迟加载 XtQuant 的模块；Trader bridge 只暴露 8 个已批准 callable，账号按 SHA-256 指纹内存匹配，无 order/cancel 面。
- `tgrid.position`（Gate 2，离线）：`PositionSnapshot`（Broker = Core + Strategic + OpenT 不可变分解）、`CorePositionGuard` 三重卖出保护（Core Floor → CanUseVolume → Reservation，INV-001/005）、`snapshot_from_symbol_config`（Core 唯一来自 SymbolConfig）、`reconcile_position`（broker<core → CORE_FLOOR_BREACH 优先；其它非零 delta → BROKER_POSITION_MISMATCH；相等 → MATCH，禁止静默修复 INV-006）。
- `tgrid.persistence`（Gate 2/4，SQLite，仅标准库）：migration 1–5。`t_lots`（§6 + §16.1 suspended review 字段，禁删触发器）、`t_lot_audit_log`（追加式，UPDATE/DELETE 双禁，FK 到 t_lots）、`order_intents`（§18.2 client_order_key 幂等 + §24 状态）、`order_reservations`（§18.3 ReservedSellQty/ReservedCash）。行为化 schema 验证（列结构/CHECK/FK/触发器/约束探针）全部在 `initialize` 中 fail-closed 执行。
- `tgrid.persistence.t_lot_writer`（G2-T004）：`transition_t_lot_status` — `BEGIN IMMEDIATE` 单事务 CAS status + 追加一条 audit，all-or-nothing；BaseException 覆盖 rollback。
- `tgrid.persistence.t_lot_transition_policy`（G2-T005）：五边闭集 `resolve_t_lot_transition` / `apply_t_lot_transition`，未批准组合零 DB 写入；人工/no-op 动作显式不可执行。
- `tgrid.strategy`（Gate 3，离线策略算法，design §38）：`Bar`/`SessionWindow`、`vwap20`/`ema20`/`atr14`/`atr_pct`、`grid_pct`（G=clip(max(G_min,K_ATR×ATR%),G_min,G_max)）、`buy_level`（Buy_n=Anchor(1-G)^n）、`exit_target_price`、`legalize_price`（price_tick 合法化，Decimal 精确）、`PriceBasis`/`CorporateActionFactor`/`adjust_historical_prices`（§7.1 统一复权口径）、`DataQualityGuard`（§26.2 七类问题→DATA_HALT）、`volatility_halt`/`EventBlockRule`（§28/§29）、`AccumulateStrategy`（§12–§16/§31：每日冻结 Anchor、5m bar 决策流、LIFO、max_t_lots、target_qty 上限、挂单互斥、卖出门复用 Gate 2 CorePositionGuard）。设计 §38 场景 A-D 全部通过。
- `tgrid.execution`（Gate 4，Execution Dry Run，design §39）：`ExecutionStore`（意图+预留原子事务）、`SimBroker`（确定性 FILL/PARTIAL/REJECT/TIMEOUT/CANCEL_FAIL/断线）、`ExecutionEngine`（意图先写后报单 INV-013、预留冲突门 §18.3、poll tick-then-read、timeout→cancel→re-query→reconcile §25、实际成交价回填 §24）、`reconcile_open_intents`（MATCHED/INTENT_ONLY/UNMATCHED_BROKER_ORDER，§23 崩溃恢复）、`DryRunHarness`（行情→信号→订单→成交→T-Lot→卖出→PnL 全链路）。§39 失败矩阵全部覆盖。
- `tgrid.shadow`（Gate 5，Shadow 模式，design §40）：`ShadowEngine` 产出 **WOULD_BUY/WOULD_SELL**（绝无券商调用面，INV-009）、Signal Log、Shadow vs Broker 对账、Daily Report，`build_shadow_reports` 组装四份 §40 交付物。真实 QMT 5 交易日影子运行见 `work/gates/GATE_5/GATE5_RUNBOOK.md`。

## 只读 QMT Adapter 边界（G1-T002）

```python
from tgrid import ReadOnlyTraderAdapter

adapter = ReadOnlyTraderAdapter(client)   # client 是注入的只读交易 client
adapter.start()                           # NEW -> STARTED
adapter.connect()                         # 仅 STARTED 允许；返回 int 0 才进入 CONNECTED
adapter.subscribe(account)                # 仅 CONNECTED 允许；int 0 成功
asset = adapter.query_asset(account)      # 仅 CONNECTED 允许
positions = adapter.query_positions(account)
orders = adapter.query_orders(account, cancelable_only=False)
trades = adapter.query_trades(account)
adapter.stop()                            # 幂等；FAILED 后按需清理恰好一次
```

- Adapter 只调用注入 client 的固定只读方法（`start`/`connect`/`subscribe`/`query_stock_asset`/
  `query_stock_positions`/`query_stock_orders`/`query_stock_trades`/`stop`）。
- 状态机 `NEW → STARTED → CONNECTED → STOPPED`（外部失败 → `FAILED`），start 幂等、失败后禁止
  restart、stop 幂等且 FAILED 后可清理一次。
- 外部异常全部转安全项目异常：`QmtReadOnlyError` / `QmtAdapterConfigError` /
  `QmtAdapterLifecycleError` / `QmtConnectionError` / `QmtQueryError`，只含操作名与异常类型，
  不泄漏原 message/repr/traceback；`KeyboardInterrupt`/`SystemExit`/`GeneratorExit` 先标记 FAILED
  再原样传播。
- **安全边界**：无 `__getattr__`、无通用转发、无 `client` property、无任何 order/cancel/改单方法；
  注入 client 不暴露为公共属性。本模块**不 import XtQuant、不连接 QMT、不读行情/账号**，全部测试
  只用 fake client 离线完成。

## 只读 MarketData 查询 Adapter 边界（G1-T003）

```python
from tgrid import ReadOnlyMarketDataAdapter

adapter = ReadOnlyMarketDataAdapter(client)   # client 是注入的只读行情/参考数据查询 client
tick = adapter.get_full_tick(["600000.SH", "000001.SZ"])
md = adapter.get_market_data(
    ["close", "volume"], ["600000.SH"], "1d",
    start_time="20260801", end_time="20260814",
    count=-1, dividend_type="none", fill_data=True,
)
detail = adapter.get_instrument_detail("600000.SH")
divs = adapter.get_divid_factors("600000.SH", start_time="20260101", end_time="20260814")
calendar = adapter.get_trading_calendar("SH", start_time="20260801", end_time="20260814")
dates = adapter.get_trading_dates("SH", start_time="20260801", end_time="20260814", count=-1)
period = adapter.get_trading_period("600000.SH")
```

- Adapter 只调用构造时冻结的 8 个固定只读 callable（`get_full_tick` / `get_market_data(_ex)` /
  `get_instrument_detail` / `get_divid_factors` / `get_trading_calendar` / `get_trading_dates` /
  `get_trading_period`），不提供订阅、下载、连接、账号或交易能力。
- 每个查询方法先做参数校验（序列/非空字符串/字符串/bool/`count∈{-1,正整}`），校验失败抛
  `MarketDataValidationError`（只含参数名与预期类型），且**不调用任何底层方法**；序列参数传给底层前
  会复制，底层 mutation 不反向污染调用方容器。
- 外部异常全部转安全项目异常：`MarketDataReadOnlyError` / `MarketDataAdapterConfigError` /
  `MarketDataValidationError` / `MarketDataQueryError`，`__cause__`/`__context__` 均为 None，
  不泄漏原异常对象/参数值/client repr；`KeyboardInterrupt`/`SystemExit`/`GeneratorExit` 原样传播。
- **安全边界**：无 `__getattr__`、无通用转发、无 `client` property；构造后替换 client 属性不可绕过
  冻结映射。本模块**不 import XtQuant、不连接 QMT、不订阅/下载行情**，全部测试只用 fake client
  离线完成。

## 单路 Quote Subscription 只读生命周期 Adapter（G1-T004）

```python
from tgrid import ReadOnlyQuoteSubscriptionAdapter

adapter = ReadOnlyQuoteSubscriptionAdapter(client)   # client 是注入的只读行情 client
seq = adapter.subscribe("600000.SH", on_quote, period="tick")  # 返回 int 并保存为 sequence id
adapter.stop()   # 用保存的 sequence id 调 unsubscribe_quote 恰好一次
```

- 每个实例最多创建**一个** `subscribe_quote` 订阅，通过固定的 `unsubscribe_quote` 至多一次清理；
  状态机 `NEW → ACTIVE → STOPPED`（失败 → `FAILED`），重复 subscribe/stop 幂等、restart 拒绝、
  stop-before-subscribe 不调用底层。
- subscribe 返回必须是非 bool 的 int 且 `>= 0`；负数/bool/None/float/string 或普通异常 → FAILED +
  `QuoteSubscriptionStartError`。unsubscribe 任意正常返回（含 None）成功；普通异常不重试。
- 参数验证失败抛 `QuoteSubscriptionValidationError`（只含参数名+固定约束，不含非法值），状态保持 NEW，
  底层调用数 0；callback 只要求 callable，绝不调用。
- 外部异常安全转 `QuoteSubscriptionError` 层级（`Config`/`Validation`/`Lifecycle`/`Start`/`Stop`），
  `__cause__`/`__context__` 均为 None；BaseException 先 FAILED 后原样传播。
- **安全边界**：无 download/query/account/connect/order/cancel、无动态转发、无 `client` 公共属性；
  构造后替换 client 属性不可绕过冻结 callable。不 import XtQuant、不连接 QMT、不接收真实行情，
  全部测试只用 fake client 离线完成。

## Gate 1 只读集成探针（G1-T005）

```python
from tgrid import run_gate1_readonly_probe

summary = run_gate1_readonly_probe(
    trader,          # 必须恰好是 ReadOnlyTraderAdapter
    market_data,     # 必须恰好是 ReadOnlyMarketDataAdapter
    account,         # 任意非 None 对象，原样传给 Trader
    stock_code="600000.SH",
    exchange="SH",
)
# summary.completed_operations 是固定 operation name tuple，不含任何业务数据
# summary.cleanup_completed == True
```

- 依次执行 15 个固定只读操作（Trader 生命周期 + 7 查询、MarketData 8 查询），最后 `trader.stop()`
  至多一次；成功 summary 只含固定名称 tuple 与 cleanup 布尔，不保存/repr/打印/返回任何查询结果。
- 精确类型校验拒绝 subclass/duck-typed raw client 绕过；account=None、stock_code/exchange 非法值在
  零调用前抛 `Gate1ProbeConfigError`。
- 任一主操作失败：先 `trader.stop()` 至多一次，再抛安全 `Gate1ProbeExecutionError`
  （`<operation> failed` / `...; cleanup failed`，`__cause__`/`__context__` 均为 None）。
- BaseException 先清理后原样传播，cleanup 普通异常不覆盖主异常；恶意 account/返回对象的
  repr/str/len/iter 均不被调用。
- 异常：`Gate1ProbeError` / `Gate1ProbeConfigError` / `Gate1ProbeExecutionError`。
- 不 import XtQuant、不连接 QMT、不读真实账号/行情；全部测试使用 fake client 构造真实 Adapter。

## Gate 1 只读 XtQuant Runtime Bridge（G1-T006）

```python
from tgrid.integrations.qmt_gate1_runtime import (
    build_simulation_runtime,
    make_opaque_account,
)

# 仅当用户授权真实模拟只读验收后使用（config/gate1_qmt.local.json 已就绪）
trader_bridge, market_bridge, token = build_simulation_runtime(
    "config/gate1_qmt.local.json"
)
# 将 trader_bridge/market_bridge 注入已通过的 Adapter，再调用 run_gate1_readonly_probe(...)
```

- 这是生产 `src/tgrid` 中唯一授权导入 XtQuant 的模块，且经 `importlib` **延迟加载**；核心模块保持离线。
- Trader bridge 只暴露已批准 Adapter 所需八 callable；账号在 `subscribe` 阶段按 SHA-256 指纹（路径 +
  账号）在内存中唯一匹配，`OpaqueAccount` 不含账号数据，绝不记录/返回/持久化账号 ID。
- 严格解析 `config/gate1_qmt.local.json` 声明的 reverse_repo runtime 与 **version-2 hashed binding**，
  无 fallback；未知/缺失字段、明文账号、路径 hash 不符、0/2 账号匹配等全部 fail closed。
- 无 order/cancel/download/quote 订阅面；`live_trading_allowed=false`；输出零敏感数据。

## 运行前提

- Python `>=3.9`
- 唯一运行时第三方依赖：`PyYAML`（仅用于解析配置文件）

```bash
pip install -e .
```

## 打开数据库（SQLite 基础）

```python
from tgrid import open_database

with open_database("data/tgrid.db") as conn:
    # foreign_keys 已开启，busy_timeout 已设置，schema 已迁移到版本 1
    print(conn.execute("PRAGMA user_version").fetchone()[0])  # 1
```

- 数据库路径由调用方显式传入，绝不隐式发现路径。
- 损坏、未来版本、版本不一致、migration 断档都会抛出显式 `PersistenceError` 子类并 fail closed，绝不删除/覆盖/自动修复数据库文件。
- journal 模式使用 SQLite 默认的 `delete`，在 Windows 文件数据库上安全。
- 调用方负责关闭连接，或使用 `open_database` 上下文管理器自动关闭。

## 离线 CLI（preflight）

```bash
python -m tgrid --help
python -m tgrid --version
python -m tgrid preflight --config config/config.example.yaml --database data/tgrid.db --log logs/preflight.jsonl
```

安装后 console script `tgrid` 指向同一入口。`preflight` 只做只读配置校验和本地资源 preflight（加载配置、拒绝 `live_trading=true`、配置 JSONL 日志、初始化/校验 SQLite、按序记录 `startup_begin`→`preflight_ok`→`shutdown_complete`、关闭全部资源），**不连接 QMT、不读取行情/账户、不产生任何交易**。三个路径参数均为 required，必须两两不同。

退出码：`0` 成功、`1` 受控失败、`2` 用法错误、`130` 中断。受控失败只向 stderr 输出一行简洁错误，不打印 traceback。

## Event Queue 骨架

```python
from tgrid import EventQueue

q = EventQueue(lambda evt: print(evt), maxsize=100)
q.start()
q.enqueue({"kind": "startup"})
q.stop()          # 优雅停止：已接受事件按 FIFO drain
q.join(timeout=5) # 等待 worker 退出
```

- `enqueue` 非阻塞：队列满立即抛 `EventQueueFull`，不等待、不丢、不在 producer 线程执行 handler。
- handler 只在唯一 worker 线程执行；抛任意 `BaseException` → `FAILED`，停止 dispatch。
- `raise_if_failed()` 只报告异常类型，不泄漏原始 message/repr/traceback。
- 仅供 Gate 0 本地骨架，不含 QMT/策略/订单能力。

## 结构化日志

```python
from tgrid import configure_jsonl_logger, emit, shutdown_logger

logger = configure_jsonl_logger("tgrid.app", "logs/app.jsonl")
emit(logger, "start", "引擎启动", context={"symbol": "0700.HK"})
shutdown_logger("tgrid.app")
```

- 日志路径由调用方显式传入，绝不隐式发现默认路径。
- 每行一个 JSON object；`context` key 为非空字符串且不得覆盖保留字段。
- 非法 level、保留字段冲突、非字符串 key、不可序列化值、打开/写入/flush 失败均抛显式 `LoggingError` 子类并 fail closed。

## 读取配置

```python
from tgrid import load_config

cfg = load_config("config/config.example.yaml")
print(cfg.global_config.live_trading)  # False
print(cfg.symbols["0700.HK"].core_qty)  # 600
```

配置加载**只接收显式文件路径**，绝不隐式读取本地真实配置。任何不合法配置都会抛出 `ConfigError`（携带字段路径），不会回退到宽松默认值。

## 安全边界

- `live_trading` 缺省为 `false`，本阶段不存在任何可开启它的执行路径。
- 不 `import xtquant`（唯一例外：`tgrid.integrations.qmt_gate1_runtime` 经 importlib 延迟加载且
  只读），不出现任何券商下单/撤单调用（`order_stock` / `cancel_order_stock` 全仓 AST 扫描命中 0）。
- `tgrid.adapters.qmt_readonly` / `tgrid.adapters.marketdata_readonly` /
  `tgrid.adapters.quote_subscription_readonly` 无 order/cancel/改单方法、无 download/query/account/
  connect 面、无动态转发、无 `client` 公共属性；只读 Adapter 边界之外不存在任何 QMT 访问入口。
- `tgrid.execution` 只面向注入的 `SimBroker`（确定性干跑），`tgrid.shadow` 只产出
  WOULD_BUY/WOULD_SELL，二者均无真实券商调用面（INV-009）。
- 生产风控不得依赖 Python `assert`；风险/配置异常均为显式类型。

## 测试

```bash
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
```

## 目录

```text
src/tgrid/        # 包源码（config / models / risk / persistence / reporting / events / adapters / main）
tests/unit/       # 单元测试
config/           # 示例配置（真实配置不入库）
work/             # 双 Agent 协作控制面（任务/状态/交接）
```

## 后续 Gate

- **GATE 3 PASS**（策略离线模拟）、**GATE 4 PASS**（Execution Dry Run）、**GATE 5 PASS**
  （Shadow 模式，离线部分）—— 验收证据见 `work/gates/GATE_*/ARCHITECT_REVIEW.md`。
- **GATE 6 / GATE 7**（真实资金）：必须由用户在真实 MiniQMT 环境人工执行，清单见
  `work/gates/GATE_6/GATE67_MANUAL_CHECKLIST.md`；真实 QMT 影子运行手册见
  `work/gates/GATE_5/GATE5_RUNBOOK.md`。
- 未经架构师 PASS 不得进入下一 Gate（单代理模式下由同一上下文自审）。
