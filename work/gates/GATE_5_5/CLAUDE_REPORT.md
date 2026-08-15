# Gate 5.5 / Claude Report — Live Broker Adapter (Pre-Live Only)

## Status

`REVIEW_READY (ITERATION 10)` — Audit Node B 对状态机移植扩展的复审
（`NODE_B_STATE_MACHINE_PORT_REVIEW_ITER9_20260815.md`，audit commit `5403829`）
判定 **CHANGES_REQUIRED（NODEB-SM9-001..005，均 P0/P1）**，Iteration 10 已全部
修复（SELF_CERTIFIED），按审计要求移交 `AUDIT_NODE_B_STATE_MACHINE_PORT` 复审。
**基线 Gate 5.5 PASS_PRELIVE（`e252847`）保持接受**；本任务未调用任何真实
order/cancel；`live_trading_allowed=false` 保持。

授权来源：Gate 5 Node A PASS（`4c1cc8c`）+ Audit Node B FINAL PASS_PRELIVE
（`e252847`）+ 用户 2026-08-15 显式授权移植 reverse_repo 完整状态机 + 形式验证器
+ 独立审计 Iteration 9 修复要求（`5403829`）。

参考实现（QMT 行为基线）：`https://github.com/smhe00/reverse_repo`
pinned commit `c9ecc701d9b1c47d6a8d03539b482368741204a3`。

## Iteration 10 — NODEB-SM9-001..005 修复（SELF_CERTIFIED）

| # | 级别 | 修复 |
|---|------|------|
| SM9-001 | P0 | **状态机/journal/互斥锁接入可信生产工厂**：`build_live_session()` 从校验后的数据库路径派生 journal（`tgrid-execution-<trade_date>.json`）与执行锁（`tgrid-execution.lock`）并**无条件**传入 `build_live_stack`；构造后校验 `stack.journal`/`stack.execution_lock` 非空（无静默 opt-out，缺失即 `LiveSessionError`）。双环境生产形态 fake 测试（simulation + live）证明栈携带完整执行权威 |
| SM9-002 | P0 | **锁先于 journal 生命周期 + 释放后永久禁用**：`ExecutionJournal` 改为**惰性初始化**（构造不读不写）；`LiveStack.activate()` 先获取执行锁，再 `load_or_initialize` + `_attach_execution_authority`，输者进程**绝不触碰共享 journal**（跨进程 FI：journal 字节不变）；`release_execution_lock()` 释放后调用 `engine.block_permanently()` —— 永久块**不可被 reconcile 清除**（FI：释放后新订单被拒、对账后仍被拒） |
| SM9-003 | P0 | **实现-模型事件精化**：(A) `send_*` 不再自产 TRIGGER/SNAPSHOT_OK——新增 `LiveStack.prepare_snapshot(evidence=...)` 可信 preflight API，证据**结构化绑定**进 journal 转移（`details.evidence`），未 READY 拒发（FI）；(B) poll/cancel 事件**按机器状态族分派**——CANCEL_PENDING 下 pending→`CANCEL_STILL_PENDING`、终态→`CANCEL_TERMINAL`，ORDER_ACTIVE 下（含自发撤单）终态→`ORDER_TERMINAL`（FI）；(C) `_advance_recovery_outcome` 对**多重/混合未决** fail-closed（>1 非终态匹配或 >1 故事族 → RECOVERY_AMBIGUOUS → SAFE_HALT + SAFE_MODE，FI）；(D) **区分 `SUBMIT_REJECTED`（确定性拒绝）与 `SUBMIT_EXCEPTION`（歧义）**：新增 `BrokerRejectedError`（port），`LiveBrokerError` 与 `BrokerOrderRejectedError` 归入其下；确定拒绝 → SUBMIT_REJECTED → SAFE_HALT + intent REJECTED + reservation 释放（FI） |
| SM9-004 | P0 | **持久化 intent remark 为唯一恢复权威**：`recover_unknown_submission` **移除 caller remark 覆盖参数**（FI：传入 remark 抛 TypeError；恢复只按 `intent.order_remark` 反查） |
| SM9-005 | P1 | **验证源绑定 fail-closed + 完整 manifest**：`execution_source_sha256()` 对缺失保护文件**抛 `ExecutionSourceIntegrityError`**（不再跳过）；manifest 扩展至 **14 个安全关键源**（+store/models/port/live_session/live_broker_adapter/daily_exposure/exposure_store）；manifest 完整性 FI（缺失/删除文件 → 验证失败；必需文件集合断言） |

