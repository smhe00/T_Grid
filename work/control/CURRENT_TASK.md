# Current Task — G1-T002

## Task Name

离线依赖注入的 QMT Trader 只读 Adapter 边界

## Objective

实现一个不直接导入 XtQuant、只接受依赖注入 client 的严格只读 Trader Adapter。它只暴露连接生命周期、
账号订阅和资产/持仓/委托/成交查询，显式状态机与安全异常；不暴露任何报单、撤单、通用动态转发或原始
client 访问。本任务只使用 fake client 离线测试，不连接 QMT、不读取真实账号。

## Scope

新增 `tgrid.adapters.qmt_readonly`，公共 API：

```python
class ReadOnlyTraderState(Enum):
    NEW = "NEW"
    STARTED = "STARTED"
    CONNECTED = "CONNECTED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"

class ReadOnlyTraderAdapter:
    def __init__(self, client: object) -> None: ...
    @property
    def state(self) -> ReadOnlyTraderState: ...
    @property
    def failure_type(self) -> Optional[str]: ...
    def start(self) -> None: ...
    def connect(self) -> None: ...
    def subscribe(self, account: object) -> None: ...
    def query_asset(self, account: object) -> object: ...
    def query_positions(self, account: object) -> object: ...
    def query_orders(self, account: object, *, cancelable_only: bool = False) -> object: ...
    def query_trades(self, account: object) -> object: ...
    def stop(self) -> None: ...
    def raise_if_failed(self) -> None: ...
```

显式异常：

```text
QmtReadOnlyError(TGridError)
QmtAdapterConfigError(QmtReadOnlyError)
QmtAdapterLifecycleError(QmtReadOnlyError)
QmtConnectionError(QmtReadOnlyError)
QmtQueryError(QmtReadOnlyError)
```

允许增加私有 helper/flag/lock，但不得增加 QMT 实例构造、行情能力或业务语义。

## Underlying Method Mapping

Adapter 只能调用注入对象的以下固定方法：

```text
start                  -> client.start()
connect                -> client.connect()
subscribe              -> client.subscribe(account)
query_asset            -> client.query_stock_asset(account)
query_positions        -> client.query_stock_positions(account)
query_orders           -> client.query_stock_orders(account, cancelable_only)
query_trades           -> client.query_stock_trades(account)
stop                   -> client.stop()
```

不得提供 `__getattr__`、`call(name, ...)`、`raw_client`、`client` property 或任何通用转发入口。

## Lifecycle Contract

1. constructor 检查注入 client 非 None，且上述 8 个方法全部 callable；失败抛
   `QmtAdapterConfigError`，错误只含缺失方法名/类型名，不含 client repr。
2. `start()`：NEW 时调用底层一次并进入 STARTED；STARTED/CONNECTED 时幂等且不重复调用；
   STOPPED/FAILED 后禁止 restart。
3. `connect()`：只允许 STARTED；底层返回必须是非 bool 的整数。仅 `0` 表示成功并进入 CONNECTED；
   非零、错误类型或异常均进入 FAILED 并抛安全 `QmtConnectionError`。
4. `subscribe()`：只允许 CONNECTED；底层返回必须是非 bool 整数且仅 `0` 成功；失败进入 FAILED，
   抛 `QmtConnectionError`。
5. 四个 query 只允许 CONNECTED；`cancelable_only` 必须是 bool。底层返回 `None` 视为失败；其他对象
   原样返回。异常/None 进入 FAILED 并抛 `QmtQueryError`。
6. `stop()`：NEW 直接 STOPPED 且不调用底层；STARTED/CONNECTED 调底层恰好一次并进入 STOPPED；
   FAILED 若底层 start 已成功，也必须尝试 stop 恰好一次做清理，但状态保持 FAILED；重复 stop 幂等。
7. 所有外部调用抛 `Exception` 时，公共异常只含操作名与原异常类型，不含原 message/repr/traceback，
   并使用 `from None`；`failure_type` 只存类型名。
8. 外部调用抛 KeyboardInterrupt/SystemExit/GeneratorExit 时，先原子标记 FAILED/failure_type，再原样
   传播；之后 `stop()` 仍可执行清理。不得吞掉这些 BaseException。
9. `raise_if_failed()` 在 FAILED 时抛 `QmtReadOnlyError`（或更具体安全子类），文本只含 failure_type；
   其他状态 no-op。
10. public state/flags 必须线程安全；不得使用生产 `assert`。不要求并发调用 query，但生命周期竞争
    必须 fail closed，不得产生第二次 start/stop。

## Security Boundary

- Adapter 类本身不得出现 `order_stock`、`cancel_order_stock`、改单或等价交易方法。
- fake client 可以实现危险方法用于证明 Adapter 不可达；测试不得调用危险方法本身。
- `getattr(adapter, "order_stock")` / `cancel_order_stock` 必须失败且 fake 的危险调用计数保持 0。
- 生产模块不得 `import xtquant`，不得读取环境变量、文件、账号或行情。
- 不得将注入 client 暴露为公共属性/返回值；错误不得泄漏 account/client repr 或 secret。

## Invariants

