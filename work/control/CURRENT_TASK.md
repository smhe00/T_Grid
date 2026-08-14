# Task G0-T004 — 离线 CLI 与 Startup/Shutdown 编排

## Goal

建立 Gate 0 的离线命令行入口与确定性 startup/shutdown 生命周期，把已经验收的配置、SQLite 与
JSONL logging 基础组合成一个只读配置校验和本地 preflight 流程。当前任务不得连接 QMT、读取真实
账号或产生任何交易行为。

## In Scope

1. 新增 `tgrid.main` 与 `tgrid.__main__`，并在 `pyproject.toml` 注册 `tgrid` console script。
2. 提供 `--help`、`--version` 与 `preflight` 子命令。
3. `preflight` 只执行：显式参数校验、加载配置、拒绝 live trading、配置 JSONL logger、初始化/
   验证 SQLite、记录 startup/shutdown 事件、关闭全部资源。
4. 定义稳定退出码与无 traceback 的用户级错误输出。
5. 对所有部分启动失败和 shutdown 失败进行可测试、fail-closed 的资源清理。

## Out of Scope

- Event Queue、后台 worker、定时器或常驻进程；后续 Gate 0 子任务实现。
- QMT/XtQuant、行情、账号、持仓、委托、成交、下单或撤单。
- 策略计算、SimBroker、dry-run、shadow/live execution。
- `run`/`trade`/`live` 命令、自动重试或自动恢复。
- 自动发现配置、数据库、日志路径，或读取环境变量中的真实路径/账号。
- 修改已经验收的 config、persistence、reporting 实现。
- Git push；Claude 不得 commit。

## Allowed Files

Claude 只能新增或修改：

```text
pyproject.toml
README.md
src/tgrid/__init__.py
src/tgrid/__main__.py
src/tgrid/main.py
src/tgrid/risk/__init__.py
src/tgrid/risk/exceptions.py
tests/unit/test_cli.py
work/control/WORKFLOW_STATE.yaml
work/control/CLAUDE_HEARTBEAT.md
work/locks/WORKTREE_LEASE.yaml
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md
work/handoff/claude_to_architect/TEST_REPORT.md
work/handoff/claude_to_architect/QUESTIONS.md
work/gates/GATE_0/CLAUDE_REPORT.md
work/reports/tests/G0-T004-test-output.txt
```

`WORKTREE_LEASE.yaml` 只在工作期间存在，交接前必须释放删除。

## Forbidden Files

```text
TGrid_双Agent协作与Gate验收协议_V1.0.md
TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md
.gitignore
config/**
src/tgrid/config.py
src/tgrid/models.py
src/tgrid/persistence/**
src/tgrid/reporting/**
tests/unit/test_config.py
tests/unit/test_models.py
tests/unit/test_persistence.py
tests/unit/test_logging.py
work/control/CURRENT_TASK.md
work/control/ARCHITECT_HEARTBEAT.md
work/gates/GATE_0/TASK.md
work/gates/GATE_0/G0-T001_RESULT.md
work/gates/GATE_0/G0-T002_RESULT.md
work/gates/GATE_0/G0-T003_RESULT.md
work/gates/GATE_0/ARCHITECT_REVIEW.md
work/handoff/architect_to_claude/**
work/design/**
父目录 D:/gitee/miniQMT 中 T_Grid 之外的全部文件
```

除 Allowed Files 外不得新增或修改其他文件。

## Design References

- 设计文档 §29：SAFE_HALT 保留日志且不得自动平仓。
- §30：配置、数据库及未知异常必须 fail closed。
- §33：`main.py` 推荐入口与真实数据/日志不得提交 Git。
- §34：INV-009 fail closed、INV-010 幂等、INV-011 禁止生产安全依赖 `assert`。
- §35：Gate 0 必须实现 CLI 并测试 startup/shutdown、invalid config，禁止 QMT 下单代码。
- §52：当前阶段明确禁止 QMT、行情、策略和真实账号访问。
- 协作协议 §7–§12、§18、§22、§29–§32。

## CLI Contract

必须支持：

```text
python -m tgrid --help
python -m tgrid --version
python -m tgrid preflight --config <path> --database <path> --log <path>
```

安装后 console script `tgrid` 必须指向同一 `main(argv=None) -> int` 入口。

### Explicit Paths

- `preflight` 的三个路径参数全部 required，不提供默认路径，不读取环境变量。
- 在任何写入前将路径规范化并验证 config/database/log 两两不同；相同路径或可解析为同一路径的
  alias 必须拒绝，避免日志或 SQLite 覆盖配置。
- config 只读；database 与 log 可由已验收模块创建父目录。

### Preflight Order

```text
parse explicit CLI arguments
normalize and validate distinct paths
load_config(config_path)
reject config.global.live_trading == true
configure_jsonl_logger(..., log_path)
emit startup_begin
initialize_database(database_path)
emit preflight_ok
close database
emit shutdown_complete
shutdown_logger
return 0
```

实现可调整内部函数划分，但不得改变安全顺序：live trading 与路径冲突必须在数据库/日志写入前拒绝。

## Exit Contract

```text
0    preflight 成功或 --help/--version 正常完成
1    TGrid 配置、logging、database、startup/shutdown 等受控失败
2    argparse 用法/缺参错误（标准 argparse 行为）
130  KeyboardInterrupt
```

