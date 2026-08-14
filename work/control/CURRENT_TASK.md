# Task G2-T003 — Append-Only T-Lot Audit Log Schema

## Goal

在已验收的 migration 2 / `t_lots` 基础上新增 migration 3，建立专用于 T-Lot 的 append-only Audit Log
schema 与启动完整性验证。本任务只建立持久化合同；不实现 Ledger CRUD、状态转换或交易执行。

## Iteration 2 Review Findings

Iteration 1 未通过。只修 `REV-G2T003-001..002`：

- dangling-FK verifier 使用固定 `__tgrid_probe_no_such_lot`；同名合法 T-Lot 会让健康数据库被误拒绝。
- 架构师确认 `tests/unit/test_t_lot_schema.py` 的既有 latest-version/history 断言必须随 migration 3 机械
  更新；Iteration 2 仅授权保留 Iteration 1 当前精确 diff，不得改动其它 T-Lot schema 测试语义。

Iteration 2 禁止新增字段、CRUD/writer、状态机或任何外部能力。

## In Scope

- 复用现有 `Migration`、`MIGRATIONS`、`initialize/open_database` 与行为式 verifier。
- 新增 migration version 3，名称固定为 `t_lot_audit_log`，创建 `t_lot_audit_log` 表。
- 字段精确为：`id`、`t_lot_id`、`event_type`、`from_status`、`to_status`、`details_json`、`actor`、
  `created_at`。
- `t_lot_id` 外键引用 `t_lots(id)`，禁止静默悬空；所有必填文本显式非空。
- `from_status/to_status` 为 NULL 或 G2-T002 已批准的七个 T-Lot 状态之一。
- `details_json` 在本任务只要求非空文本；JSON 解析/业务 schema 留给后续 writer/service，避免复制解析层。
- 数据库 trigger 同时禁止 UPDATE 与 DELETE；历史事件只能追加。
- 启动 verifier 必须检查列、外键、约束以及 UPDATE/DELETE 的真实拒绝行为，不只匹配 DDL/trigger 名。
- 使用临时 SQLite 文件测试 fresh install、v2→v3、幂等重开、migration rollback 与 tamper detection。

## Out of Scope

- Audit writer/repository API、T-Lot CRUD、状态转换矩阵、原子“状态更新 + audit append”事务服务。
- Corporate Action payload 解释、人工 review workflow、Reconciliation、Crash Recovery、SAFE_MODE。
- OrderIntent、Reservation、订单/成交/callback、策略与 LIFO。
- QMT/XtQuant、账号、行情、下单、撤单、订阅、下载及任何 live/dry-run 执行。
- 真实数据库、配置、日志、reverse_repo 修改或跨仓运行时依赖。

## Reuse Direction

- 只能扩展现有 migration runner 和 `database.py` verifier；禁止第二个 SQLite wrapper/version 文件。
- 复用 G2-T002 的非冲突 probe ID、行为式约束探针与完整 rollback 模式；如需共享 helper，应最小重构，
  不复制另一套近似实现。
- 复用 G2-T002 的状态集合语义；不得引入第二套相互漂移的状态定义。
- reverse_repo 无本项目 Audit schema；不得复制交易 journal 或执行脚本充当 TGrid Audit Log。

## Allowed Files

- `src/tgrid/persistence/migrations.py`
- `src/tgrid/persistence/database.py`
- `tests/unit/test_t_lot_audit_schema.py`（新增）
- `tests/unit/test_t_lot_schema.py`（Iteration 2 仅允许保留当前 latest-version/history 机械更新）
- `tests/unit/test_persistence.py`（仅版本 3 / history / forbidden-table 的必要明确更新）
- `tests/unit/test_cli.py`（仅一条 user_version 与两条 history count 从 2 更新为 3）
- `work/reports/tests/G2-T003-test-output.txt`（新增）
- `work/gates/GATE_2/G2-T003_RESULT.md`（新增）
- `work/gates/GATE_2/CLAUDE_REPORT.md`
- `work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md`
- `work/handoff/claude_to_architect/TEST_REPORT.md`
- `work/handoff/claude_to_architect/QUESTIONS.md`（仅确有问题时）
- `work/control/WORKFLOW_STATE.yaml`
- `work/control/CLAUDE_HEARTBEAT.md`
- `work/locks/WORKTREE_LEASE.yaml`（仅持有期间）

