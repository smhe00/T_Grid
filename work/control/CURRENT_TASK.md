# Task G2-T001 — Offline Core Position Guard

## Goal

实现一个纯离线、不可变、fail-closed 的 Core Position 快照与卖出保护能力，精确表达设计中的持仓分解、
Core Floor、可用数量和卖出预留不变量；本任务只引入这一项主要能力。

## Iteration 2 Review Findings

Iteration 1 未通过。只修 `REV-G2T001-001..004`：

- T 模块当前会把 `StrategicExtraPosition` 当成可卖空间；必须把 Core 与 Strategic 都作为 T 模块不可退出
  的 protected position，并把卖出容量限制为 Open T-Lot 持仓。
- 报告声称复用 `SymbolConfig`，但生产实现没有导入或使用它；必须提供一个实际由
  `SymbolConfig.core_qty` 构造/绑定快照的最小受测路径，禁止调用者在该路径另传一份可能漂移的 core。
- `open_t_lots` 实际存的是股数而非 lot 数量；改成与设计 `OpenTLotPosition` 一致、无歧义的 quantity 名称。
- `src/tgrid/risk/__init__.py` 不在 Allowed Files；撤销该文件改动，不得扩大范围。

Iteration 2 仍为纯离线最小修复；禁止增加 Ledger、Reconciliation、OrderIntent、数据库或 QMT 能力。

## In Scope

- 在设计推荐的 `tgrid.position` 包中实现不可变 `PositionSnapshot`（或同等唯一公开模型）。
- 快照必须显式保存：`symbol`、Broker 总持仓、Core 持仓、StrategicExtra 持仓、Open T-Lot 持仓、
  QMT 可用数量 `can_use_qty`、已预留卖出数量 `reserved_sell_qty`。
- 精确验证 `BrokerPosition = CorePosition + StrategicExtraPosition + OpenTLotPosition`。
- 计算 `AvailableTQty = min(CanUseVolume, BrokerPosition - CoreQty) - ReservedSellQty`。
- 提供显式的 T 模块卖出校验，独立执行并区分：Core Floor、QMT 可用数量、卖出预留冲突。
- 最大化复用现有 `SymbolConfig` 和 `CoreFloorViolation`、`InsufficientAvailableVolume`、
  `SellReservationConflict`；仅在持仓分解/字段本身损坏没有合适现有异常时，新增一个最小明确的
  `RiskError` 子类。
- 用纯合成数据编写单元测试与 Failure Injection。

## Out of Scope

- T-Lot SQLite 表、Ledger 状态变化、Audit Log、Reconciliation、Crash Recovery、SAFE_MODE 状态机。
- OrderIntent、`client_order_key`、真实 Reservation 的创建/释放、ReservedCash。
- Target Ceiling 买入检查、策略信号、Adaptive Grid、LIFO 平仓选择。
- 任何 QMT/XtQuant 导入、连接、账号、行情、资产、持仓查询、下单、撤单、订阅或下载。
- 修改 reverse_repo；不得复制其 live 执行脚本或建立跨仓运行时依赖。
- CLI、配置 schema、数据库 migration、日志与 Event Queue 改动。

## Reuse Direction

- TGrid 内部：复用现有 `SymbolConfig` 和 risk exception 层；禁止创建第二套配置或异常根类型。
- reverse_repo：只读学习其 fail-closed、显式状态与“不以执行结果猜测意图”的模式。当前检索未发现可直接
  复用的 Core Position / T-Lot 领域模型，因此不得为了“复用”而依赖其 GC001 live 脚本。
- 本任务不新增 QMT Adapter；Gate 1 的只读 Adapter/Probe 保持不变。

## Allowed Files

- `src/tgrid/position/__init__.py`（新增）
- `src/tgrid/position/manager.py`（新增）
- `src/tgrid/risk/exceptions.py`（仅允许新增最小 Position invariant 异常）
- `src/tgrid/risk/__init__.py`（Iteration 2 仅允许撤销本任务超范围导出改动）
- `src/tgrid/__init__.py`（仅公开本任务批准的模型/异常）
- `tests/unit/test_position_manager.py`（新增）
- `work/reports/tests/G2-T001-test-output.txt`（新增完整测试证据）
- `work/gates/GATE_2/G2-T001_RESULT.md`（新增）
- `work/gates/GATE_2/CLAUDE_REPORT.md`（新增或更新）
- `work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md`
- `work/handoff/claude_to_architect/TEST_REPORT.md`
- `work/handoff/claude_to_architect/QUESTIONS.md`（仅确有问题时）
- `work/control/WORKFLOW_STATE.yaml`
- `work/control/CLAUDE_HEARTBEAT.md`
- `work/locks/WORKTREE_LEASE.yaml`（仅持有期间）

## Forbidden Files