### 验证产物（可复算）

```text
verify_state_machines():
  reachable_abstract_states : 39   (不变 — 机器语义未被本轮改动)
  reachable_transitions     : 115
  unreachable_states        : 0 / unreachable_transitions: 0
  states_without_terminal_path : 0 / invariant_violations: 0
  transition_spec_sha256    : 7d9959dd323745e2...  (不变)
  execution_source_sha256   : 0f5d3ca63e287eac...  (14 个保护源文件真实内容绑定)
  execution_source_commit   : None (运行树无 .git；内容哈希为持久完整性锚)
```

### Evidence

- 回归：`python -m unittest discover -s tests -p "test_*.py"` → **1009 tests OK**
  （较 998 新增 11：manifest 完整性 2、remark 权威 1、可信 preflight 1、
  poll/cancel 状态族 2、确定性拒绝 1、锁先于 journal 1、释放后永久禁用 1、
  恢复多重 fail-closed 1、惰性 journal 1）。
- `python -m compileall -q src tests scripts` → exit 0。
- 修改：`port.py`（BrokerRejectedError）、`live_broker_adapter.py`、
  `executor.py`、`live_bootstrap.py`、`live_session.py`、`execution_journal.py`、
  `statemachine.py`（manifest + ExecutionSourceIntegrityError）、
  `execution/__init__.py`、`tgrid/__init__.py`、`test_execution_statemachine.py`、
  `test_live_bootstrap.py`。
- 诚实声明：Iteration 10 修复为 SELF_CERTIFIED，按审计要求移交
  `AUDIT_NODE_B_STATE_MACHINE_PORT` 独立复审；未获独立 PASS 前不声称扩展通过；
  真实资金 Gate 6/7 仍 BLOCKED。

## Iteration 9 — ExecutionMutex + SUBMIT_UNKNOWN remark 反查恢复（SELF_CERTIFIED）

完成 reverse_repo 移植剩余两项能力：

1. **`ExecutionMutex` 跨进程执行互斥**（`src/tgrid/execution/execution_mutex.py`，
   reverse_repo `repo_execution_core.ExecutionMutex` 原样移植）：文件锁
   （Windows `msvcrt.locking` LK_NBLCK / POSIX `fcntl.flock` LOCK_EX|LOCK_NB）、
   超时轮询（默认 try-once）、锁文件写入 pid+时间戳、进程退出由 OS 自动释放。
   `build_live_stack(execution_lock_path=...)` 可选开启；
   `LiveStack.activate()` **先于任何状态变更获取锁**，争用 → `LiveBootstrapError`
   fail-closed（同一交易日最多一个执行进程）；`release_execution_lock()` 幂等释放。
2. **`ExecutionEngine.recover_unknown_submission()`**（reverse_repo
   `_recover_unknown_submission` 移植）：`send_buy` 异常落入 SUBMIT_UNKNOWN 后，
   按**持久化 intent 的 order_remark 反查全部 broker 订单**（strict query，
   None ≠ 空成功）：
   - 唯一匹配且 symbol/side 一致 → 按 broker 状态分类
     `RECOVERED_ACTIVE`（SUBMITTED/PARTIAL）/ `RECOVERED_CANCEL_PENDING`
     （CANCEL_REQUESTED）/ `RECOVERED_TERMINAL`（FILLED/CANCELED/REJECTED，
     终态释放 reservation）；
   - **0 匹配 → `RECOVERED_NO_MATCH` → SAFE_HALT，禁止自动重发**（异常前
     订单可能已到达 broker）；
   - 查询失败 / 多匹配 / 身份不一致 / 未知状态 → `RECOVERY_AMBIGUOUS` →
     SAFE_HALT + SAFE_MODE（fail-closed，绝不静默降级）。
3. **journal 驱动崩溃恢复**：`LiveStack.activate()` 按**加载的机器状态**选择
   启动事件——全新 journal（NEW）→ BEGIN→PREFLIGHT_OK；**崩溃/中断恢复**
   （PREFLIGHT/WAIT_TRIGGER/SNAPSHOT/READY/INTENT/SUBMIT_UNKNOWN/
   ORDER_ACTIVE/CANCEL_PENDING/RECONCILE）→ **RESTART→RECOVERY**；
   终态 journal（DONE/SKIPPED/SAFE_HALT）→ `LiveBootstrapError` fail-closed
   （机器无出边，拒绝重复激活）。启动对账后按 reconcile 结果驱动机器出口：
   MATCHED 非终态 → RECOVERY_ACTIVE/CANCEL_PENDING，MATCHED 终态 →
   RECOVERY_TERMINAL，干净恢复 → RECOVERY_CLEAR。