## Forbidden Files

- 设计/协议原文、`CURRENT_TASK.md` 与架构师控制文件。
- `src/tgrid/position/**`、`src/tgrid/integrations/**`、`src/tgrid/adapters/**`、`src/tgrid/probes/**`。
- `src/tgrid/__init__.py`、`src/tgrid/models.py`、`src/tgrid/risk/**`、`src/tgrid/persistence/__init__.py`。
- `config/**`、`scripts/**`、`docs/**`、`README.md`、`D:/gitee/miniQMT/reverse_repo/**`。
- 任何真实/local 数据库、配置、日志、账号或业务数据。

## Design References

- §6：禁止删除历史批次；所有状态变化必须保留 Audit Log。
- §16–16.1：SUSPENDED review 人工动作须可审计。
- §4.2：Corporate Action 调整必须写 Audit Log（payload 业务解释后续实现）。
- §21–23：SQLite 启动加载、禁止静默修复、Crash Recovery 不依赖 callback。
- §34：INV-002、INV-005、INV-008、INV-010、INV-011。
- §37 Gate 2：本任务只覆盖 Audit Log schema foundation。

## Invariants

1. Migration 3 单事务原子；失败不得残留 audit 表、trigger、history 3 或 user_version=3。
2. v2→v3 不删除/改写既有 metadata、migration history、t_lots 或其 trigger。
3. 合法 audit 行只能引用已存在的 T-Lot；悬空 t_lot_id 必须数据库层拒绝。
4. audit 行一经插入，数据库层禁止 UPDATE 和 DELETE；不得提供 bypass helper。
5. from/to status 为 NULL 或批准的七状态；未知、大小写变体、空字符串拒绝。
6. verifier 所有 probe 使用不冲突 ID，完整 rollback，不改变用户行、t_lots、history 或 user_version。
7. 缺表/缺列/错外键/弱化约束/同名但不拦截的 trigger 均 fail closed，不自动修复。
8. 生产安全无 Python `assert`；未知 SQLite/schema 异常进入现有 `PersistenceError` 层。
9. `live_trading_allowed=false`；无 QMT/order/cancel/download/subscribe 调用。

## Acceptance Criteria

- `MAX_SCHEMA_VERSION == 3`，MIGRATIONS 精确为 bootstrap、t_lot_ledger、t_lot_audit_log。
- fresh DB 与手工合法 v2 DB 均原子到 v3；既有 t_lots 数据逐值保持；第二次打开幂等。
- 合法最小 audit 行可插入；悬空 t_lot_id、空必填文本、非法 from/to status 被拒绝。
- UPDATE 任意列与 DELETE 均由数据库拒绝，原始 audit 行逐值保持。
- 删除/弱化任一 immutable trigger、外键或约束后 initialize 显式失败且不修复。
- verifier 前后 audit/t_lots 全行、history 与 user_version 完全一致。
- 不新增 writer/CRUD/状态机，不访问真实 DB/QMT。
- 既有 555 项测试保持通过。

## Required Tests / Failure Injection

- fresh、v2→v3、幂等、migration-3 中途非法 SQL完整 rollback并可再次升级。
- 合法行；每个合法 from/to status；NULL status；空/NULL必填字段；悬空 t_lot_id。
- UPDATE/DELETE 拒绝且行不变；同名 no-op trigger 必须被 verifier 拒绝。
- 伪造版本 3 schema：弱化 status、缺外键或外键指错表/列，verifier 必须拒绝。
- 预置旧/当前 probe-shaped IDs 与非空真实数据，initialize 仍通过且零残留。
- 完整 `unittest discover`、compileall、AST forbidden API/assert scan、diff-check。

## Deliverables

- migration 3、扩展 verifier 与测试。
- 完整测试输出、Implementation/Test/Claude/G2-T003 Result 报告。
- 报告单列 Reuse Evidence、Failure Injection 与明确未实现的 writer/CRUD/交易能力。
- 不提交 commit；由 Desktop ChatGPT 独立复核后决定验收提交。

## Stop Condition

完成后删除 Lease，设置 `REVIEW_READY / owner=architect / task_id=G2-T003 / iteration=2` 并停止写入。
若无法在 Allowed Files 内安全复用现有 migration/verifier，设置 BLOCKED，不得另建数据库框架。
