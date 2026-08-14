# Task G2-T002 — Transactional T-Lot Ledger Schema

## Goal

在现有 SQLite migration/verification 基础上新增 Gate 2 的 T-Lot Ledger 持久化 schema，并以事务迁移、
数据库级约束、禁止历史删除和启动完整性验证形成 fail-closed 基础。本任务只建立 schema，不实现 Ledger
CRUD 或状态转换服务。

## Iteration 2 Review Findings

Iteration 1 未通过。只修 `REV-G2T002-001..005`：

- SQLite 当前接受 `NULL id`、fractional qty 与文本 entry price，数据库约束没有表达真实类型语义。
- verifier 使用固定 probe ID；合法用户行可造成启动拒绝，既有主键冲突也可让弱化约束假通过。
- realized PnL 被错误限制为正数、fees 被错误限制为严格正数；设计并无此语义。
- verifier 没有完整行为验证必填文本、numeric storage type 与 review_status。
- `tests/unit/test_cli.py` 的版本断言修改虽属必要机械更新，但超出 Iteration 1 Allowed Files；Iteration 2
  仅授权精确更新三条断言：一条 user_version 与两条 migration history count，从 1 改为 2。

Iteration 2 仍只允许 migration/schema/verifier 与测试修复，禁止新增 CRUD 或领域状态机。

## In Scope

- 复用现有 `Migration`、`MIGRATIONS`、`initialize/open_database` 和行为式 schema probe 模式。
- 新增 migration version 2，名称固定、可审计，创建 `t_lots` 表。
- 表至少覆盖设计 §6 全部字段，并加入 §16.1 的 suspended review 字段：
  `suspended_at/review_due_at/last_reviewed_at/review_reason/review_status`。
- 数据库级约束至少保证：主键、非空字段、`qty > 0`、`entry_price > 0`、允许状态枚举、可选价格/比例
  字段为正、时间/ID/symbol/side 非空。
- 允许状态精确为：`PENDING_BUY`、`OPEN`、`PENDING_SELL`、`CLOSED`、`SUSPENDED`、
  `CONVERTED_TO_STRATEGIC`、`ERROR`。
- 用数据库 trigger 禁止任何 `DELETE FROM t_lots`；状态变化以后只能通过更新并由后续 Audit Log 记录。
- 扩展启动 schema verifier：版本正确但 t_lots 缺失、错列、弱化约束或 delete trigger 缺失时必须失败。
- 使用临时 SQLite 文件测试 fresh install、v1→v2 upgrade、幂等重开、失败 rollback 与 tamper detection。

## Out of Scope

- T-Lot repository/CRUD、创建/更新/查询 API、状态转换矩阵、LIFO、目标价格计算。
- Audit Log 表与写入、OrderIntent、Reservation、订单/成交/回调、Crash Recovery、Reconciliation。
- PositionSnapshot/CorePositionGuard 修改。
- QMT/XtQuant、账号、行情、下单、撤单、订阅、下载或任何 live/dry-run 执行。
- 真实数据库、配置、日志、CLI、reverse_repo 修改或跨仓依赖。

## Reuse Direction

- 必须扩展现有 migration tuple 和 `database.py` verifier；禁止另建第二个 migration runner、数据库入口、
  schema version 文件或 SQLite wrapper。
- 约束验证优先复用现有 SAVEPOINT/rollback 行为探针思想，不以容易误判的 DDL 前缀/正则作为唯一证据。
- reverse_repo 没有 TGrid T-Lot schema；不得复制其交易执行日志/脚本来替代本项目 Ledger schema。

## Allowed Files

- `src/tgrid/persistence/migrations.py`
- `src/tgrid/persistence/database.py`
- `tests/unit/test_t_lot_schema.py`（新增）
- `tests/unit/test_persistence.py`（仅为 schema version 2 更新既有明确预期，不得弱化 Gate 0 测试）
- `tests/unit/test_cli.py`（Iteration 2 仅允许三条断言：一条 version、两条 history count 从 1 更新为 2）
- `work/reports/tests/G2-T002-test-output.txt`（新增）
- `work/gates/GATE_2/G2-T002_RESULT.md`（新增）
- `work/gates/GATE_2/CLAUDE_REPORT.md`
- `work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md`
- `work/handoff/claude_to_architect/TEST_REPORT.md`
- `work/handoff/claude_to_architect/QUESTIONS.md`（仅确有问题时）
- `work/control/WORKFLOW_STATE.yaml`
- `work/control/CLAUDE_HEARTBEAT.md`
- `work/locks/WORKTREE_LEASE.yaml`（仅持有期间）

## Forbidden Files

- 设计与协议原文。
- `src/tgrid/position/**`、`src/tgrid/integrations/**`、`src/tgrid/adapters/**`、`src/tgrid/probes/**`。
- `src/tgrid/__init__.py`、`src/tgrid/models.py`、`src/tgrid/risk/**`、`src/tgrid/persistence/__init__.py`。
- `config/**`、`scripts/**`、`docs/**`、`README.md`。
- `D:/gitee/miniQMT/reverse_repo/**` 与父仓库其他项目。
- 任何真实/local 数据库、配置、日志、账号或业务数据。

