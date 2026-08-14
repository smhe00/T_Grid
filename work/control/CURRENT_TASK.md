# Current Task — G1-T003

## Task Name

离线依赖注入的 MarketData 查询只读 Adapter 边界

## Objective

实现一个不直接导入 XtQuant、只接受依赖注入 client 的固定只读行情/参考数据查询 Adapter。它只封装
G1-T001 静态确认存在的快照、历史行情、合约资料、复权因子、交易日历与交易时段查询；不实现订阅、
下载、连接、账号、交易或通用动态转发。本任务只使用 fake client 离线测试。

## Scope

新增 `tgrid.adapters.marketdata_readonly`，公共 API：

```python
class ReadOnlyMarketDataAdapter:
    def __init__(self, client: object) -> None: ...
    def get_full_tick(self, stock_codes: Sequence[str]) -> object: ...
    def get_market_data(
        self, field_list: Sequence[str], stock_list: Sequence[str], period: str,
        *, start_time: str = "", end_time: str = "", count: int = -1,
        dividend_type: str = "none", fill_data: bool = True,
    ) -> object: ...
    def get_market_data_ex(...same arguments...) -> object: ...
    def get_instrument_detail(self, stock_code: str, *, complete: bool = False) -> object: ...
    def get_divid_factors(self, stock_code: str, *, start_time: str = "", end_time: str = "") -> object: ...
    def get_trading_calendar(self, market: str, *, start_time: str = "", end_time: str = "") -> object: ...
    def get_trading_dates(
        self, market: str, *, start_time: str = "", end_time: str = "", count: int = -1,
    ) -> object: ...
    def get_trading_period(self, stock_code: str) -> object: ...
```

允许将重复签名抽为私有 helper，但不得增加订阅、下载、连接、账号或交易能力。

显式异常：

```text
MarketDataReadOnlyError(TGridError)
MarketDataAdapterConfigError(MarketDataReadOnlyError)
MarketDataValidationError(MarketDataReadOnlyError)
MarketDataQueryError(MarketDataReadOnlyError)
```

## Underlying Method Mapping

Adapter 只能调用构造时从注入对象冻结的以下八个字面量 callable：

```text
get_full_tick          -> client.get_full_tick(list(stock_codes))
get_market_data        -> client.get_market_data(list(fields), list(stocks), period, start, end, count, dividend, fill)
get_market_data_ex     -> client.get_market_data_ex(list(fields), list(stocks), period, start, end, count, dividend, fill)
get_instrument_detail  -> client.get_instrument_detail(stock_code, complete)
get_divid_factors      -> client.get_divid_factors(stock_code, start_time, end_time)
get_trading_calendar   -> client.get_trading_calendar(market, start_time, end_time)
get_trading_dates      -> client.get_trading_dates(market, start_time, end_time, count)
get_trading_period     -> client.get_trading_period(stock_code)
```

不得提供 `__getattr__`、`call(name, ...)`、raw client/property 或任何字符串驱动的通用转发入口。

## Validation Contract

1. constructor 检查 client 非 None，八个 required method 均 callable；属性读取抛普通 Exception、缺失或
   non-callable 均转为安全 `MarketDataAdapterConfigError`，文本只含固定方法名/异常类型，不含 client repr。
2. `stock_codes`、`field_list`、`stock_list` 必须是非字符串 Sequence；stock list/code list 非空，成员均为
   非空字符串；field list 可为空表示底层默认字段。传给底层前创建新的 list，不得让底层修改调用方容器。
3. `stock_code`、`market`、`period` 必须为非空字符串；时间与 `dividend_type` 必须为字符串；`complete`、
   `fill_data` 必须为 bool；`count` 必须为非 bool 的 int，且只允许 `-1` 或正整数。
4. 参数验证失败抛 `MarketDataValidationError`，文本只含参数名和预期类型/约束，不含非法值 repr/message，
   且不得调用任何底层方法。
5. 底层返回 `None` 视为查询失败；其他对象（包括空 dict/list）原样返回。
6. 底层普通 Exception 转为安全 `MarketDataQueryError`；异常文本只含操作名与原异常类型，
   `__cause__ is None`、`__context__ is None`，不得保留原异常对象/traceback/repr/message。
