# Task G0-T003 — 结构化 JSONL Logging 基础

## Goal

建立 Gate 0 的可靠日志基础：调用方显式指定文件路径，输出可机器解析、可审计的 UTF-8 JSONL，
并对配置、序列化和写入失败执行 fail closed。当前任务只实现 logging，不实现 CLI、Event Queue、
QMT、策略或交易功能。

## In Scope

1. 新增 `tgrid.reporting` 包及结构化 logging 模块。
2. 仅使用 Python 标准库 `logging`、`json` 等，不增加第三方运行时依赖。
3. 提供显式日志文件路径的配置 API、结构化事件写入 API 和显式 shutdown/close API。
4. 输出一行一个 JSON object 的 UTF-8 JSONL，适合后续 Gate 审计与故障定位。
5. 重复初始化、handler 生命周期、并发写入和错误边界可预测且有测试。
6. 新增明确的 logging 异常层级与 Failure Injection。

## Out of Scope

- CLI、进程主入口、startup/shutdown 编排；后续 Gate 0 子任务实现。
- Event Queue、状态机、调度器或后台线程。
- SQLite audit/domain 表或把日志写入数据库。
- QMT/XtQuant、行情、账号、持仓、委托、成交、下单或撤单。
- 策略计算、SimBroker、dry-run、shadow/live execution。
- 上传、远程传输、告警、邮件、云日志或日志查看 UI。
- 自动读取配置文件、环境变量、账号信息或默认真实路径。
- Git push；Claude 不得 commit。

## Allowed Files

Claude 只能新增或修改：

```text
README.md
src/tgrid/__init__.py
src/tgrid/risk/__init__.py
src/tgrid/risk/exceptions.py
src/tgrid/reporting/__init__.py
src/tgrid/reporting/logging.py
tests/unit/test_logging.py
work/control/WORKFLOW_STATE.yaml
work/control/CLAUDE_HEARTBEAT.md
work/locks/WORKTREE_LEASE.yaml
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md
work/handoff/claude_to_architect/TEST_REPORT.md
work/handoff/claude_to_architect/QUESTIONS.md
work/gates/GATE_0/CLAUDE_REPORT.md
work/reports/tests/G0-T003-test-output.txt
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
src/tgrid/persistence/**
tests/unit/test_config.py
tests/unit/test_models.py
tests/unit/test_persistence.py
work/control/CURRENT_TASK.md
work/control/ARCHITECT_HEARTBEAT.md
work/gates/GATE_0/TASK.md
work/gates/GATE_0/G0-T001_RESULT.md
work/gates/GATE_0/G0-T002_RESULT.md
work/gates/GATE_0/ARCHITECT_REVIEW.md
work/handoff/architect_to_claude/**
work/design/**
父目录 D:/gitee/miniQMT 中 T_Grid 之外的全部文件
```

除 Allowed Files 外不得新增或修改其他文件。

## Design References

- 设计文档 §29：SAFE_HALT 后仍须保留日志。
- §33：推荐目录结构与真实日志不得提交 Git。
- §34：INV-009 fail closed、INV-011 禁止生产风控依赖 `assert`。
- §35：Gate 0 必须实现并测试 logging，禁止 QMT 下单代码。
- §52：当前阶段禁止 QMT、行情、策略和真实账号访问。
- 协作协议 §7–§12、§18、§22、§29–§32。

## Event Contract

每条成功日志必须恰好写入一个 JSON object 和一个换行符，至少包含：

```text
schema_version  整数，当前固定为 1
timestamp       UTC ISO-8601，必须带时区
level           标准大写级别名称
logger          logger 名称
event           调用方显式传入的非空事件名
message         字符串消息
context         JSON object；无扩展字段时为空 object
```

要求：

- 中文、换行、引号等内容必须通过 JSON 转义保持单行并可无损解析。
- `context` key 必须是非空字符串；不得覆盖上述保留字段。
- 不可 JSON 序列化的值必须同步抛出明确 logging 异常，不得静默丢日志或只写半行。
- 本模块不得自动采集配置、环境变量、账号或任何真实交易信息。

## Logging Lifecycle Contract

1. 调用方必须显式传入日志文件路径；空路径、目录路径和不可用路径明确失败。
2. 可以创建不存在的父目录，但不得自动选择 `data/`、用户目录或其他默认真实路径。
3. 只配置 TGrid 自己的 named logger，不得清空、替换或改变 root logger 的既有 handlers/level。
4. TGrid logger 必须 `propagate=False`，避免重复写入 root。
5. 同一 logger 重复配置时不得产生重复 handler 或重复行；旧的 TGrid-owned handler 必须 flush/close。
6. shutdown/close 必须幂等并释放文件句柄；Windows 上关闭后文件应可移动/删除。
7. 标准库 logging 的内部错误不得被静默吞掉；配置、序列化和写入失败必须转换为明确异常并保留异常链。
8. 不得依赖 `logging.raiseExceptions` 才能暴露生产错误。

