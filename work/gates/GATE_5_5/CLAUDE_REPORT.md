# Gate 5.5 / Claude Report — Live Broker Adapter (Pre-Live Only)

## Status

`AUDIT_READY_PRELIVE (ITERATION 8)` — Node B Iteration-6 复审（`9b664d8`，
`work/gates/GATE_5_5/NODE_B_REVIEW_ITER6_20260815.md`）判定 `CHANGES_REQUIRED`；
**NODEB-RR6-001..003 已全部修复（SELF_CERTIFIED）**，Audit Node B 已
**FINAL PASS_PRELIVE**（`e252847`，2026-08-15）。Iteration 8（本次）为
**reverse_repo 状态机 + 形式验证器移植（用户授权的新能力，SELF_CERTIFIED）**，
不改变、不取代 PASS_PRELIVE 结论。**本任务未调用任何真实 order/cancel；
`live_trading_allowed=false` 保持。**

授权来源：Gate 5 Node A PASS（`4c1cc8c`）+ Audit Node B FINAL PASS_PRELIVE
（`e252847`）+ 用户 2026-08-15 显式授权移植 reverse_repo 完整状态机 + 形式验证器。

参考实现（QMT 行为基线）：`https://github.com/smhe00/reverse_repo`
pinned commit `c9ecc701d9b1c47d6a8d03539b482368741204a3`。

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

- 回归（Iteration 8，最新）：`python -m unittest discover -s tests -p "test_*.py"`
  → **980 tests OK**；`python -m compileall -q src tests scripts` → exit 0。
- Iteration 7（RR6 关闭）：**957 tests OK**；capability 扫描：真实
  `order_stock`/`cancel_order_stock` 调用点 **桥内 2 处（白名单）、桥外 0 处**；
  `RESULT: PASS`。
- 测试文件：`test_xtquant_bridge.py`（account-health FI）、`test_live_bootstrap.py`
  （SAFE_MODE 伪造结果 FI、LiveStack 状态机 + fail-closed journal 绑定）、
  `test_execution_statemachine.py`（形式验证器/快照/journal/engine 集成）、
  `test_execution_live_chain.py`、`test_execution.py`。
- 既有 AST 扫描（assert / xtquant import / 桥外 order call）保持 PASS。

## Boundary

- 本任务**绝不 invoke** 真实 order/cancel；所有 broker 调用经注入 fake/bridge。
- 未实现/未授权：真实资金运行、Gate 6、live-soak。
- `live_trading_allowed=false`；Gate 6/7 BLOCKED。
- 授权令牌：`AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`。

## Recommendation

`AUDIT_READY_PRELIVE`（Iteration 8）——Audit Node B FINAL PASS_PRELIVE
（`e252847`）已接受；reverse_repo 状态机移植为**新能力**，建议在首笔真实订单前
纳入 Node B 复审；首笔真实订单须 Node B PASS + 用户显式授权。
