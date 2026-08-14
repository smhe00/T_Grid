# TGrid

QMT 低频做 T 交易引擎（开发中）。

> **当前状态：Gate 0 / Gate 1 只读边界。** 本仓库目前有配置读取、配置数据模型、显式风险异常类型、SQLite 持久化基础，以及一个**严格只读的 QMT Adapter 边界**（`tgrid.adapters.qmt_readonly`）。它**没有任何行情、账户、持仓、下单、撤单或真实交易能力**，也没有策略计算能力；Adapter 只通过依赖注入的 client 调用固定只读方法，不 import XtQuant、不连接真实 QMT。

## 已实现（G0-T001 / G0-T002 / G1-T002 / G1-T003 / G1-T004）

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
- 不 `import xtquant`，不出现任何券商下单/撤单调用。
- `tgrid.adapters.qmt_readonly` / `tgrid.adapters.marketdata_readonly` /
  `tgrid.adapters.quote_subscription_readonly` 无 order/cancel/改单方法、无 download/query/account/
  connect 面、无动态转发、无 `client` 公共属性；只读 Adapter 边界之外不存在任何 QMT 访问入口。
  quote subscription 只订阅/撤销单路行情，不执行 callback、不进入业务逻辑。
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

SQLite 持久化、logging、CLI、Event Queue、Position Manager、T-Lot Ledger 等按设计文档 Gate 体系依次推进。未经架构师 PASS 不得进入下一 Gate。
