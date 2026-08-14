# Task G0-T005 — 单一 Event Queue 骨架

## Goal

实现 Gate 0 的纯本地、通用单消费者 Event Queue 骨架，为后续 QMT callback isolation 提供可验证的
线程边界。当前任务只建立队列与生命周期，不接入 QMT、CLI、数据库、策略、订单或任何真实数据。

## In Scope

1. 新增 `tgrid.events`，提供线程安全、容量有界、FIFO、单 worker 的 `EventQueue`。
2. 定义明确的 lifecycle state、非阻塞 enqueue、graceful stop、bounded join 与 worker failure 状态。
3. 在 risk exception 层新增 Event Queue 专用异常并导出公共 API。
4. 测试并发生产者、stop/enqueue 竞态、队列满、handler 异常与线程清理。
5. README 只说明这是 Gate 0 本地骨架，不含 QMT/交易能力。

## Out of Scope

- QMT/XtQuant callback 注册、行情、账号、持仓、委托、成交、连接或真实事件类型。
- 策略状态机、Risk Engine 调用、OrderIntent、Reservation、broker adapter、下单/撤单。
- SQLite、JSONL logger、CLI 或 startup/shutdown 的集成；已验收模块不得修改。
- 定时器、调度器、重试、自动恢复、持久化 replay、多进程或 asyncio。
- 自动开启 live trading；`live_trading_allowed` 必须保持 false。

## Required Public Contract

在 `src/tgrid/events.py` 至少提供：

```python
class EventQueueState(Enum):
    NEW = "NEW"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"

class EventQueue:
    def __init__(self, handler, *, maxsize: int, thread_name: str = "tgrid-event-loop"): ...
    @property
    def state(self) -> EventQueueState: ...
    @property
    def failure_type(self) -> str | None: ...
    def start(self) -> None: ...
    def enqueue(self, event: object) -> None: ...
    def stop(self) -> None: ...
    def join(self, timeout: float | None = None) -> bool: ...
    def raise_if_failed(self) -> None: ...
```

Python 3.9 兼容时类型注解可用 `Optional`。允许增加私有 helper，但不得增加业务语义。

## Lifecycle Contract

```text
NEW --start--> RUNNING --stop--> STOPPING --drain accepted FIFO--> STOPPED
                         |
                         +-- handler BaseException --> FAILED
```

1. constructor：`handler` 必须 callable；`maxsize` 必须是非 bool 的正整数；`thread_name` 必须为
   非空字符串。无效参数使用显式 Event Queue exception，不能泄漏裸 queue/threading 异常。
2. `start()`：NEW 时只创建一个非 daemon worker；RUNNING 时幂等且不得创建第二线程；STOPPING、
   STOPPED、FAILED 后禁止 restart，抛 lifecycle exception。
3. `enqueue()`：只在 RUNNING 接受；状态检查与入队必须位于同一同步边界。使用非阻塞语义；满队列
   立即抛 `EventQueueFull`，不得等待、重试、静默 drop，也不得在 producer/callback 线程执行 handler。
4. `stop()`：不得无限阻塞；NEW 直接变 STOPPED；RUNNING 原子变 STOPPING，并拒绝所有之后的 enqueue；
   STOPPING/STOPPED/FAILED 幂等。stop 前成功接受的事件必须按 FIFO drain，除非 handler 已失败。
5. `join(timeout)`：只等待 worker 退出，返回 `True`/`False` 表示是否已退出；timeout 必须为 None 或
   非负有限实数（bool 禁止）。不得从 worker 自身 join；该情况必须立即抛 lifecycle exception。
6. 正常处理：每个被接受事件最多调用一次 handler；所有 handler 调用只能发生在唯一 worker 线程，
   不得并发；多 producer 的成功 enqueue 不能丢失或重复。
7. handler 抛任意 `BaseException` 时：worker 捕获线程边界、记录只含类型名的 `failure_type`、原子进入
   FAILED、停止 dispatch、丢弃尚未处理的队列项并退出；后续 enqueue 必须拒绝。
8. `raise_if_failed()`：FAILED 时抛 `EventQueueWorkerError`，用户消息只含异常类型，不含原始 message/
   repr/traceback/事件内容；非 FAILED 时不操作。不得在后台线程打印 traceback。
9. 所有 state/failure 可见性与 transition 必须由 lock/condition 保证；生产安全不得依赖 `assert`。

## Exceptions

在 `tgrid.risk.exceptions` 中定义并从 `tgrid.risk`、`tgrid` 导出至少：

```text
EventQueueError(TGridError)
EventQueueConfigError(EventQueueError)
EventQueueLifecycleError(EventQueueError)
EventQueueFull(EventQueueError)
EventQueueWorkerError(EventQueueError)
```

不得直接暴露标准库 `queue.Full` 或 handler 原始异常文本。

## Allowed Files

Claude 只能新增或修改：

