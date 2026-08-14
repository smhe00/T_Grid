# Current Task — G1-T004

## Task Name

离线依赖注入的单路 Quote Subscription 只读生命周期边界

## Objective

实现一个不直接导入 XtQuant、只接受依赖注入 client 的单路行情订阅生命周期 Adapter。每个实例最多创建
一个 `subscribe_quote` 订阅，并通过固定的 `unsubscribe_quote` 做至多一次清理；显式记录状态、sequence id
与失败类型。全部测试使用 fake client，不连接 QMT、不接收真实行情，不加入 Event Queue 或业务逻辑。

## Scope

新增 `tgrid.adapters.quote_subscription_readonly`，公共 API：

```python
class QuoteSubscriptionState(Enum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"
    FAILED = "FAILED"

class ReadOnlyQuoteSubscriptionAdapter:
    def __init__(self, client: object) -> None: ...
    @property
    def state(self) -> QuoteSubscriptionState: ...
    @property
    def sequence_id(self) -> Optional[int]: ...
    @property
    def failure_type(self) -> Optional[str]: ...
    def subscribe(
        self, stock_code: str, callback: Callable[[object], None], *,
        period: str = "tick", start_time: str = "", end_time: str = "", count: int = 0,
    ) -> int: ...
    def stop(self) -> None: ...
    def raise_if_failed(self) -> None: ...
```

显式异常：

```text
QuoteSubscriptionError(TGridError)
QuoteSubscriptionConfigError(QuoteSubscriptionError)
QuoteSubscriptionValidationError(QuoteSubscriptionError)
QuoteSubscriptionLifecycleError(QuoteSubscriptionError)
QuoteSubscriptionStartError(QuoteSubscriptionError)
QuoteSubscriptionStopError(QuoteSubscriptionError)
```

## Underlying Method Mapping

构造时只冻结以下两个字面量 callable：

```text
subscribe -> client.subscribe_quote(stock_code, period, start_time, end_time, count, callback)
stop      -> client.unsubscribe_quote(sequence_id)
```

不得暴露底层的 `subscribe_quote`/`unsubscribe_quote` 方法名，不得提供动态转发或 raw client。

## Lifecycle Contract

1. constructor 检查 client 非 None，两个方法均 callable；descriptor/属性读取普通异常转为安全
   `QuoteSubscriptionConfigError`，异常图不得保留原异常；BaseException 原样传播。
2. NEW 时 `subscribe()` 验证全部参数后调用底层恰好一次。返回必须是非 bool 的 int 且 `>= 0`；成功保存
   sequence id 并进入 ACTIVE。负数、bool、None、float/string 或普通异常均进入 FAILED，抛安全
   `QuoteSubscriptionStartError`。
3. ACTIVE 后再次 subscribe，以及 STOPPED/FAILED 后 subscribe，均抛
   `QuoteSubscriptionLifecycleError`，不得重复调用底层。
4. NEW 时 `stop()` 直接进入 STOPPED，不调用底层；ACTIVE 时用保存的 sequence id 调用
   `unsubscribe_quote` 恰好一次，任意正常返回值（包括 None）均视为成功并进入 STOPPED；重复 stop 幂等。
5. subscribe 已成功但之后处于 FAILED 且 cleanup 尚未尝试时，`stop()` 仍尝试 unsubscribe 恰好一次；
   状态保持 FAILED。若 subscribe 从未成功，不调用 unsubscribe。
6. unsubscribe 普通异常进入 FAILED，保存类型并抛安全 `QuoteSubscriptionStopError`；cleanup 被视为已尝试，
   后续 stop 不自动重试，以避免不确定结果下重复撤销订阅。
7. 底层普通异常的公共文本只含操作名与异常类型，`__cause__`/`__context__` 均为 None，不保留原异常
   message/repr/traceback；`failure_type` 只存类型名或固定失败类别。
8. KeyboardInterrupt/SystemExit/GeneratorExit 在 subscribe/stop 中先标记 FAILED/failure_type，再原样传播；
   若 subscribe 已成功，后续 stop 仍按规则做至多一次清理。
9. `raise_if_failed()` 仅在 FAILED 时抛安全 `QuoteSubscriptionError`，只报告 failure_type；其他状态 no-op。
10. 本任务只要求顺序调用生命周期；不得宣称支持并发 subscribe/stop，也不得创建线程。

## Validation Contract

- `stock_code`、`period` 必须为非空字符串；`start_time`、`end_time` 必须为字符串。
- `callback` 必须 callable，但不得调用、包装或检查其 repr。
- `count` 必须是非 bool 的 int 且 `>= 0`。
- 验证失败抛 `QuoteSubscriptionValidationError`，只含参数名与固定约束，不含非法值；状态保持 NEW，
  subscribe/unsubscribe 调用计数均为 0。

