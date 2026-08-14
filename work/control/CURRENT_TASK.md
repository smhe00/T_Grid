# Task G2-T004 — Atomic T-Lot Status Transition Writer

## Completion

`PASS` — Architect independent review completed at `2026-08-15T00:23:10+08:00` (iteration 2).
The next task is intentionally left for the GitHub/web-ChatGPT handoff.

## Goal

在已验收的 `t_lots` 与 `t_lot_audit_log` schema 上实现一个纯离线、fail-closed 的持久化原语：使用
SQLite 单事务 compare-and-set 更新一个 T-Lot 的 status/updated_at，并追加一条不可变 Audit Log。任何
一步失败都必须完整回滚。本任务不决定业务状态转换矩阵，也不连接 QMT。

## Iteration 2 Review Findings

Iteration 1 未通过。只修 `REV-G2T004-001..003`：

- CAS 后的 `KeyboardInterrupt/SystemExit/GeneratorExit` 未进入 rollback，留下 active 半完成事务。
- status 在 exact-str 校验前做 tuple membership，执行恶意 `__eq__` 并泄露 secret。
- 两连接测试是完全串行执行，没有形成确定性交错/竞争。

Iteration 2 禁止扩大 writer API、字段、状态策略或数据库层。

## In Scope

- 新增唯一的 T-Lot status transition writer；输入为已初始化的 `sqlite3.Connection` 与显式字段。
- writer 必须显式接收：`t_lot_id`、`expected_status`、`new_status`、`audit_id`、`event_type`、
  `details_json`、`actor`、`occurred_at`。
- 事务开始前验证全部输入为 exact `str`、必填非空；status 必须属于既有七状态且 old != new。
- writer 只接受当前没有活动 transaction 的连接；若调用者已有事务，显式拒绝且不得 commit/rollback
  调用者状态。
- 使用 `BEGIN IMMEDIATE` + 单次 compare-and-set：`UPDATE ... WHERE id=? AND status=?`；rowcount 必须为 1。
- 同一事务追加 audit，`from_status=expected_status`、`to_status=new_status`，并更新 `updated_at=occurred_at`。
- audit insert、约束、CAS、COMMIT 任一步失败时 rollback；不得留下只更新未审计或只审计未更新状态。
- 提供最小明确的 persistence 异常：输入无效、T-Lot 不存在、expected-status 冲突、原子写入失败。
- 返回 data-only/frozen 结果，仅包含 lot id、from/to status、audit id、occurred_at；不返回连接/游标。

## Deliberate Boundary

- 本原语只保证“调用者请求的两个合法状态之间”原子 CAS + Audit，不定义哪些边合法。
- 业务状态转换矩阵、人工授权（CONVERT/MANUAL_EXIT）、OrderIntent/成交驱动规则由后续状态机任务实现。
- 不提供 delete、通用 UPDATE、任意 SQL、重试或 bypass-audit API。

## Out of Scope

- T-Lot create/full CRUD/list/query repository、数量/价格修改、LIFO、目标价计算。
- 业务 transition matrix、SUSPENDED review action、Corporate Action payload 解释。
- Reconciliation、Crash Recovery、SAFE_MODE、OrderIntent、Reservation、订单/成交/callback。
- QMT/XtQuant、账号、行情、下单、撤单、订阅、下载以及任何 live/dry-run 执行。
- schema migration 4、真实数据库、配置、日志、reverse_repo 修改或跨仓依赖。

## Reuse Direction

- 必须直接使用 G2-T002/G2-T003 已验收的 `t_lots` 与 `t_lot_audit_log`；禁止新表、新 migration、新审计文件。
- 状态集合必须从一个现有 persistence 定义复用或最小提取为共享常量；不得复制第三份漂移列表。
- 复用现有 `PersistenceError` 层；新增异常必须继承该层，禁止第二个异常根类型。
- 不复制 reverse_repo journal/交易执行代码；其执行日志不能替代本项目数据库 Audit Log。

## Allowed Files

- `src/tgrid/persistence/migrations.py`（仅允许最小公开/复用既有状态 tuple；不得改 SQL/schema/version）
- `src/tgrid/persistence/database.py`（仅必要的共享状态引用调整；不得改 schema/version/verifier 语义）
- `src/tgrid/persistence/t_lot_writer.py`（新增）
- `src/tgrid/persistence/__init__.py`（仅导出本任务批准的 writer/result/exceptions）
- `tests/unit/test_t_lot_writer.py`（新增）
- `work/reports/tests/G2-T004-test-output.txt`（新增）
- `work/gates/GATE_2/G2-T004_RESULT.md`（新增）
- `work/gates/GATE_2/CLAUDE_REPORT.md`
- `work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md`
- `work/handoff/claude_to_architect/TEST_REPORT.md`
- `work/handoff/claude_to_architect/QUESTIONS.md`（仅确有问题时）
- `work/control/WORKFLOW_STATE.yaml`
- `work/control/CLAUDE_HEARTBEAT.md`
- `work/locks/WORKTREE_LEASE.yaml`（仅持有期间）