7. KeyboardInterrupt/SystemExit/GeneratorExit 原样传播，不得转为项目异常或吞掉。
8. 成功构造后只使用冻结的八个 bound callable；构造后 client 属性替换/descriptor 变化不得改变目标。

## Security Boundary

- 生产模块不得 `import xtquant`，不得读取环境变量、文件、账号、行情或网络。
- 不得出现 `subscribe_quote`、`unsubscribe_quote`、`download_*`、`order_*`、`cancel_*` 的调用或公共 API。
- 不得将注入 client 暴露为公共属性/返回值；错误不得泄漏 symbol、参数值、client repr 或 unique secret。
- 本任务不验证真实数据结构、新鲜度或 QMT 连接；这些能力仍为 `AVAILABLE_UNVERIFIED`。

## Invariants

1. Gate 1 严格只读，且本任务只是离线 transport boundary。
2. 八个底层调用为固定、显式、可审计 mapping，无动态逃逸口。
3. `live_trading_allowed=false`，无配置可改变。
4. 外部普通异常的完整异常图不携带敏感信息；BaseException 不被吞掉。
5. 无实际 XtQuant import/实例化/连接/查询，无第三方依赖。

## Acceptance Criteria

1. 公共 API、异常层级、固定 mapping 与验证合同符合任务。
2. fake client 证明每个公共方法仅调用对应底层方法一次，实参与返回值正确。
3. mutable 输入容器在调用前复制，fake client 的 mutation 不反向污染调用方。
4. 每个参数类型/边界失败均 fail closed，底层总调用数保持 0，错误不含非法值。
5. 八个 query 返回 None、RuntimeError unique secret 的失败路径均安全；cause/context 为 None。
6. constructor descriptor secret 失败安全；构造后目标属性替换不影响冻结 mapping。
7. KeyboardInterrupt/SystemExit/GeneratorExit 覆盖代表性方法并原样传播。
8. dangerous fake 即使具备订阅、下载、order/cancel，Adapter 也无这些 API且危险计数为 0。
9. 完整回归不少于 287 项，compileall、AST 安全扫描通过，完整输出保存。
10. 无 XtQuant import/真实访问/新增依赖；`live_trading_allowed=false`。

## Required Tests / Failure Injection

- constructor 八个 required method 的逐项 missing/non-callable，以及 descriptor unique secret/BaseException。
- 八个正常 mapping；两个 market-data 方法的全部默认值与非默认值；输入容器隔离。
- stock/field/code/market/period/time/count/bool/dividend 参数的类型与边界矩阵。
- 八个方法的 None 返回与普通异常；代表性 BaseException 原样传播。
- 异常图递归扫描确保 secret、参数值和 client repr 不可见。
- 构造后属性替换/危险 descriptor 不被重新解析。
- AST：生产无 assert、无 xtquant import、无 subscribe/download/order/cancel call，无动态 getattr/call。
- 完整 unittest、compileall；完整输出保存到指定 artifact。

## Allowed Files

Claude 只能新增或修改：

```text
src/tgrid/adapters/marketdata_readonly.py
src/tgrid/adapters/__init__.py
src/tgrid/risk/exceptions.py
src/tgrid/risk/__init__.py
src/tgrid/__init__.py
tests/unit/test_marketdata_readonly.py
README.md
work/reports/tests/G1-T003-test-output.txt
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
src/tgrid/adapters/qmt_readonly.py
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

不得安装依赖、启动/停止/连接 QMT、导入 xtquant、查询真实数据、添加订阅/下载/账号/交易能力。

## Deliverables

1. MarketData 查询只读 Adapter、异常、导出与 README 边界说明。
2. 完整单元测试和 `work/reports/tests/G1-T003-test-output.txt`。
3. 更新 Claude Gate、Implementation/Test/Questions 报告。
4. 不提交 commit；等待架构师独立 Review。

## Stop Condition

完成范围检查、测试并释放 Lease 后，原子设置：

```text
state: REVIEW_READY
owner: architect
iteration: 1
last_actor: claude
git_head_commit: a2f5fa3cb826e14a89bc478492f900d93d25b9fa
live_trading_allowed: false
```

然后停止修改。出现设计冲突、范围污染或无法保证只读边界时设置 `BLOCKED` 并停止。
