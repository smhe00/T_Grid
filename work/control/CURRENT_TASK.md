# Current Task — G1-T001

## Task Name

Gate 1 QMT 只读环境与 API 边界调查

## Objective

在不连接 QMT、不读取账号/行情、不修改生产代码的前提下，确定本机可用于 TGrid 的 Python/XtQuant
运行环境、Gate 1 所需显式输入及只读 API allowlist，生成可审计的环境报告，为后续真实只读接入任务
消除环境和权限歧义。

## Scope

1. 记录当前 Python 可执行文件、版本和 `sys.path` 来源摘要；用 `importlib.util.find_spec` 检查
   `xtquant`、`xtquant.xtdata`、`xtquant.xttrader`、`xtquant.xttype` 是否可用。
2. 只检查 PATH/Python launcher 和仓库内已有文档或脚本引用的解释器/API；不得递归扫描整盘。
3. 若模块可导入，只做 `inspect`/属性存在性/签名等离线反射，不创建 trader、不调用 connect/start、
   不订阅、不查询任何数据。
4. 建立 Gate 1 只读 capability matrix：连接、行情、资产、持仓、委托、成交、断线识别、企业行动/
   复权、交易日历/交易时段、行情新鲜度；每项标记 `AVAILABLE_UNVERIFIED`、`MISSING` 或
   `NEEDS_EXPLICIT_INPUT`，不得把静态存在误报为真实可用。
5. 明确后续真实只读验证所需的用户/环境输入，但不得在报告中复制完整账号 ID、凭据或敏感配置。
6. 定义下一任务可使用的最小只读 allowlist 和明确 forbidden list，提交调查报告等待架构师 Review。

## Out of Scope

- 修改或新增 `src/**`、`tests/**`、`config/**`、`pyproject.toml`、README。
- 安装/升级/下载 XtQuant、Python 或任何依赖；不得调用 pip/conda。
- 启动、停止、重启或操作 MiniQMT/QMT 客户端或任何后台进程。
- 创建 `XtQuantTrader`、调用 `connect/start/subscribe`，读取行情、账户、持仓、委托或成交。
- 读取、猜测或复用父项目中的真实账号 ID、QMT userdata 路径、令牌、密码或本地私密配置。
- `order_stock`、`cancel_order` 及任何下单/撤单/改单/策略执行。
- live trading；`live_trading_allowed` 必须保持 `false`。

## Design References

- 设计 §36：Gate 1 只允许 QMT 连接和只读查询；禁止 `order_stock`、`cancel_order`。
- 设计 §19：所有 QMT 调用必须封装在 Adapter 层，业务代码不得直接调用 trader。
- 设计 §3.1：未来 callback 只能 enqueue，不能直接修改业务状态。
- 协作协议 §18、§22、§29–§32：证据、fail-closed、Git/Lease/状态机要求。
- Gate 0 最终裁决：`work/gates/GATE_0/RESULT.md`。

## Read-only API Boundary to Assess

候选 allowlist（只做静态调查，本任务不得调用）：

```text
XtQuantTrader.start
XtQuantTrader.connect
XtQuantTrader.subscribe
XtQuantTrader.query_stock_asset
XtQuantTrader.query_stock_positions
XtQuantTrader.query_stock_orders
XtQuantTrader.query_stock_trades
XtQuantTrader.stop
xtdata.connect
xtdata.get_full_tick
xtdata.get_market_data / get_market_data_ex
xtdata.subscribe_quote / unsubscribe_quote
```

无条件 forbidden：

```text
order_stock
order_stock_async
cancel_order_stock
cancel_order_stock_async
cancel_order
任何名称或语义等价的报单、撤单、改单方法
```

`query_stock_orders` 是只读查询，不得因名称包含 order 而误分类为报单。

## Invariants

1. Gate 1 仍是严格 read-only；调查本身不建立 QMT 连接。
2. 不访问真实账号、真实行情或私密配置，不记录敏感值。
3. 静态模块/API 存在只表示“候选可用”，不表示连接或数据验收通过。
4. 缺失 XtQuant 环境时 fail closed：记录事实与所需输入，不安装、不猜测路径。
5. 不修改 Gate 0 已验收代码和测试。
6. `live_trading_allowed=false`，禁止 API 清单不可弱化。