### 验证产物（可复算）

```text
verify_state_machines():
  reachable_abstract_states : 39   (不变 — 机器语义未被本轮改动)
  reachable_transitions     : 115
  unreachable_states        : 0 / unreachable_transitions: 0
  states_without_terminal_path : 0 / invariant_violations: 0
  transition_spec_sha256    : 7d9959dd323745e2...  (不变)
  execution_source_sha256   : 92118bb141733140...  (绑定 7 个执行源文件真实内容)
  execution_source_commit   : None (运行树无 .git；内容哈希为持久完整性锚)
```

### Evidence

- 回归：`python -m unittest discover -s tests -p "test_*.py"` → **998 tests OK**
  （较 980 新增 18：ExecutionMutex 6、SUBMIT_UNKNOWN 反查恢复 9、LiveStack
  锁串行化 1、journal 崩溃恢复重启 1、终态 journal 拒绝激活 1）。
- `python -m compileall -q src tests scripts` → exit 0。
- 新增：`src/tgrid/execution/execution_mutex.py`；修改：`executor.py`、
  `live_bootstrap.py`（崩溃恢复启动事件 + 恢复出口分类）、`statemachine.py`
  （EXECUTION_SOURCE_FILES +1）、`execution/__init__.py`、`tgrid/__init__.py`、
  `tests/unit/test_execution_mutex.py`（新增）、`test_execution_statemachine.py`、
  `test_live_bootstrap.py`。
- 诚实声明：状态机移植为**新能力**，未经 Audit Node B 复审，不取代 PASS_PRELIVE；
  真实资金 Gate 6/7 仍 BLOCKED，须 Node B 复审 + 用户显式授权。

## Iteration 8 — reverse_repo 状态机 + 形式验证器移植（SELF_CERTIFIED）

新增 **TGrid 单状态机**（14 状态：NEW/PREFLIGHT/RECOVERY/WAIT_TRIGGER/SNAPSHOT/
READY/INTENT/SUBMIT_UNKNOWN/ORDER_ACTIVE/CANCEL_PENDING/RECONCILE/DONE/SKIPPED/
SAFE_HALT）+ 9 项 SafetyFacts 不变量 + `advance()` 逐事件事实更新 +
`verify_state_machines()` 形式验证器（BFS 不动点、sha256 绑定），
与 **ExecutionJournal**（schema v2、strategy+trade_date 三元校验、temp+fsync+
os.replace 原子写、历史≤500、`journal_matches_verification` 绑定）成对接入
`ExecutionEngine`（send/poll/timeout 驱动机器事件）与 `LiveStack`（journal_path
可选开启、activate 驱动 BEGIN→PREFLIGHT_OK→RECOVERY_CLEAR/AMBIGUOUS）。

### 验证产物（可复算）

```text
verify_state_machines():
  reachable_abstract_states : 39
  reachable_transitions     : 115
  declared_states           : 14   (declared_phase_event_edges 53)
  terminal_abstract_states  : 16
  unreachable_states        : 0
  unreachable_transitions   : 0
  states_without_terminal_path : 0
  invariant_violations      : 0
  transition_spec_sha256    : 7d9959dd323745e2...
  execution_source_sha256   : c0d84be841f1987b... (绑定 6 个执行源文件真实内容)
  execution_source_commit   : None (运行树无 .git；内容哈希为持久完整性锚)
```

证明的不变量：提交须环境/账户已核实；提交须对账后 broker 快照；提交须现金/行情
已核实；外部订单须持久化 intent；完成态不含未决订单；未决订单不得回到 ready；
每个可达非终态可达终态；每个声明状态/转移可达。

### 生产 fail-closed 绑定

`LiveStack.activate()`（state-machine 模式）在 BEGIN 前执行
`_ensure_journal_verification()`：全新 journal（尚无绑定哈希）自动绑定当前构建；
**已绑定但哈希与当前 transition spec / 执行源不匹配 → `LiveBootstrapError`**
（绝不静默重绑），显式 `bind_machine_verification()` 是唯一受认可的恢复路径
（reverse_repo "代码变更使旧 journal 失效" 语义）。

### Evidence