## Security Boundary

- 生产模块不得 `import xtquant`，不得读取环境、文件、账号、网络或真实行情。
- 不得包含 download、order、cancel、账号查询、行情查询或连接 API。
- 不得执行 callback；fake client 可仅保存 callback identity，用于证明参数原样传递。
- 构造后 client 属性替换不得改变冻结 callable；不得公开 client 或 generic call/forward。
- `live_trading_allowed=false`，无任何开关可改变。

## Acceptance Criteria

1. 公共 API、异常层级、固定 mapping、参数验证和状态机符合任务。
2. fake client 证明 subscribe 六个参数原样传递，callback identity 保持，成功 sequence id 返回并保存。
3. subscribe 返回类型/负数矩阵全部 fail closed；底层普通异常 secret 不泄漏。
4. NEW/ACTIVE/STOPPED/FAILED 的 subscribe/stop/repeat/restart 路径及调用次数精确。
5. unsubscribe 的 None/任意正常返回成功；普通异常不重试，失败类型与异常图安全。
6. BaseException 代表路径先 FAILED 后原样传播，已知 sequence 的后续 cleanup 至多一次。
7. constructor descriptor secret、构造后 method 替换与 dangerous fake 安全。
8. Adapter 无 download/query/account/connect/order/cancel/dynamic forwarding，危险计数 0。
9. 完整回归不少于 325 项，compileall、AST 安全扫描通过，完整输出保存。
10. 无真实 XtQuant/行情/账号访问、无新增依赖；`live_trading_allowed=false`。

## Required Tests / Failure Injection

- constructor 两个方法逐项 missing/non-callable/descriptor exception/BaseException。
- 参数验证矩阵；callback identity；六个 subscribe 实参。
- 返回值：0、正整数成功；负数、bool、None、float/string 失败。
- 全生命周期、重复 subscribe/stop、restart rejection、stop-before-subscribe。
- subscribe/unsubscribe RuntimeError unique secret 的 cause/context/stdout/stderr 安全。
- KeyboardInterrupt/SystemExit/GeneratorExit 代表路径与后续 cleanup。
- 构造后属性替换不改变冻结 callable；dangerous fake 的交易/下载/查询方法不可达。
- AST：无 assert/xtquant/download/query/account/connect/order/cancel/dynamic getattr/call。
- 完整 unittest、compileall；完整输出保存。

## Allowed Files

Claude 只能新增或修改：

```text
src/tgrid/adapters/quote_subscription_readonly.py
src/tgrid/adapters/__init__.py
src/tgrid/risk/exceptions.py
src/tgrid/risk/__init__.py
src/tgrid/__init__.py
tests/unit/test_quote_subscription_readonly.py
README.md
work/reports/tests/G1-T004-test-output.txt
work/gates/GATE_1/CLAUDE_REPORT.md
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md
work/handoff/claude_to_architect/TEST_REPORT.md
work/handoff/claude_to_architect/QUESTIONS.md
work/control/CLAUDE_HEARTBEAT.md
work/control/WORKFLOW_STATE.yaml
```

`WORKFLOW_STATE.yaml` 只允许更新 worker state/owner/iteration/last_actor/last_update/git_head_commit/notes
和必要 escalation 字段；不得改变 Gate、基线、设计路径或 `live_trading_allowed`。

## Forbidden Files / Changes

除 Allowed Files 外全部禁止，尤其：

```text
pyproject.toml
config/**
src/tgrid/main.py
src/tgrid/events.py
src/tgrid/adapters/qmt_readonly.py
src/tgrid/adapters/marketdata_readonly.py
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

不得安装依赖、启动/停止/连接 QMT、真实订阅或查询行情、访问账号、加入 Event Queue 或增加交易能力。

## Deliverables

1. 单路 Quote Subscription 只读生命周期 Adapter、异常、导出与 README 边界说明。
2. 完整单元测试和 `work/reports/tests/G1-T004-test-output.txt`。
3. 更新 Claude Gate、Implementation/Test/Questions 报告。
4. 不提交 commit；等待架构师独立 Review。

## Stop Condition

完成范围检查、测试并释放 Lease 后，原子设置：

```text
state: REVIEW_READY
owner: architect
iteration: 1
last_actor: claude
git_head_commit: 6d6d30a831825b65588e4e6a1bbdc54febf14bee
live_trading_allowed: false
```

然后停止修改。出现设计冲突、范围污染或无法保证只读边界时设置 `BLOCKED` 并停止。