## Acceptance Criteria

1. `docs/GATE_1_ENVIRONMENT_REPORT.md` 记录实际解释器、Python 版本、模块发现结果和调查方法。
2. 报告包含 capability matrix，并区分静态存在、环境缺失、需要显式输入和尚未真实验证。
3. 报告列出后续只读连接所需最小输入：兼容 XtQuant 的 Python/启动方式、QMT userdata 路径、
   账号类型和经脱敏的账号选择、只读验证标的，以及客户端运行前提；不得填写或猜测真实值。
4. 报告给出精确 allowlist/forbidden list，`order_stock`/撤单系列明确禁止。
5. 若当前解释器无 `xtquant`，结论必须明确为环境未就绪，不得声称 Gate 1 接入成功。
6. 完整命令与输出保存到 `work/reports/tests/G1-T001-environment-probe.txt`，敏感路径可保留到解释器/
   包位置，但账号、凭据和真实私密配置必须脱敏或不读取。
7. 不连接 QMT、不启动进程、不安装依赖、不修改生产代码/测试；Git diff 只含 Allowed Files。
8. 完整 Gate 0 回归无需重跑；必须执行 `git diff --check -- T_Grid` 和生产 AST 禁止交易 API 扫描，
   确认本任务没有弱化安全边界。
9. 不提交 commit；完成后释放 Lease，进入 `REVIEW_READY`。环境缺失可以作为调查结论，不构成本任务
   BLOCKED；只有无法可靠完成调查或发现范围/安全冲突时才使用 `BLOCKED`。

## Required Checks / Failure Injection

- 当前解释器 `find_spec('xtquant')` 缺失路径。
- 可用解释器候选中的 import failure 必须只报告异常类型/安全摘要，不打印 traceback 或环境变量。
- 静态 API 检查不得实例化 trader；在报告中证明未发生 connect/query/subscribe。
- AST 扫描 `src/tgrid/**/*.py`：继续无 `xtquant` import、无 `order_stock`/撤单调用、无 `assert`。
- Git HEAD/范围/Lease 检查。

## Allowed Files

Claude 只能新增或修改：

```text
docs/GATE_1_ENVIRONMENT_REPORT.md
work/reports/tests/G1-T001-environment-probe.txt
work/gates/GATE_1/CLAUDE_REPORT.md
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md
work/handoff/claude_to_architect/TEST_REPORT.md
work/handoff/claude_to_architect/QUESTIONS.md
work/control/CLAUDE_HEARTBEAT.md
work/control/WORKFLOW_STATE.yaml
```

`WORKFLOW_STATE.yaml` 只允许更新 worker state/owner/iteration/last_actor/last_update/git_head_commit/notes
和必要 escalation 字段；不得修改 Gate、基线、设计路径或 `live_trading_allowed`。

## Forbidden Files

除 Allowed Files 外的全部文件，尤其：

```text
src/**
tests/**
config/**
README.md
pyproject.toml
work/control/CURRENT_TASK.md
work/control/ARCHITECT_HEARTBEAT.md
work/gates/GATE_0/**
work/gates/GATE_1/TASK.md
work/gates/GATE_1/ARCHITECT_REVIEW.md
work/gates/GATE_1/RESULT.md
父目录 D:/gitee/miniQMT 中 T_Grid 之外的全部文件
```

## Deliverables

1. `docs/GATE_1_ENVIRONMENT_REPORT.md`。
2. `work/reports/tests/G1-T001-environment-probe.txt` 完整安全输出。
3. Gate 1 Claude Report、Implementation/Test/Questions 报告。
4. 后续只读接入的输入清单与安全边界建议；不创建连接代码。

## Stop Condition

完成调查、验证范围且释放 Lease 后，原子设置：

```text
state: REVIEW_READY
owner: architect
iteration: 1
last_actor: claude
git_head_commit: 34169aa9873af9ae7f94994ed7301956d491585d
live_trading_allowed: false
```

然后停止修改。若出现范围污染、安全边界冲突或无法形成可信报告，设置 `BLOCKED` 并停止。