## Forbidden Files

- 设计/协议原文、`CURRENT_TASK.md` 与架构师控制文件。
- 现有 persistence/CLI/T-Lot schema 测试；本任务不改变 schema version/history 预期。
- `src/tgrid/position/**`、`src/tgrid/integrations/**`、`src/tgrid/adapters/**`、`src/tgrid/probes/**`。
- `src/tgrid/models.py`、`src/tgrid/risk/**`、`config/**`、`scripts/**`、`docs/**`、`README.md`。
- `D:/gitee/miniQMT/reverse_repo/**` 与任何真实/local 数据库、配置、日志、账号或业务数据。

## Design References

- §6：所有 T-Lot 状态变化必须保留 Audit Log；禁止删除历史批次。
- §16–16.1：SUSPENDED/review 动作必须可审计，但业务授权后续实现。
- §21–23：本地 SQLite 是恢复输入之一，禁止静默修复，callback 不是唯一事实来源。
- §34：INV-002、INV-005、INV-008、INV-010、INV-011。
- §37 Gate 2：T-Lot Ledger + Audit Log 的原子写入基础；不实现交易信号。

## Invariants

1. status update 与 audit insert 必须 all-or-nothing；不存在可观察的半完成状态。
2. CAS rowcount != 1 时 fail closed；不得猜测、重试、upsert 或自动创建 T-Lot。
3. expected status 不匹配时原 lot/audit 逐值不变。
4. audit_id 重复、audit constraint/trigger/commit 失败时 lot status/updated_at 完整回滚。
5. writer 不接受已有 transaction，不提交/回滚调用者 transaction。
6. 不执行未知对象的 `str/repr/bool/iter`；输入类型错误返回固定、data-free project error。
7. 普通 SQLite 异常转换为固定、data-free `PersistenceError` 子类；不得暴露 SQL/参数/底层异常图。
8. 无 Python `assert` 承担生产安全；无自动 retry。
9. `live_trading_allowed=false`；无 QMT/order/cancel/download/subscribe 调用。

## Acceptance Criteria

- 合法 CAS 精确更新 status/updated_at 一次并追加精确一条 audit，返回 frozen data-only result。
- 不存在 lot 与 expected-status 冲突可区分，均不写 audit、不改 lot。
- duplicate audit_id、非法 audit payload、数据库约束失败、commit failure 均完整 rollback。
- 已有 transaction 输入立即拒绝，调用者原 transaction/数据保持可继续控制。
- 两连接竞争同一 expected status 时最多一个成功；另一个显式 conflict，不新增第二条 audit。
- writer 没有 delete、通用 update、create、retry、QMT 或交易入口。
- 既有 579 项测试保持通过。

## Required Tests / Failure Injection

- happy path：OPEN→SUSPENDED、字段映射、exact one audit、frozen result。
- missing lot；stale expected status；old==new；七状态外值；空/NULL/非 exact-str 输入。
- duplicate audit_id 与审计表约束故障：验证 lot/audit/history/user_version 前后逐值不变。
- 在 audit insert 后注入 commit failure，验证 rollback；若 sqlite 原生难以可靠注入，使用最小受控
  connection seam，不得建立第二个数据库 wrapper。
- caller active transaction：writer 拒绝且不 commit/rollback，调用者可自行 rollback。
- 两个 SQLite connection 的确定性交错/CAS 竞争；不得靠 sleep。
- 异常 secret 注入：项目异常 message、`__cause__`、`__context__` 不可达 secret。
- 完整 unittest、compileall、AST assert/forbidden API scan、diff-check。

## Deliverables

- 原子 writer、frozen result、最小 persistence exceptions 与单元/FI 测试。
- 完整测试输出、Implementation/Test/Claude/G2-T004 Result 报告。
- 报告单列 Reuse Evidence、事务边界、Failure Injection 及明确未实现的状态矩阵/CRUD/QMT。
- 不提交 commit；由 Desktop ChatGPT 独立复核后决定验收提交。

## Stop Condition

完成后删除 Lease，设置 `REVIEW_READY / owner=architect / task_id=G2-T004 / iteration=2` 并停止写入。
若无法在 Allowed Files 内保持真正原子性，设置 BLOCKED，不得扩大为新数据库框架。