## Invariants

1. 成功返回表示日志文件已可写且 logger 生命周期已正确建立。
2. 任何失败不得留下半条 JSON、重复 handler 或仍占用的失败文件句柄。
3. 每条成功事件都是独立、完整、可解析的一行 JSON。
4. 重复配置与重复 shutdown 均确定且幂等。
5. 并发调用不得产生交错、截断或不可解析 JSON。
6. 生产安全与错误检查不得依赖 Python `assert`。
7. 不得包含 QMT、策略、订单或真实交易能力；`live_trading_allowed` 保持 `false`。

## Acceptance Criteria

1. 公共 API 命名清晰并在 docstring/README 说明调用方负责显式路径和 shutdown 生命周期。
2. 单条事件输出满足 Event Contract，UTF-8/中文/嵌入换行可无损 round-trip。
3. level 至少支持标准 logging 整数级别；非法 level 明确拒绝。
4. `context` 只接受字符串 key 与 JSON-compatible value；保留字段冲突、非字符串 key、不可序列化值均 fail closed。
5. 重复配置同一 logger 不重复输出，旧 handler 被关闭；不同 logger 互不干扰。
6. root logger 的 handlers、level 和 propagate 行为不被修改。
7. shutdown 后不再持有文件句柄，重复 shutdown 不报错。
8. 多线程并发至少写入 100 条事件，行数完整、每行可解析且 event/message 不丢失。
9. 文件配置/打开失败抛显式 logging 异常；事件 emit/flush 失败抛显式 logging 异常，不得只写 stderr 后继续。
10. 日志文件/临时产物不提交仓库；测试全部使用临时目录。
11. 原有 101 项测试全部继续通过。
12. 无新增运行时依赖、无 QMT import、无券商/策略/交易代码、无生产 `assert`。
13. README 明确当前新增结构化日志基础，但仍没有 CLI、QMT 或交易能力。

## Required Tests

至少覆盖：

- 基本 JSONL 字段、UTC timestamp、级别和 UTF-8 round-trip。
- message 含换行/引号时仍只产生一条可解析物理行。
- 空 context 与多个合法 context 字段。
- 空 event、非法 level、保留字段冲突、非字符串 context key、不可序列化值。
- 空路径、目录路径、不存在父目录创建、文件打开失败。
- 同一 logger 重复配置不重复写行且旧 handler 关闭。
- 不同 logger 隔离；root logger 配置前后完全不变。
- shutdown/重复 shutdown；关闭后文件可重命名或删除。
- 注入 handler write/flush 失败并验证显式异常传播。
- 100 条以上多线程并发写入，逐行 `json.loads` 并核对唯一事件集合。
- AST 扫描生产源码无 `assert`、无 `xtquant`、无 `order_stock`/`cancel_order`。
- 原 101 项测试回归。

必须实际运行：

```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
```

## Failure Injection

至少注入并保存证据：

1. 目标路径是目录。
2. 父路径不可创建或 FileHandler 打开失败。
3. context 含不可 JSON 序列化对象。
4. handler stream 在 emit 或 flush 时抛 `OSError`。
5. 重复配置同一 logger 后写一条事件。
6. message 含换行与非 ASCII 字符。

所有异常必须 fail closed；不得产生伪成功报告、半行 JSON 或 handler 泄漏。

## Deliverables

1. Allowed Files 内的实现与测试。
2. 更新 `IMPLEMENTATION_REPORT.md`、`TEST_REPORT.md`、`QUESTIONS.md`。
3. `work/reports/tests/G0-T003-test-output.txt` 保存完整输出与 Failure Injection 证据。
4. 更新 `CLAUDE_REPORT.md`，明确 Gate 0 尚未完成。

## Stop Condition

完成后：

1. 检查 Git diff 仅包含 Allowed Files。
2. 原子更新 `WORKFLOW_STATE.yaml`：
   - `state: "REVIEW_READY"`
   - `owner: "architect"`
   - 保持 `gate: 0`、`task_id: "G0-T003"`、`iteration: 1`
   - 更新真实本机 `last_update`；未 commit 时 `git_head_commit` 保持基线并在 notes 说明。
3. 释放 Lease。
4. 停止写入，保持只读等待架构师 Review。
