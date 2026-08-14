# Task G0-T001 — 项目骨架与配置安全基础

## Goal

建立可安装、可测试、无任何 QMT 或交易能力的 Python 项目骨架，并实现 Gate 0 的配置读取、核心配置模型和显式风险异常基础。

本任务只引入一个主要能力：**可靠、fail-closed 的配置基础**。

## In Scope

1. 建立 TGrid 本地 Python 包骨架和项目元数据。
2. 从调用方显式传入的 YAML 路径读取配置；禁止隐式读取真实本地配置。
3. 实现最小且有类型边界的配置模型：全局配置、证券配置和根配置。
4. 只允许 V1 的 `ACCUMULATE` 模式。
5. 实现 Gate 0 所需的显式配置/风险异常类型。
6. 提供不含账号、资金或真实环境信息的 `config/config.example.yaml`。
7. 编写标准库 `unittest` 测试，覆盖成功路径与失败注入。
8. 提供最小 README，说明当前仅处于 Gate 0、没有 QMT/行情/交易能力。

本任务允许将 `PyYAML` 作为唯一的配置解析第三方依赖，并允许为运行测试在当前 Python 环境中安装该依赖；不得自行实现不完整的 YAML 解析器。

## Out of Scope

- SQLite schema、migration 和持久化实现（后续 Gate 0 任务）。
- logging 系统（后续 Gate 0 任务）。
- CLI（后续 Gate 0 任务）。
- Event Queue（后续 Gate 0 任务）。
- Position Manager、T-Lot Ledger、Order Intent、Reservation。
- ATR、VWAP、Adaptive Grid 或任何策略计算。
- QMT/XtQuant import、连接、行情、账户、持仓、委托、成交、下单或撤单。
- SimBroker、dry-run、shadow/live execution。
- 修改两份权威 Markdown 文档或架构语义。
- Git commit、push 或任何外部操作。

## Allowed Files

Claude 只能新增或修改：

```text
pyproject.toml
.gitignore
README.md
config/config.example.yaml
src/tgrid/__init__.py
src/tgrid/config.py
src/tgrid/models.py
src/tgrid/risk/__init__.py
src/tgrid/risk/exceptions.py
tests/__init__.py
tests/unit/__init__.py
tests/unit/test_config.py
tests/unit/test_models.py
work/control/WORKFLOW_STATE.yaml
work/control/CLAUDE_HEARTBEAT.md
work/locks/WORKTREE_LEASE.yaml
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md
work/handoff/claude_to_architect/TEST_REPORT.md
work/handoff/claude_to_architect/QUESTIONS.md
work/gates/GATE_0/CLAUDE_REPORT.md
work/reports/tests/G0-T001-test-output.txt
```

`WORKTREE_LEASE.yaml` 只能在开始时获取、结束时释放；完成交接后该文件应不存在。

## Forbidden Files

明确禁止修改：

```text
TGrid_双Agent协作与Gate验收协议_V1.0.md
TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md
work/control/CURRENT_TASK.md
work/control/ARCHITECT_HEARTBEAT.md
work/gates/GATE_0/TASK.md
work/design/**
父目录 D:/gitee/miniQMT 中 T_Grid 之外的全部文件
```

除 Allowed Files 外的任何源代码或控制文件也禁止修改。

## Design References

- 设计文档 §0：默认 `LIVE_TRADING = false`
- §2：V1 禁止范围
- §3.1：单一事件队列原则（本任务不实现，只避免冲突设计）
- §18.1：`lot_size` / `price_tick` 与数量价格合法性
- §32：配置结构
- §34：INV-009、INV-010、INV-011
- §33、§35、§44、§51：目录、Gate 0 范围与 Claude 纪律
- 协作协议 §7–§10、§22、§24、§29–§32

## Invariants

1. `live_trading` 缺省值必须为 `false`；本任务不得产生任何执行路径。
2. 不得 import `xtquant`，不得出现 `order_stock`、`cancel_order` 或券商调用。
3. 配置异常必须显式失败，不得静默采用可能扩大风险的值。
4. 生产风险异常不得依赖 Python `assert`。
5. 只允许 `ACCUMULATE`；`NEUTRAL`、`DISTRIBUTE` 和未知模式必须拒绝。
6. 数量配置使用严格整数语义，不能把 `bool` 当作整数接受。
7. 价格/比例配置必须为有限数值，拒绝 NaN、Infinity、零值或负值（允许为零的字段必须在模型中明确列出）。
8. `t_unit > 0`、`lot_size > 0` 且 `t_unit % lot_size == 0`。
9. `price_tick > 0`、`core_qty >= 0`、`target_qty >= core_qty`、`max_t_lots >= 1`。
10. 未知字段、缺失必填字段和错误根结构必须 fail closed。