- 回归：`python -m unittest discover -s tests -p "test_*.py"` → **980 tests OK**
  （较 957 新增 23：形式验证器、快照严格 schema、journal 生命周期/绑定/损坏拒绝、
  engine 状态机集成、LiveStack 状态机驱动 + fail-closed 构建失配）。
- `python -m compileall -q src tests scripts` → exit 0。
- 新增：`src/tgrid/execution/statemachine.py`、`execution_journal.py`；
  修改：`executor.py`、`live_bootstrap.py`、`tgrid/__init__.py`、
  `tests/unit/test_execution_statemachine.py`、`tests/unit/test_live_bootstrap.py`。
- 诚实声明：状态机为**新能力**，未经 Audit Node B 复审，不取代 PASS_PRELIVE；
  真实资金 Gate 6/7 仍 BLOCKED，须 Node B 复审 + 用户显式授权。

## NODEB-RR6-001..003 Closure（SELF_CERTIFIED）

| # | 级别 | 修复 |
|---|------|------|
| RR6-001 | P0 | **无任何 engine 可达 API 接受调用方提供的 reconciliation 结果作为清除权威**：`ExecutionEngine.reconcile_and_clear_safe_mode()` 自身用 engine store+broker 执行权威 `reconcile_open_intents`（伪造 `MATCHED` 对象无法清除 SAFE_MODE）；未决/UNKNOWN fail-closed、reservation 保留；顺带修复 recovery 不再把已按 remark 匹配的 broker 订单重复报为 UNMATCHED（跟踪已匹配 broker order ids） |
| RR6-002 | P0 | 桥**持久化生产 session 解析出的精确 `SECURITY_ACCOUNT` + `ACCOUNT_STATUS_OK` 常量**（不再依赖未验证默认值；`build_live_session` 把解析常量经 `build_live_stack` 传入桥）；`_verify_bound_account_healthy()` 要求 **id + type + status 精确匹配**；FI：正确 id 但错误 type、正确 id/type 但异常 status、非默认注入常量成功、未绑定常量 fail-closed |
| RR6-003 | P1 | **移除自指 `git_head_commit`**；改用非自指字段 `implementation_commit` + `handoff_parent_commit` + `handoff_metadata_parent`，均记录精确 GitHub SHA（不再把实现 SHA 标记为分支 head） |

## Evidence

- 回归（Iteration 10，最新）：`python -m unittest discover -s tests -p "test_*.py"`
  → **1009 tests OK**；`python -m compileall -q src tests scripts` → exit 0。
- Iteration 9：**998 tests OK**；Iteration 8：**980 tests OK**；
  Iteration 7（RR6 关闭）：**957 tests OK**；capability 扫描：真实
  `order_stock`/`cancel_order_stock` 调用点 **桥内 2 处（白名单）、桥外 0 处**；
  `RESULT: PASS`。
- 测试文件：`test_xtquant_bridge.py`（account-health FI）、`test_live_bootstrap.py`
  （SAFE_MODE 伪造结果 FI、LiveStack 状态机 + fail-closed journal 绑定 +
  执行锁串行化 + 锁先于 journal + 释放后永久禁用 + 恢复多重 fail-closed +
  生产 session 执行权威）、`test_execution_mutex.py`（ExecutionMutex 跨进程互斥）、
  `test_execution_statemachine.py`（形式验证器/快照/journal/engine 集成 +
  SUBMIT_UNKNOWN remark 反查恢复 + 可信 preflight + poll/cancel 状态族 +
  确定性拒绝 + manifest 完整性）、`test_execution_live_chain.py`、
  `test_execution.py`。
- 既有 AST 扫描（assert / xtquant import / 桥外 order call）保持 PASS。

## Boundary

- 本任务**绝不 invoke** 真实 order/cancel；所有 broker 调用经注入 fake/bridge。
- 未实现/未授权：真实资金运行、Gate 6、live-soak。
- `live_trading_allowed=false`；Gate 6/7 BLOCKED。
- 授权令牌：`AUDIT_NODE_B_STATE_MACHINE_PORT`（迭代 10 移交）。

## Recommendation

`REVIEW_READY`（Iteration 10）——NODEB-SM9-001..005 已修复（SELF_CERTIFIED），
按审计要求移交 **AUDIT_NODE_B_STATE_MACHINE_PORT** 独立复审；独立 PASS 前不
声称状态机扩展通过；首笔真实订单须 Node B PASS + 用户显式授权。
