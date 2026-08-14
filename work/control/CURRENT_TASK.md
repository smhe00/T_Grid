# Task G0-T002 — SQLite 初始化与迁移安全基础

## Goal

建立 Gate 0 的 SQLite 持久化基础：显式路径打开、完整性检查、事务化初始化、可审计 schema migration、幂等重启和 fail-closed 异常处理。

本任务只引入一个主要能力：**可靠且不可静默修复的数据库生命周期基础**。

## In Scope

1. 新增 `tgrid.persistence` 包。
2. 使用 Python 标准库 `sqlite3`，不增加第三方运行时依赖。
3. 从调用方显式传入的数据库文件路径打开/初始化数据库；禁止隐式读取配置或账号信息。
4. 建立最小 bootstrap schema：迁移记录与项目元数据；不建立交易领域表。
5. 实现有序、事务化、幂等的 schema migration runner。
6. 实现数据库完整性、未来版本、版本记录不一致和损坏文件的 fail-closed 处理。
7. 配置基础 SQLite PRAGMA，并确保每个新连接都启用外键约束。
8. 新增显式 persistence 异常类型与全面 `unittest`/Failure Injection。

## Out of Scope

- `t_lots`、OrderIntent、Reservation、positions、orders、trades、reconciliation、Audit Log 领域表；它们属于 Gate 2。
- logging 系统、CLI 和 Event Queue；它们属于后续 Gate 0 子任务。
- QMT/XtQuant、行情、账户、持仓、委托、成交、下单或撤单。
- 策略计算、SimBroker、dry-run、shadow/live execution。
- 自动备份、自动恢复、自动删除或重建损坏数据库。
- 配置热更新或数据库路径自动发现。
- Git push；Claude 不得 commit。

## Allowed Files

Claude 只能新增或修改：

```text
README.md
src/tgrid/__init__.py
src/tgrid/risk/__init__.py
src/tgrid/risk/exceptions.py
src/tgrid/persistence/__init__.py
src/tgrid/persistence/database.py
src/tgrid/persistence/migrations.py
tests/unit/test_persistence.py
work/control/WORKFLOW_STATE.yaml
work/control/CLAUDE_HEARTBEAT.md
work/locks/WORKTREE_LEASE.yaml
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md
work/handoff/claude_to_architect/TEST_REPORT.md
work/handoff/claude_to_architect/QUESTIONS.md
work/gates/GATE_0/CLAUDE_REPORT.md
work/reports/tests/G0-T002-test-output.txt
```

`WORKTREE_LEASE.yaml` 只在工作期间存在，交接前必须释放删除。

## Forbidden Files

```text
TGrid_双Agent协作与Gate验收协议_V1.0.md
TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md
pyproject.toml
.gitignore
config/**
src/tgrid/config.py
src/tgrid/models.py
tests/unit/test_config.py
tests/unit/test_models.py
work/control/CURRENT_TASK.md
work/control/ARCHITECT_HEARTBEAT.md
work/gates/GATE_0/TASK.md
work/gates/GATE_0/G0-T001_RESULT.md
work/gates/GATE_0/ARCHITECT_REVIEW.md
work/design/**
父目录 D:/gitee/miniQMT 中 T_Grid 之外的全部文件
```

除 Allowed Files 外不得新增或修改其他文件。

## Design References

- 设计文档 §3：T-Lot Ledger 使用 SQLite（本任务只建基础层）
- §6：历史不可直接删除原则（领域表留到 Gate 2）
- §18.2–§18.3：未来订单事务/原子性需求（本任务不得实现订单）
- §21–§23：启动对账与 crash recovery 对持久化可靠性的要求
- §30：database error 必须触发 fail-closed
- §33、§35：目录结构与 Gate 0 SQLite 初始化
- §34：INV-009、INV-010、INV-011
- 协作协议 §7–§12、§18、§22、§29–§32

## Invariants

1. 数据库路径必须由调用方显式传入；空路径、目录路径和不可用路径必须明确失败。
2. 任何未知数据库异常必须阻止继续初始化，不得删除、覆盖或“修复”原文件。
3. 损坏数据库必须抛出显式 persistence 异常，原文件内容保持不变。
4. 高于当前代码支持的 schema version 必须拒绝，禁止自动降级。
5. migration 记录与 SQLite `PRAGMA user_version` 不一致时必须拒绝，禁止猜测修复。
6. 每个 migration 必须在明确事务内原子执行；失败不得留下半张表、版本号或成功记录。
7. 重复初始化必须幂等，同一 migration 不得重复记录或重复应用。
8. 每个正常连接必须 `PRAGMA foreign_keys=ON`；设置合理的 `busy_timeout`。
9. 不得依赖 Python `assert` 承担数据库安全或版本校验。
10. 不得包含 QMT、策略、订单或真实交易能力；`live_trading_allowed` 保持 `false`。

