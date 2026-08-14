# TGrid

QMT 低频做 T 交易引擎（开发中）。

> **当前状态：Gate 0 / 项目骨架。** 本仓库目前只有配置读取、配置数据模型、显式风险异常类型和 SQLite 持久化基础，**没有任何 QMT 连接、行情、账户、持仓、下单、撤单或真实交易能力**，也没有策略计算能力。

## 已实现（G0-T001 / G0-T002）

- `tgrid.config.load_config(path)`：从调用方显式传入的 YAML 路径读取并校验配置，返回有类型的 `RootConfig`。
- 配置数据模型（`GlobalConfig` / `SymbolConfig` / `RootConfig`），全部为不可变 dataclass。
- 显式风险异常类型（`ConfigError`、`RiskError`、`CoreFloorViolation`、`InsufficientAvailableVolume`、`SellReservationConflict`、`CashReservationConflict`）。
- 严格 fail-closed 校验：未知字段、缺失必填字段、错误根结构、非法类型/范围、bool 冒充整数、NaN/Infinity 都会被拒绝。
- 示例配置 `config/config.example.yaml`（仅含 `0700.HK` 与 `000333.SZ` 示例数量，代码不写死任何证券或数量）。
- `tgrid.persistence`（SQLite 基础，仅标准库 `sqlite3`）：显式路径打开、`PRAGMA foreign_keys=ON`、`busy_timeout`、完整性检查、有序事务化幂等 migration、schema 版本一致性校验，以及 `PersistenceError` / `DatabaseOpenError` / `DatabaseIntegrityError` / `SchemaVersionError` / `MigrationError` 异常。当前只有 `schema_migrations` 与 `application_metadata` 两张基础表，不含任何交易领域表。
- `tgrid.reporting`（结构化 JSONL 日志，仅标准库）：`configure_jsonl_logger(name, path)` 显式路径配置、`emit(logger, event, message, level, context)` 写入单行可解析 JSON、`shutdown_logger(name)` 幂等关闭。输出 UTF-8 JSONL（`schema_version`/`timestamp`/`level`/`logger`/`event`/`message`/`context`），中文/换行/引号无损 round-trip；配置/序列化/写入失败抛 `LoggingError` / `LoggingConfigError` / `LoggingEmitError`，不静默吞错、不留半行。
- `tgrid.events`（单消费者 Event Queue 骨架，仅标准库）：线程安全、容量有界、FIFO、单 worker 的 `EventQueue`，生命周期 `NEW → RUNNING → STOPPING → STOPPED`（handler 抛异常 → `FAILED`）。非阻塞 `enqueue`（满队列抛 `EventQueueFull`）、graceful `stop` + drain、有界 `join`、`raise_if_failed()`。异常：`EventQueueError` / `EventQueueConfigError` / `EventQueueLifecycleError` / `EventQueueFull` / `EventQueueWorkerError`。为后续 QMT callback 隔离提供线程边界，不含 QMT/策略/订单能力。

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
- 生产风控不得依赖 Python `assert`；风险/配置异常均为显式类型。

## 测试

```bash
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
```

## 目录

```text
src/tgrid/        # 包源码（config / models / risk / persistence / reporting / main）
tests/unit/       # 单元测试
config/           # 示例配置（真实配置不入库）
work/             # 双 Agent 协作控制面（任务/状态/交接）
```

## 后续 Gate

SQLite 持久化、logging、CLI、Event Queue、Position Manager、T-Lot Ledger 等按设计文档 Gate 体系依次推进。未经架构师 PASS 不得进入下一 Gate。