- 受控失败向 stderr 输出一行简洁错误，禁止 traceback。
- stdout 只输出稳定、简洁的成功信息或 help/version；不得输出配置内容、账号或敏感数据。
- 不捕获 `SystemExit`/`GeneratorExit`；`KeyboardInterrupt` 单独映射 130。

## Logging Contract

成功 preflight 的 JSONL event 顺序必须是：

```text
startup_begin
preflight_ok
shutdown_complete
```

context 只允许非敏感、稳定字段，例如 `schema_version` 不得由调用方覆盖；不得记录完整配置、环境变量、
原始异常文本、账号信息或证券数量。失败发生在 logger 建立后时，应尽力记录稳定事件名与异常类型，
但日志失败本身必须使 CLI 非零退出，不能伪报成功。

## Lifecycle / Failure Rules

1. 任一步失败均返回非零且不得继续到后续业务步骤。
2. logger 配置后，无论 DB 初始化、事件写入还是其他受控异常，最终都必须尝试 shutdown logger。
3. DB 成功打开后，无论后续步骤是否失败都必须 close；Windows 上返回后 DB/log 文件可移动。
4. shutdown 中出现失败不能被吞掉；若启动异常与清理异常同时发生，保留主要失败并在安全边界报告清理失败，
   不得返回 0。
5. `preflight` 可重复运行：SQLite migration 不重复，JSONL 追加新的一组完整生命周期事件。
6. Gate 0 无任何可开启 live trading 的路径；配置中 `live_trading: true` 必须在创建 DB/log 前拒绝。
7. 生产安全不得依赖 Python `assert`。

## Acceptance Criteria

1. `python -m tgrid --help`、`--version` 与 console entry point 配置正确。
2. 缺少子命令或 required 参数时使用 argparse 标准 usage，退出 2。
3. 合法、`live_trading=false` 配置的 preflight 返回 0，创建/验证 DB 与 JSONL，并按契约输出三事件。
4. 配置中 `live_trading=true` 返回 1，且 DB/log 均未创建。
5. 三路径冲突或 alias 冲突返回 1，并在任何数据库/日志写入前停止。
6. invalid config、损坏 DB、日志打开失败、emit 失败均返回 1、无 traceback、无 success 文本。
7. 部分启动失败后所有已获取资源关闭；故障注入后文件在 Windows 可移动/删除。
8. 正常与失败 shutdown 顺序有测试；清理失败不能改变为成功。
9. 重复 preflight 两次，migration history 仍一条，日志为两组按序事件，不覆盖原日志。
10. 用户级输出不包含完整配置、数据库内容、原始 traceback 或敏感字段。
11. 原有 142 项测试全部继续通过。
12. 无新增第三方运行时依赖、无 QMT import、无券商/策略/交易代码、无生产 `assert`。
13. README 明确 CLI 仅做离线 preflight，无 QMT/交易能力，并给出全部显式参数示例。

## Required Tests

至少覆盖：

- parser/help/version、缺子命令、缺 required 参数与 exit code。
- `main(argv)` 成功路径及 `python -m tgrid` 子进程最小 smoke（不调用 QMT）。
- 成功 JSONL 三事件顺序、SQLite `user_version=1` 与 migration history 幂等。
- `live_trading=true` 在 DB/log 创建前拒绝。
- config/database、config/log、database/log 相同或 alias 路径冲突。
- invalid YAML/配置、损坏 DB、日志目录路径/打开失败。
- 注入 `initialize_database`、`emit`、DB close、`shutdown_logger` 失败，核对退出码和清理调用顺序。
- startup 失败与 shutdown 失败同时发生时仍非零且无 traceback。
- KeyboardInterrupt 返回 130，并清理已获取资源。
- 重复 preflight 两次：DB migration 不重复、日志六事件按两组排列。
- stdout/stderr 契约和敏感信息不泄漏。
- AST 扫描生产源码无 `assert`、无 `xtquant`、无 `order_stock`/`cancel_order`。
- 原 142 项测试回归。

必须实际运行：

```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
python -m tgrid --help
python -m tgrid --version
```

## Failure Injection

至少注入并保存证据：

1. invalid YAML / `live_trading=true`。
2. 三类路径冲突。
3. 损坏 SQLite 文件。
4. log 目标为目录或 FileHandler 打开失败。
5. startup event / preflight event emit 失败。
6. DB close 与 logger shutdown 失败。
7. KeyboardInterrupt 发生在 logger 建立后或 DB 打开后。

所有异常必须 fail closed；不得连接 QMT、不得产生订单、不得把失败打印为成功。

## Deliverables

1. Allowed Files 内的实现与测试。
2. 更新 `IMPLEMENTATION_REPORT.md`、`TEST_REPORT.md`、`QUESTIONS.md`。
3. `work/reports/tests/G0-T004-test-output.txt` 保存完整输出、CLI smoke 与 Failure Injection 证据。
4. 更新 `CLAUDE_REPORT.md`，明确 Gate 0 尚未完成。

## Stop Condition

完成后：

1. 检查 Git diff 仅包含 Allowed Files。
2. 原子更新 `WORKFLOW_STATE.yaml`：
   - `state: "REVIEW_READY"`
   - `owner: "architect"`
   - 保持 `gate: 0`、`task_id: "G0-T004"`、`iteration: 1`
   - 更新真实本机 `last_update`；未 commit 时 `git_head_commit` 保持基线并在 notes 说明。
3. 释放 Lease。
4. 停止写入，保持只读等待架构师 Review。