```text
README.md
src/tgrid/__init__.py
src/tgrid/events.py
src/tgrid/risk/__init__.py
src/tgrid/risk/exceptions.py
tests/unit/test_events.py
work/control/WORKFLOW_STATE.yaml
work/control/CLAUDE_HEARTBEAT.md
work/locks/WORKTREE_LEASE.yaml
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md
work/handoff/claude_to_architect/TEST_REPORT.md
work/handoff/claude_to_architect/QUESTIONS.md
work/gates/GATE_0/CLAUDE_REPORT.md
work/reports/tests/G0-T005-test-output.txt
```

Lease 只在工作期间存在，交审前必须删除。

## Forbidden Files

```text
TGrid_双Agent协作与Gate验收协议_V1.0.md
TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md
.gitignore
pyproject.toml
config/**
src/tgrid/config.py
src/tgrid/models.py
src/tgrid/main.py
src/tgrid/__main__.py
src/tgrid/persistence/**
src/tgrid/reporting/**
tests/unit/test_config.py
tests/unit/test_models.py
tests/unit/test_persistence.py
tests/unit/test_logging.py
tests/unit/test_cli.py
work/control/CURRENT_TASK.md
work/control/ARCHITECT_HEARTBEAT.md
work/gates/GATE_0/TASK.md
work/gates/GATE_0/G0-T005_TASK.md
work/gates/GATE_0/*_RESULT.md
work/gates/GATE_0/ARCHITECT_REVIEW.md
work/handoff/architect_to_claude/**
work/design/**
父目录 D:/gitee/miniQMT 中 T_Grid 之外的全部文件
```

除 Allowed Files 外不得新增或修改其他文件。

## Design References

- 设计 §3.1：QMT callbacks 未来只允许 enqueue；所有状态变更由唯一事件线程串行执行。
- 设计 §35 / §50：Gate 0 包含 Event Queue 骨架，禁止 QMT 下单代码。
- 设计 §34：INV-009 fail closed、INV-010 幂等、INV-011 禁止生产安全依赖 assert。
- 协作协议 §7–§12、§18、§22、§29–§32。

## Acceptance Criteria

1. 公共 API、状态机与 exception hierarchy 符合上述契约。
2. 100 个以上事件由多个 producer 并发 enqueue 后，所有成功接受项恰好处理一次；handler 永不并发，
   且只在同一个非主 worker thread 执行。
3. stop/enqueue 的确定性交错能证明：stop 转 STOPPING 前接受的事件全部 drain，之后 enqueue 全部拒绝；
   无静默 drop、重复或 worker 泄漏。
4. 队列满立即抛项目 `EventQueueFull`，不泄漏 `queue.Full`，不阻塞 callback thread。
5. handler 的 RuntimeError、KeyboardInterrupt、SystemExit、GeneratorExit 均进入 FAILED，停止后续 dispatch，
   worker 退出；`failure_type`/`raise_if_failed()` 不泄漏唯一 secret token 或 traceback。
6. start/stop/join/raise_if_failed 幂等与非法状态均有测试；start-stop 多次/并发不得产生第二 worker。
7. join timeout 与 self-join 不死锁；测试结束后没有名为测试 thread_name 的存活线程。
8. 原 178 项测试全部通过；新增测试稳定、无 sleep 驱动的竞态断言，优先使用 Event/Barrier。
9. `compileall` 与 AST 扫描通过：无生产 `assert`、无 xtquant import、无 order_stock/cancel_order。
10. 无新增第三方依赖、无 QMT/账号/策略/订单/数据库/CLI/logging 集成。

## Required Tests / Failure Injection

- constructor 边界：handler/maxsize/thread_name 非法值。
- NEW/RUNNING/STOPPING/STOPPED/FAILED 全 transition 与 restart rejection。
- 多 producer + FIFO（单 producer 顺序及全局实际接受顺序）+ handler 单线程/不并发。
- 满队列立即失败；stop 与 enqueue 的 lock-serialized 竞态。
- stop 时 drain；stop before start；重复 start/stop/join；join timeout；worker self-join rejection。
- handler RuntimeError/KeyboardInterrupt/SystemExit/GeneratorExit，pending 项不再 dispatch，worker 退出。
- 唯一 secret token 不出现在 exception 文本、stdout、stderr；后台无 traceback。
- 完整回归与禁止 API/assert AST 扫描。

必须实际运行并保存完整输出：

```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
```

## Deliverables

1. Allowed Files 内实现与测试。
2. 更新 Implementation/Test/Questions/Claude Gate 报告。
3. `work/reports/tests/G0-T005-test-output.txt` 保存完整测试、compileall、AST 与 Failure Injection 证据。

## Stop Condition

完成后检查 diff 仅含 Allowed Files，原子更新：

```text
state: REVIEW_READY
owner: architect
gate: 0
task_id: G0-T005
iteration: 1
git_head_commit: f59801e765c539e9f9a7aa690215f2e66570fd79
```

更新真实本机时间、释放 Lease，不 commit、不 push，停止写入等待 Review。
