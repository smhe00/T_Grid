# Task G2-T005 — T-Lot Business Transition Policy Guard

## Goal

在 G2-T004 已验收的原子 `transition_t_lot_status` 之上增加一个**纯离线、fail-closed、闭集的业务状态转换策略层**。
该层负责把受支持的业务 action 映射为唯一的 T-Lot `from_status -> to_status`，拒绝所有未授权边，并在允许时
仅通过 G2-T004 原语完成持久化。任务不连接 QMT，不生成 OrderIntent，不实现真实人工交易授权。

## Architectural Intent

G2-T004 故意只保证“两个合法 schema status 之间的原子 CAS + Audit”，不决定业务上哪些边合法。
G2-T005 关闭这一安全缺口：高层调用者不再通过本任务 API 任意指定 `new_status`，而只能提交闭集 action；
策略层解析出唯一目标状态并调用既有 writer。

本任务只建立 V1 当前可机械验证的最小生命周期边，不提前猜测订单拒绝、部分成交、人工卖出或异常恢复语义。

## In Scope

新增一个 T-Lot business transition policy/guard，至少提供：

1. 一个纯函数 resolver：输入 `expected_status + action`，返回 frozen/data-only transition plan；
2. 一个 guarded apply API：输入连接、lot id、expected status、action、audit id/details/actor/time，先解析策略，
   再**恰好一次**调用 G2-T004 `transition_t_lot_status`；
3. action 必须为 exact `str` 且来自以下闭集，action 到状态边必须固定：

```text
BUY_FILL_CONFIRMED   : PENDING_BUY  -> OPEN
PREPARE_SELL         : OPEN         -> PENDING_SELL
SELL_FILL_CONFIRMED  : PENDING_SELL -> CLOSED
SUSPEND_T            : OPEN         -> SUSPENDED
RESUME_T             : SUSPENDED    -> OPEN
```

4. `event_type` 由 action 固定映射生成，调用者不得覆盖或传入任意 event type；
5. resolver/apply 对未知 action、错误 expected status、非法组合、self-transition、终态出边全部 fail closed；
6. `CLOSED`、`CONVERTED_TO_STRATEGIC`、`ERROR` 在本任务视为无自动出边；
7. 以下设计动作**不得伪装成普通状态转换**：
   - `KEEP_SUSPENDED`：是 no-op review decision，不得通过 `SUSPENDED -> SUSPENDED` 绕过 writer；
   - `CONVERT_TO_STRATEGIC`：需要后续真正的显式人工授权机制，本任务必须拒绝执行；
   - `MANUAL_EXIT`：需要实际人工成交/对账证据，本任务不得直接映射为 `CLOSED`；
8. 复用 G2-T004 writer 的 CAS/rollback/异常净化，不复制 SQL、不自建第二套 transaction manager。

## Deliberate Boundary

本任务的 transition matrix 是**最小闭集**，不是对未来全部合法状态边的猜测。

特别地：

- 不为 routine order reject/cancel/partial fill 自创状态边；
- 不新增 `ERROR` 恢复边；
- 不实现 audit-only `KEEP_SUSPENDED` 事件；
- 不把聊天文本、配置布尔值或普通函数参数当成真实人工交易授权；
- 后续如需扩展边，必须由新的 Architect task/ADR 明确授权。

## Out of Scope

- T-Lot create/full CRUD/list/query、数量/价格/订单字段更新、LIFO 查询。
- `KEEP_SUSPENDED` audit-only writer、真实人工审批 token/identity/UI。
- `CONVERT_TO_STRATEGIC` 执行、`MANUAL_EXIT` 执行、人工成交写回。
- Reconciliation、Crash Recovery、SAFE_MODE、Corporate Action 调整。
- OrderIntent、Reservation、订单状态机、部分成交、撤单/拒单处理。
- QMT/XtQuant、账号、行情、下单、撤单、订阅、下载、真实或 dry-run 交易执行。
- schema/migration/version 变化、真实数据库、配置、日志、reverse_repo 修改或跨仓依赖。

## Reuse Direction

- 必须直接复用 `src/tgrid/persistence/t_lot_writer.py` 的 `transition_t_lot_status`；禁止复制其 SQL/CAS/rollback。
- 必须复用现有七状态定义；不得新建第三份 status 列表。
- 新异常必须进入现有 `PersistenceError` / T-Lot persistence 异常层，不建立新的无关异常根。
- 新模块不得 import `xtquant`，不得出现 broker/order/cancel/download/subscribe 能力。

## Allowed Files

- `src/tgrid/persistence/t_lot_transition_policy.py`（新增）
- `src/tgrid/persistence/__init__.py`（仅导出本任务批准的 resolver/apply/plan/exceptions）
- `tests/unit/test_t_lot_transition_policy.py`（新增）
- `work/reports/tests/G2-T005-test-output.txt`（新增）
- `work/gates/GATE_2/CLAUDE_REPORT.md`
- `work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md`
- `work/handoff/claude_to_architect/TEST_REPORT.md`
- `work/handoff/claude_to_architect/QUESTIONS.md`（仅确有问题时）
- `work/control/WORKFLOW_STATE.yaml`

本地 `work/locks/WORKTREE_LEASE.yaml` 可按协议持有，但**不得 stage/commit**。

## Forbidden Files