## Acceptance Criteria

1. `pyproject.toml` 定义独立的 `tgrid` 包，Python 下限不得高于父项目当前的 `>=3.9`；本任务运行时依赖仅允许 `PyYAML`，并说明用途。
2. `import tgrid` 无文件、网络、QMT、数据库或日志副作用。
3. 配置加载函数只接收显式文件路径，返回有类型的根配置对象。
4. 示例配置至少包含 `0700.HK` 和 `000333.SZ`，并为每个证券显式提供 `lot_size`、`price_tick`；数量只作示例，代码不得写死证券或数量。
5. 全局配置至少支持设计中的数据库路径、日志目录、5m 周期、订单超时、开收盘过滤、波动暂停参数、`minimum_cash_buffer` 与 `live_trading`。
6. 证券配置至少支持 `enabled`、`mode`、`core_qty`、`target_qty`、`t_unit`、`lot_size`、`price_tick`、`max_t_lots`、`max_t_capital`、anchor/ATR/grid/exit 参数。
7. 配置解析对未知字段和不合法类型/范围给出包含字段路径的确定性错误。
8. 风险异常至少有清晰基类，并包含后续所需的 `CoreFloorViolation`、`InsufficientAvailableVolume`、`SellReservationConflict`、`CashReservationConflict`；本任务不实现触发它们的交易逻辑。
9. 所有新增测试通过；测试不得依赖 QMT、网络、真实账号或工作站专属路径。
10. Git diff/status 仅包含 Allowed Files 以及任务开始前已有的架构师控制文件。

## Required Tests

至少覆盖：

- 示例配置成功加载。
- 缺省 `live_trading` 为 `false`。
- 两个示例市场的 `lot_size` / `price_tick` 可分别配置，未写死 100 股。
- 非 `ACCUMULATE` 模式被拒绝。
- `t_unit` 不能被 `lot_size` 整除时被拒绝。
- 零/负 `price_tick` 被拒绝。
- `target_qty < core_qty` 被拒绝。
- `max_t_lots < 1` 被拒绝。
- bool 冒充整数被拒绝。
- NaN/Infinity 被拒绝。
- 未知字段、缺失字段、错误根结构被拒绝。
- 风险异常类型可被明确捕获，且实现中不使用 `assert` 承担安全校验。

必须实际运行：

```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
```

## Failure Injection

至少注入并记录：

1. 文件不存在。
2. YAML 语法损坏。
3. 根节点不是 mapping。
4. 未知键。
5. `t_unit: true`。
6. `price_tick: .nan` 或等价非有限数值。
7. 非法交易模式。

所有场景必须抛出明确、可审计的配置异常；不得回退到宽松默认值继续运行。

## Deliverables

1. Allowed Files 中的实现与测试。
2. `work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md`。
3. `work/handoff/claude_to_architect/TEST_REPORT.md`，包含实际命令、逐项结果和失败输出。
4. `work/reports/tests/G0-T001-test-output.txt`，保存完整测试输出。
5. `work/gates/GATE_0/CLAUDE_REPORT.md`，明确 Gate 0 尚未完成，只汇报 G0-T001。
6. 若无问题，`QUESTIONS.md` 写 `NONE`；发现设计歧义则写入并停止猜测相关部分。

## Stop Condition

完成并验证后，Claude 必须：

1. 确认 diff 范围。
2. 将 `WORKFLOW_STATE.yaml` 原子更新为：
   - `state: "REVIEW_READY"`
   - `owner: "architect"`
   - 保持 `gate: 0`、`task_id: "G0-T001"`
   - 更新 `last_actor`、`last_update` 和 `git_head_commit`（未 commit 时保持空并在 notes 说明）。
3. 释放并删除 `work/locks/WORKTREE_LEASE.yaml`。
4. 停止修改，等待 Desktop ChatGPT 独立 Review。