1. Gate 1 仍严格只读；无报单/撤单路径。
2. 所有 QMT 调用未来只能经过 Adapter 的固定方法，不提供动态逃逸口。
3. `live_trading_allowed=false`；本任务无配置开关可改变它。
4. 外部失败 fail closed，状态和异常类型可审计，敏感 message 不泄漏。
5. start/stop 幂等，失败后可清理，不依赖 `assert`。
6. 无实际 XtQuant import/实例化/连接/账号/行情访问。

## Acceptance Criteria

1. 公共 API、method mapping、状态机与异常层级符合本任务。
2. fake client 证明每个 public 方法只调用对应底层方法，参数/返回值不变，且 query 顺序无隐藏副作用。
3. connect/subscribe 的 bool、None、float/string、非零返回均 fail closed；只有 int 0 成功。
4. query 返回 None、缺失/非 callable method、非法 lifecycle、非法 cancelable_only 均抛显式项目异常。
5. RuntimeError unique secret 不出现在公共异常、cause/context、stdout/stderr；failure_type 正确。
6. KeyboardInterrupt/SystemExit/GeneratorExit 覆盖 start/connect/subscribe/query/stop 的代表路径：状态先 FAILED，
   原样传播，已启动 client 可由后续 stop 清理且只清理一次。
7. fake client 即使带有完整 order/cancel 方法，Adapter 实例也没有这些 API、没有通用转发、危险计数为 0。
8. 多线程重复 start/stop 最多各调用底层一次；无死锁、无残留线程。
9. 完整 Gate 0 + Gate 1 回归不少于 223 项，compileall、AST 安全扫描通过。
10. 无 `xtquant` import、无新增第三方依赖、无 QMT/账号/行情真实访问；`live_trading_allowed=false`。

## Required Tests / Failure Injection

- constructor 8 个 required method 的逐项缺失与 non-callable。
- 全 lifecycle transition、重复 start/connect/stop、restart rejection、query-before-connect。
- 正常 method mapping：asset/positions/orders/trades，含 `cancelable_only` True/False。
- connect/subscribe 所有非法返回类型和非零码。
- query None 与底层 RuntimeError；unique secret 不泄漏，cause/context 均安全。
- start/connect/query/stop 的普通异常及代表性 KeyboardInterrupt/SystemExit/GeneratorExit 清理路径。
- fake dangerous client 的 order/cancel API 不可达、无调用。
- 并发重复 start/stop，底层调用计数恰为 1。
- AST：生产无 assert、无 xtquant import、无 order/cancel call；不得通过字符串动态 getattr/call 绕过。
- 完整 unittest、compileall；完整输出保存。

## Allowed Files

Claude 只能新增或修改：

```text
src/tgrid/adapters/__init__.py
src/tgrid/adapters/qmt_readonly.py
src/tgrid/risk/exceptions.py
src/tgrid/risk/__init__.py
src/tgrid/__init__.py
tests/unit/test_qmt_readonly.py
README.md
work/reports/tests/G1-T002-test-output.txt
work/gates/GATE_1/CLAUDE_REPORT.md
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md
work/handoff/claude_to_architect/TEST_REPORT.md
work/handoff/claude_to_architect/QUESTIONS.md
work/control/CLAUDE_HEARTBEAT.md
work/control/WORKFLOW_STATE.yaml
```

`WORKFLOW_STATE.yaml` 只允许更新 worker state/owner/iteration/last_actor/last_update/git_head_commit/notes
和必要 escalation 字段；不得修改 Gate、基线、设计路径或 `live_trading_allowed`。

## Forbidden Files / Changes

除 Allowed Files 外全部禁止，尤其：

```text
pyproject.toml
config/**
src/tgrid/main.py
src/tgrid/events.py
src/tgrid/persistence/**
src/tgrid/reporting/**
其他 tests/**
docs/**
work/control/CURRENT_TASK.md
work/control/ARCHITECT_HEARTBEAT.md
work/gates/GATE_1/TASK.md
work/gates/GATE_1/ARCHITECT_REVIEW.md
work/gates/GATE_1/RESULT.md
父目录 D:/gitee/miniQMT 中 T_Grid 之外全部文件
```

不得安装依赖、启动/停止 QMT、连接/查询真实数据、添加行情 Adapter、账号发现、日志/DB/CLI 集成，
也不得增加任何下单、撤单、改单或动态 method forwarding。

## Deliverables

1. 只读 Trader Adapter、异常、导出与 README 边界说明。
2. 完整单元测试和 `work/reports/tests/G1-T002-test-output.txt`。
3. 更新 Claude Gate、Implementation/Test/Questions 报告。
4. 不提交 commit；等待架构师独立 Review。

## Stop Condition

完成范围检查、测试并释放 Lease 后，原子设置：

```text
state: REVIEW_READY
owner: architect
iteration: 1
last_actor: claude
git_head_commit: 73cbe3be6abf3744fd16b322c45fb4a17ee6bb40
live_trading_allowed: false
```

然后停止修改。出现设计冲突、范围污染或无法保证只读边界时设置 `BLOCKED` 并停止。
