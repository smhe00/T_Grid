# Current Task — G1-T005

## Task Name

离线 Gate 1 只读集成探针编排器

## Objective

在不导入 XtQuant、不连接 QMT、不读取真实账号/行情的前提下，组合已通过的
`ReadOnlyTraderAdapter` 与 `ReadOnlyMarketDataAdapter`，实现固定顺序的 Gate 1 只读探针编排器。
它只调用既有 Adapter 公共只读方法，返回不含业务数据的固定审计摘要，并保证任意失败路径都尝试安全
停止 Trader。全部测试使用 fake client 构造真实 Adapter，不加入订阅、CLI、DB、日志或交易逻辑。

## Public API

新增 `tgrid.probes.gate1_readonly` 与 `tgrid.probes`：

```python
@dataclass(frozen=True)
class Gate1ReadOnlyProbeSummary:
    completed_operations: tuple[str, ...]
    cleanup_completed: bool

class Gate1ProbeError(TGridError): ...
class Gate1ProbeConfigError(Gate1ProbeError): ...
class Gate1ProbeExecutionError(Gate1ProbeError): ...

def run_gate1_readonly_probe(
    trader: ReadOnlyTraderAdapter,
    market_data: ReadOnlyMarketDataAdapter,
    account: object,
    stock_code: str,
    exchange: str,
) -> Gate1ReadOnlyProbeSummary: ...
```

异常放在 `tgrid.risk.exceptions` 并由 root/risk package 导出；summary 与 runner 由 root/probes 导出。

## Exact Operation Order

runner 必须依次且各调用一次：

```text
1  trader.start()
2  trader.connect()
3  trader.subscribe(account)
4  trader.query_asset(account)
5  trader.query_positions(account)
6  trader.query_orders(account, cancelable_only=False)
7  trader.query_trades(account)
8  market_data.get_full_tick([stock_code])
9  market_data.get_market_data([], [stock_code], "1d", count=1)
10 market_data.get_market_data_ex([], [stock_code], "5m", count=1)
11 market_data.get_instrument_detail(stock_code, complete=False)
12 market_data.get_divid_factors(stock_code)
13 market_data.get_trading_calendar(exchange)
14 market_data.get_trading_dates(exchange, count=1)
15 market_data.get_trading_period(stock_code)
16 trader.stop()  # cleanup，成功或失败路径均至多一次
```

成功 summary 的 `completed_operations` 必须是固定 operation name tuple（不含对象类型、返回数量、symbol、
account 或任何数据），`cleanup_completed=True`。所有查询结果只用于确认调用完成，不得保存、repr、打印、
序列化、计数或返回。

## Configuration Boundary

1. `trader` 必须满足 `type(trader) is ReadOnlyTraderAdapter`；`market_data` 必须满足
   `type(market_data) is ReadOnlyMarketDataAdapter`，禁止 subclass override 或 duck-typed raw client 绕过。
2. `account` 只允许原样传给 Trader Adapter，runner 不做 repr/type-name/log/存储；可为任意非 None 对象。
3. `stock_code`、`exchange` 必须为非空字符串；验证失败抛安全 `Gate1ProbeConfigError`，不得启动 trader
   或调用任何 adapter 方法，错误不含非法值。
4. runner 不接受 callback、client、method name、任意 callable 或额外配置。

## Failure / Cleanup Contract

1. 每个 operation 完成后才把固定名称追加到私有 completed list；失败 operation 不记为 completed。
2. 任一 operation 抛普通 `Exception`：只记录固定 operation name，随后调用 `trader.stop()` 至多一次。
   离开 active except context 后抛 `Gate1ProbeExecutionError`；文本仅说明固定 operation 与 cleanup 是否失败，
   `__cause__`/`__context__` 均为 None，不含原异常类型/message/repr/traceback或 account/market data。
3. 主 operation 失败、cleanup 成功：错误固定为 `<operation> failed`；主 operation 与 cleanup 都失败：
   固定为 `<operation> failed; cleanup failed`。cleanup 失败不得覆盖主 operation 名称。