## Bootstrap Schema Contract

当前 schema version 为 `1`。至少建立：

```text
schema_migrations
  version      INTEGER PRIMARY KEY, > 0
  name         TEXT NOT NULL UNIQUE
  applied_at   TEXT NOT NULL

application_metadata
  key          TEXT PRIMARY KEY
  value        TEXT NOT NULL
  updated_at   TEXT NOT NULL
```

要求：

- 记录 migration 1 的名称和实际应用时间。
- `application_metadata` 至少持久化 `project_name=TGrid`。
- `PRAGMA user_version` 与最新 migration version 同为 `1`。
- 不得在本任务创建 `t_lots`、orders、trades、positions 或 reservations 表。

## Acceptance Criteria

1. `tgrid.persistence` 提供清晰的显式路径初始化/连接 API，并说明调用方负责关闭连接或使用 context manager。
2. 首次初始化生成合法 SQLite 文件和 Bootstrap Schema Contract 中的内容。
3. 再次初始化不重复 migration、不丢失 metadata，结果确定且幂等。
4. 新连接验证 `foreign_keys=1`、`busy_timeout>0`；journal mode 可在 Windows 文件数据库安全使用并有测试/说明。
5. `PRAGMA quick_check` 或等价检查不是 `ok` 时 fail closed。
6. 空文件可视为全新 SQLite 数据库；非 SQLite/损坏文件必须拒绝且不得覆盖。
7. 未来 `user_version`、未来 migration version、版本不一致、migration 记录断档均明确拒绝。
8. migration 执行失败时完整回滚；再次打开仍能确定识别当前状态。
9. persistence 异常至少包含统一基类、打开/完整性/版本/迁移失败的明确子类，并保留原异常链（安全边界显式转换除外）。
10. 原有 61 项配置测试全部继续通过。
11. 无新增运行时依赖、无 QMT import、无券商/策略/交易代码、无生产 `assert`。
12. README 明确当前只增加数据库基础，仍没有 QMT 或交易能力。

## Required Tests

至少覆盖：

- 新数据库初始化与期望 schema/metadata/version。
- 重复初始化幂等。
- 连接关闭后可重新打开。
- `foreign_keys`、`busy_timeout` 和 journal mode。
- 空路径、目录路径、父目录创建或失败行为。
- 未来 `user_version` 被拒绝。
- migration 表未来版本被拒绝。
- migration 表与 `user_version` 不一致被拒绝。
- migration 版本断档/重复异常被拒绝。
- 损坏字节文件失败且文件 hash/bytes 不变。
- 注入 migration 中途异常后 DDL、版本和 migration 记录完整回滚。
- 不创建任何 Gate 2 交易领域表。
- persistence 异常层级和可捕获性。
- 原 61 项测试回归。

必须实际运行：

```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
```

## Failure Injection

至少注入并保存证据：

1. 文件头为随机/非 SQLite 字节。
2. `PRAGMA user_version=999`。
3. migration 表记录版本高于支持版本。
4. migration 表版本与 `user_version` 不一致。
5. migration 执行一半后显式抛出异常。
6. 目标路径是目录或不可创建父目录。

所有异常必须 fail closed；不得删除损坏文件或自动降级。

## Deliverables

1. Allowed Files 内的实现与测试。
2. 更新 `IMPLEMENTATION_REPORT.md`、`TEST_REPORT.md`、`QUESTIONS.md`。
3. `work/reports/tests/G0-T002-test-output.txt` 保存完整输出。
4. 更新 `CLAUDE_REPORT.md`，明确 Gate 0 尚未完成。

## Stop Condition

完成后：

1. 检查 Git diff 仅包含 Allowed Files。
2. 原子更新 `WORKFLOW_STATE.yaml`：
   - `state: "REVIEW_READY"`
   - `owner: "architect"`
   - 保持 `gate: 0`、`task_id: "G0-T002"`、`iteration: 1`
   - 更新真实本机 `last_update`；未 commit 时 `git_head_commit` 保持基线并在 notes 说明。
3. 释放 Lease。
4. 停止写入，保持只读等待架构师 Review。
