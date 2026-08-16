# TGrid 开发者说明

本文件面向需要修改、审计或扩展 TGrid 的开发者。普通使用者请优先阅读仓库根目录的 [`README.md`](../README.md)。

## 1. 开发文档入口

TGrid 的技术设计、Gate 验收和执行安全边界分散在几类文档中，各自承担不同职责：

- [`TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md`](../TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md)：策略、持仓模型、风险不变量、事件模型和总体架构的设计基线。
- [`docs/GATES.md`](GATES.md)：Gate 分阶段开发与验收说明。
- [`work/control/CURRENT_TASK.md`](../work/control/CURRENT_TASK.md)：当前唯一有效的实施/执行任务与授权范围。
- [`work/control/WORKFLOW_STATE.yaml`](../work/control/WORKFLOW_STATE.yaml)：当前 Gate、owner、authorized_next、审计基线和交易授权状态。
- [`work/gates/`](../work/gates/)：各阶段的实现证据、独立审计和运行手册。
- [`TGrid_双Agent协作与Gate验收协议_V1.0.md`](../TGrid_双Agent协作与Gate验收协议_V1.0.md)：协作与 Gate 审核规则。

公共交易执行内核位于 [`smhe00/qmt-execution-core`](https://github.com/smhe00/qmt-execution-core)。TGrid 当前生产组合固定使用经过独立审计的 Core 版本，具体 SHA 以 `pyproject.toml` 与 `work/control/WORKFLOW_STATE.yaml` 为准。

## 2. 当前执行架构

TGrid 自身负责策略和业务账本，公共 Core 负责安全执行生命周期：

```text
Strategy / TGrid
  ├─ Core Position / T-Lot / Daily Exposure
  ├─ signal / sizing / risk policy
  └─ business OrderIntent + Reservation
              │
              ▼
qmt-execution-core
  ├─ explicit execution state machine
  ├─ durable intent / crash recovery
  ├─ Runtime Authority
  ├─ per-(account,symbol) unresolved claim
  ├─ per-account shared BUY cash reservation
  ├─ MiniQMT runtime / session-id isolation
  └─ broker submit / cancel lifecycle
              │
              ▼
          MiniQMT / QMT
```

生产 shared runtime 的关键链路是：

```text
QMT binding
  → account_key
  → OS-derived canonical Account Runtime Authority
  → certified dedicated coordination DB
     (path + db_uuid + authority_id)
  → CoordinatedExecutionSession
  → TGrid ExecutionEngine
```

TGrid production builder 不允许调用方选择 `coordination_path` / `authority_root`，也不使用 `coordinator=` / `authority=` 注入绕过 Runtime Authority。低层注入仅允许出现在隔离测试中。

## 3. 核心安全不变量

开发时不要为了“跑通”而弱化以下规则：

1. `core_qty` 是长期底仓硬下限，T 模块不得卖穿。
2. V1 为 `ACCUMULATE`：低频做 T 采用先买后卖，不做裸卖。
3. broker side effect 前必须先有 durable execution intent。
4. Core coordination 必须先于 TGrid business sidecar，TGrid sidecar 必须先于 broker submit。
5. 同一 `(account_key, symbol)` 同时最多存在一个 unresolved execution lifecycle。
6. 同一账户的 BUY 使用 fresh broker cash，并扣除其他活跃 Core reservation 后原子授权。
7. `UNKNOWN`、`CANCEL_REJECTED`、unresolved `FAILED/QUARANTINED` 不允许 blind resend，也不得释放 claim/cash reservation。
8. Runtime Authority 缺失、损坏或 DB identity 不匹配时必须 fail closed；普通策略 runtime 不得自动重建 coordination domain。
9. callback 不直接修改策略/账本/订单状态，必须经过受控事件边界。
10. `live_trading_allowed=false` 时不得通过其他开关绕过 live gate。

## 4. 本地开发

要求 Python `>=3.9`。

```bash
pip install -e .
python -m tgrid --help
```

基础检查：

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m compileall -q src tests scripts
python scripts/capability_scan.py
```

涉及 qmt-execution-core 的改动，还应运行已安装 Core 的 release verifier：

```bash
qmt-execution-core verify
```

不要把真实账户 ID、真实本地路径、broker balance、Runtime Authority 文件或 coordination DB 提交到仓库。

## 5. 代码目录

```text
src/tgrid/        TGrid 生产源码
  strategy/       低频做T策略与价格/风控逻辑
  execution/      TGrid 业务执行编排与业务账本
  integrations/   QMT/Core/业务边界组合
  persistence/    SQLite schema、T-Lot、intent、reservation
  position/       Core Position 与持仓一致性

tests/unit/       单元与安全回归
scripts/          Gate / capability / evidence runners
config/           示例配置；真实本地配置不入库
docs/             长期说明文档
work/control/     当前任务与状态控制面
work/gates/       Gate 证据、审计、运行手册
```

## 6. 修改执行链路时的最低要求

任何涉及 `src/tgrid/integrations/`、`src/tgrid/execution/`、Runtime Authority、broker submit/cancel、recovery、reservation 或 state/finality 映射的修改，都应视为安全敏感改动：

1. 先冻结期望不变量；
2. 实现并补足 fail-closed / crash / ambiguous-state 测试；
3. 跑完整回归、compileall、capability scan；
4. 涉及 Core 时跑 formal verifier；
5. 由独立 reviewer 做 source-level audit，而不是只看测试绿灯；
6. 审计通过后才允许进入下一 Gate 或执行带 broker side effect 的验证。

当前实际授权范围始终以 [`work/control/CURRENT_TASK.md`](../work/control/CURRENT_TASK.md) 和 [`work/control/WORKFLOW_STATE.yaml`](../work/control/WORKFLOW_STATE.yaml) 为准，README 或历史 Gate 文档不能替代控制面授权。