## Design References

- §6 T-Lot 虚拟批次账本：字段、状态、禁止删除、状态变化须留 Audit Log。
- §16–16.1：SUSPENDED 与 review 字段；SUSPENDED 仍占容量（容量逻辑后续实现）。
- §21–23：启动加载 SQLite、禁止静默修复、Crash Recovery 不依赖 callback。
- §34：INV-002、INV-005、INV-006、INV-008、INV-010、INV-011。
- §37 Gate 2：本任务只覆盖 T-Lot Ledger 的 schema foundation。

## Invariants

1. Migration 2 必须在单一事务内原子完成；失败不得留下 t_lots、trigger、version 2 history 或
   `user_version=2` 的部分状态。
2. v1→v2 upgrade 不删除、不改写 migration 1 与 application metadata。
3. 重新 initialize 版本 2 数据库幂等，不重建表、不重复 history。
4. `DELETE t_lots` 必须由数据库层拒绝；不得提供 bypass helper。
5. status 只接受七个设计值；未知/大小写变体/空值在数据库层拒绝。
6. qty 为正整数语义；entry price 为正；非法约束 probe 不留测试行。
7. 版本数字、migration history 与实际 schema/trigger/约束必须一致，否则 `PersistenceError` 子类。
8. 不自动修复被篡改的表/trigger；不删除、覆盖或重建用户数据库。
9. 生产安全无 Python `assert`；未知 SQLite/schema 异常 fail closed。
10. `live_trading_allowed=false`；无 QMT、order/cancel/download/subscribe 调用。

## Acceptance Criteria

- `MAX_SCHEMA_VERSION == 2`，`MIGRATIONS` 精确包含 `(1, bootstrap)` 与 `(2, t_lot_ledger)`。
- fresh `initialize()` 后基础表、t_lots、禁止删除 trigger 和两条 migration history 均存在。
- 人工构造合法 v1 数据库后 initialize 可原子升级到 v2并保留 v1 metadata/history。
- 合法最小 T-Lot 行可以由测试 SQL 插入；删除该行触发 `sqlite3.IntegrityError` 或明确数据库拒绝。
- 非法 qty/entry_price/status/必填空文本均由数据库约束拒绝。
- 删除/改列 t_lots、删除 trigger、用弱化约束伪造 v2 schema，重新 initialize 均显式失败且不修复。
- verifier 的行为探针前后：t_lots 行、migration history、`user_version` 完全不变。
- 不新增 Ledger CRUD 公共 API，不修改现有 Position 或 QMT 代码。
- 既有 523 项测试保持通过。

## Required Tests

- Fresh DB：版本、history、表、列、trigger、foreign_keys/journal 既有合同。
- v1→v2：预置 metadata 标记值，升级后逐值保持；第二次打开幂等。
- Migration 2 中途 SQL 错误注入：完整 rollback，仍为干净 v1 状态；修复 migration 后可再次升级。
- 合法最小行与包含所有可选/suspended 字段的完整行。
- 每个 status 接受；未知、小写、空 status 拒绝。
- qty 0/负数/非整数语义，entry_price 0/负数，空 id/symbol/side/time 拒绝。
- target/exit price、grid_pct 非正值（非 NULL 时）拒绝。
- DELETE 拒绝且原行保留；删除 trigger 后 initialize fail closed，不自动恢复。
- 缺表、缺列/多列/错类型、弱化 qty/status 约束的伪造 schema均拒绝。
- verifier probe 前后 row count/content、migration history、user_version 不变。
- 完整 `unittest discover`、compileall、AST forbidden API scan、diff-check。

## Failure Injection

- 将 migration 2 替换为“先建表再执行非法 SQL”，确认事务 rollback 没有残留 table/trigger/history/version。
- 构造 `CHECK(qty > 0 OR 1=1)` 与允许任意 status 的伪造 v2 表，确认语义 verifier 拒绝而不是字符串误判。
- 构造名字相同但允许删除的 trigger，确认 verifier 不能只检查 trigger 名称。
- 在非空 t_lots 上运行 verifier，确认 SAVEPOINT probe 不删除/修改真实行。
- SQLite 意外错误必须转换为现有 `PersistenceError` 层，不泄漏裸数据库异常。

## Deliverables

- migration 2、扩展 schema verifier 与测试。
- 完整 `G2-T002-test-output.txt`。
- Implementation/Test/Claude/G2-T002 Result 报告，含 migration/constraint/rollback 映射。
- 报告单列 Reuse Evidence 与 Failure Injection；不得宣称已实现 CRUD/Audit/Reconciliation。
- 不提交 commit；由 Desktop ChatGPT 独立复核后决定验收提交。

## Stop Condition

完成后删除 Lease，设置：

```text
state = REVIEW_READY
owner = architect
task_id = G2-T002
iteration = 1
```

然后停止写入。若现有 persistence verifier 无法在 Allowed Files 内安全扩展，设置 `BLOCKED`，不得另建
数据库框架或扩大文件范围。