- `src/tgrid/persistence/t_lot_writer.py`、`migrations.py`、`database.py`：G2-T004/G2-T003 已验收，本任务禁止修改。
- 设计/协议原文、`CURRENT_TASK.md`、Architect Review/Fix Request/Gate Result。
- 现有 persistence/position/risk/integration/adapter/probe 实现与既有测试。
- `src/tgrid/models.py`、`config/**`、`scripts/**`、`docs/**`、`README.md`。
- `D:/gitee/miniQMT/reverse_repo/**` 与任何真实/local 数据库、配置、日志、账号或业务数据。

## Design References

- §3.1：所有策略状态变化在单一事件线程串行执行；callback 不直接改 T-Lot。
- §6：七种 T-Lot 状态；所有状态变化必须保留 Audit Log，禁止删除历史批次。
- §16–16.1：SUSPENDED review；`CONVERT_TO_STRATEGIC` / `MANUAL_EXIT` 需要显式人工确认，禁止自动处置。
- §31：状态机采用显式、可审计状态转换。
- §34：Fail Closed、安全不变量与 `live_trading=false`。
- §37 Gate 2：Position + Ledger + Reconciliation；当前任务仅补 Ledger 的业务 transition guard。

## Invariants

1. 高层 apply API 不接受任意 `new_status` 或任意 `event_type`；目标状态/事件类型只能由闭集 action 推导。
2. 未列出的任意 status pair/action 组合必须在调用 writer 前拒绝，数据库逐值不变。
3. 一个成功 apply 恰好调用一次 G2-T004 writer；不得自行 `BEGIN/UPDATE/INSERT/COMMIT/ROLLBACK`。
4. stale expected status 由底层 CAS fail closed；policy 不预读后猜测或 retry。
5. `KEEP_SUSPENDED` 不得用 self-transition 制造假审计。
6. `CONVERT_TO_STRATEGIC`、`MANUAL_EXIT` 本任务绝不执行；不得通过 `manual=True`、配置或 actor 字符串绕过。
7. `CLOSED` / `CONVERTED_TO_STRATEGIC` / `ERROR` 无自动出边。
8. 输入拒绝不得调用未知对象的 `str/repr/bool/iter/__eq__`；项目异常固定、data-free、无 secret exception graph。
9. 不删除/弱化 G2-T004 writer 测试或 schema/verifier 测试。
10. `live_trading_allowed=false`；无 QMT/order/cancel/download/subscribe 调用。

## Acceptance Criteria

- 五条批准边逐条成功，返回 frozen/data-only plan/result，实际 DB status/audit 与 action 映射完全一致。
- 对 7x7 status pair 做矩阵测试：除五条批准边外全部拒绝；self-transition 全拒绝。
- action 与 expected status 不匹配时在 DB write 前拒绝。
- unknown action、空值、非 exact-str、str subclass、bool/bytes/container/恶意对象全部 fail closed 且无 dunder secret 泄漏。
- `KEEP_SUSPENDED`、`CONVERT_TO_STRATEGIC`、`MANUAL_EXIT` 显式测试为不可执行且 DB 不变。
- stale expected status 真实走到底层 CAS conflict；无自动 retry、upsert、状态猜测。
- spy/patch 证明 rejected request 调用 writer 0 次，accepted request 调用 writer恰 1 次。
- 新模块 AST 中无 raw SQL transaction/UPDATE/INSERT/DELETE、无 `assert` 安全保护、无 QMT/交易能力。
- 当前完整回归（基线 597 项）全部保持通过，加上本任务新测试。

## Required Tests / Failure Injection

- 五条 approved edge happy path + 固定 event_type 映射。
- 全 7x7 transition matrix negative coverage。
- terminal-state outbound、self-transition、action/source mismatch。
- manual/no-op 三动作 fail-closed：KEEP/CONVERT/MANUAL_EXIT。
- malicious action/status object 的 dunder/secret 注入；异常 message、`__cause__`、`__context__` 不可达 secret。
- writer spy：拒绝前 0 call，成功恰 1 call；writer 抛 conflict/write-failed/BaseException 时不吞、不 retry、不二次调用。
- SQLite integration：seed 临时 T-Lot，执行 approved edge 后精确一条 audit；stale source 前后逐值不变。
- 完整 unittest、compileall、AST forbidden/raw-SQL scan、`git diff --check`、Allowed Files diff-check。

## Deliverables

- business transition resolver + guarded apply + frozen plan/result/最小异常。
- 完整单元/FI/SQLite integration 测试与原始测试输出。
- Implementation/Test/Claude 报告必须单列：
  - exact transition matrix；
  - Reuse Evidence（实际调用 G2-T004 writer）；
  - rejected manual/no-op actions；
  - Failure Injection；
  - 明确未实现的 QMT/OrderIntent/Reconciliation/manual authorization。

## Stop Condition

完成后再次 fetch `origin/main` 并确认实现基线未变化；若变化立即 STOP WRITE。
若未变化，按 GitHub 双 Agent 协议设置新的唯一 `handoff_id`、`handoff_seq + 1`、
`state=REVIEW_READY / owner=architect / task_id=G2-T005 / iteration=1 / authorized_next=[]`，
只提交 Allowed Files 与 Claude 所有报告，普通非强制 push 到 `main`，然后停止写入等待 Review。

若无法在不修改 G2-T004 writer/schema 的前提下实现，设置 `BLOCKED`，不得扩大范围。