- `TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md`
- `TGrid_双Agent协作与Gate验收协议_V1.0.md`
- `src/tgrid/integrations/**`、`src/tgrid/adapters/**`、`src/tgrid/probes/**`
- `src/tgrid/persistence/**`、既有 migration 与数据库文件
- `config/**`、`scripts/**`、`docs/**`、`README.md`
- `D:/gitee/miniQMT/reverse_repo/**` 与父仓库其他项目
- 任何真实/local 配置、日志、账号、业务数据或 QMT 路径

## Design References

- §4 第一原则：Core Position，尤其 `PositionAfterSell >= CoreQty` 与双重数量保护。
- §5 Position Manager：Broker = Core + StrategicExtra + OpenTLot。
- §21–22.1：Broker Authority、禁止静默对账、人工变化不得自动猜测。
- §34：INV-001、INV-005、INV-006、INV-008、INV-011、INV-012、INV-016。
- §37 Gate 2；本任务仅覆盖其中 Core Position Manager 的最小第一片。
- §50：`CorePositionGuard` 为最高优先级。

## Invariants

1. 所有数量必须是 `type(value) is int` 的 plain integer；拒绝 bool、float、string、int 子类和负数。
2. `symbol` 必须是非空 plain string；不得隐式 trim/normalize 后接受非法输入。
3. 快照创建时持仓分解必须精确相等；不一致立即显式失败，不修改、不猜测为 Strategic/T-Lot。
4. 快照必须 frozen；构造完成后任何字段均不可修改。
5. Broker 持仓低于 Core 时立即 `CoreFloorViolation`；可用数量结果不得为负。
6. T 卖出量必须是正的 plain int，并依次通过独立 Core Floor、`can_use_qty` 与 reservation 检查。
7. Core/Strategic 数量不得被 T 模块卖出校验重新分类或修改。
8. 不使用 Python `assert` 承担生产安全；未知输入 fail closed。
9. `live_trading_allowed=false`；生产代码不得导入 XtQuant 或调用 order/cancel/download/subscribe。

## Acceptance Criteria

- 唯一公开 Position 模型为 immutable snapshot，不暴露可变内部集合或 mutation API。
- 合法样例 `broker=700/core=600/strategic=0/open_t=100` 精确通过。
- `broker != core + strategic + open_t` 的任意方向偏差显式失败且无自动修复。
- `available_t_qty` 对 Core headroom、QMT can-use 与已有 reservation 取正确最小边界。
- `validate_t_sell`（或同等显式 API）分别抛出三种已有异常，测试能证明错误优先级和互不替代。
- API 不返回/创建 OrderIntent，不执行 Reservation mutation，不访问数据库/QMT。
- 包级导出最小、明确；不得把内部 helper 或 raw state 暴露为公共运行入口。
- 既有 475 项测试全部保持通过。

## Required Tests

- 合法分解、零 Core/零 T-Lot、StrategicExtra 非零。
- frozen/不可变验证。
- 每个数量字段：负数、bool、float、string、int subclass。
- 空 symbol、仅空白 symbol、string subclass。
- Broker 比分解多/少；Broker 低于 Core；reservation 大于未预留可卖数量。
- 公式边界：can-use 更小、core headroom 更小、恰好全部预留、恰好可卖、超出 1 股。
- 卖出参数：0、负数、bool、float、string、int subclass。
- Core Floor、InsufficientAvailableVolume、SellReservationConflict 各自独立触发。
- AST 扫描：本任务生产文件无 `ast.Assert`、XtQuant import、order/cancel/download/subscribe 调用。
- 完整执行：`python -m unittest discover -s tests -p "test_*.py" -v` 与
  `python -m compileall -q src tests`。

## Failure Injection

- 构造一个看似为 int 的恶意 int subclass，确认不执行其自定义转换/字符串方法且被拒绝。
- 传入异常 `__str__` 的非法 symbol/int-like 对象，确认错误路径不调用 `str/repr` 泄漏或执行副作用。
- 依次构造可同时违反多个卖出边界的快照/数量，确认 Core Floor 最高优先级，其次 QMT 可用量，再次
  reservation conflict；任何失败均不改变快照。
- 尝试使用正常公开方式修改字段，确认被冻结且失败后值不变。

## Deliverables

- 上述生产代码与单元测试。
- 完整 `G2-T001-test-output.txt`。
- 更新 Implementation Report、Test Report、Claude Report 和 G2-T001 Result，逐条映射设计/不变量。
- 报告单列 `Reuse Evidence`：实际复用了哪些 TGrid 类型/异常；为何 reverse_repo 无等价领域模型而未复制
  live 代码。
- 不提交 commit；由 Desktop ChatGPT 独立复核后决定验收提交。

## Stop Condition

完成后删除 Lease，设置：

```text
state = REVIEW_READY
owner = architect
task_id = G2-T001
iteration = 1
```

然后停止写入并等待。若任何范围或设计冲突无法在允许文件内解决，设置 `BLOCKED`，不要扩大范围。