4. 所有主 operation 成功但 `trader.stop()` 普通异常：抛 `Gate1ProbeExecutionError("cleanup failed")`。
5. 主 operation 抛 KeyboardInterrupt/SystemExit/GeneratorExit：仍尝试 stop 至多一次，然后原样传播主
   BaseException；cleanup 的普通异常不得覆盖它。若 cleanup 自身抛 BaseException 且无主 BaseException，
   原样传播 cleanup BaseException。
6. account/symbol/返回对象的恶意 `__repr__`、`__str__`、`__len__`、`__iter__` 均不得由 runner 调用。
7. runner 自身不得调用 Adapter 私有字段、底层 client 或任何不在 Exact Operation Order 的 API。

## Security Boundary

- 生产模块不得 `import xtquant`，不得读取环境变量、文件、网络、账号或行情。
- 不得包含 subscribe_quote/unsubscribe_quote、download、connect client、order、cancel 或动态 forwarding。
- 不得把 query 返回对象放入 summary；不得打印或持久化业务数据。
- `live_trading_allowed=false`，本任务不提供开关。

## Acceptance Criteria

1. happy path 的 16 步精确顺序、参数、次数与固定 summary 正确。
2. 1–15 每一步单独注入普通异常，均在失败后调用 stop 至多一次，公共异常图无 secret。
3. 每一步失败前的 completed operation 精确，但不得通过异常或返回值公开；仅测试内部 fake call log 审计。
4. 主失败+cleanup 失败不掩盖主 operation；全成功+cleanup 失败只报告 cleanup。
5. 主 BaseException 三类代表路径均先 cleanup 后原样传播；cleanup 普通异常不覆盖主 BaseException。
6. 精确类型校验拒绝 subclass/raw fake；非法 account=None、symbol/exchange 类型/空值在零调用前拒绝。
7. 恶意 account 和返回对象的 repr/str/len/iter 调用计数均为 0。
8. AST 证明 runner 只调用两个批准 Adapter 的固定公共方法，无私有访问/危险 API/动态转发。
9. 完整回归不少于 371 项，compileall、AST 安全扫描通过，完整输出保存。
10. 无真实 XtQuant/QMT/账号/行情访问、无新增依赖；`live_trading_allowed=false`。

## Required Tests / Failure Injection

- happy path 精确 16 步与参数；summary frozen、只含固定 names 和 cleanup bool。
- trader 7 个主步骤、market data 8 个步骤逐项 RuntimeError secret 注入。
- 主异常 + stop 异常；纯 stop 异常；异常 graph/stdout/stderr secret 扫描。
- KeyboardInterrupt/SystemExit/GeneratorExit 主步骤代表路径及 cleanup 行为。
- exact-type、None account、stock_code/exchange 参数验证与零调用。
- poisonous repr/str/len/iter account/return object 未被观察。
- AST：无 assert/xtquant/subscription/download/order/cancel/dynamic getattr/call、无 `_methods`/私有字段访问。
- 完整 unittest、compileall；完整输出保存。

## Allowed Files

Claude 只能新增或修改：

```text
src/tgrid/probes/__init__.py
src/tgrid/probes/gate1_readonly.py
src/tgrid/risk/exceptions.py
src/tgrid/risk/__init__.py
src/tgrid/__init__.py
tests/unit/test_gate1_readonly_probe.py
README.md
work/reports/tests/G1-T005-test-output.txt
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
src/tgrid/adapters/**
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

不得安装依赖、导入/启动/停止/连接 QMT、真实查询或订阅、访问账号、加入 CLI/DB/log 或增加交易能力。

## Deliverables

1. Gate 1 只读集成探针 summary/runner、异常与导出。
2. 完整单元测试和 `work/reports/tests/G1-T005-test-output.txt`。
3. 更新 README、Claude Gate、Implementation/Test/Questions 报告。
4. 不提交 commit；等待架构师独立 Review。

## Stop Condition

完成范围检查、测试并释放 Lease 后，原子设置：

```text
state: REVIEW_READY
owner: architect
iteration: 1
last_actor: claude
git_head_commit: 81e1abcc6e50bae7629335a2e40633ba3a870bff
live_trading_allowed: false
```

然后停止修改。出现设计冲突、范围污染或无法保证只读边界时设置 `BLOCKED` 并停止。
