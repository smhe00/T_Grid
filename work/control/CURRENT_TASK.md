# Current Task — G0-T006

## Task Name

Gate 0 集成认证与总报告

## Objective

在已验收的 G0-T001 至 G0-T005 基线上执行一次只读、可复现的 Gate 0 集成认证，并生成设计要求的
`docs/GATE_0_REPORT.md`。本任务只收集证据和编写报告，不修改任何生产代码或测试，不进入 Gate 1。

## Scope

1. 核对 Git HEAD 恰为 `3e3c4529b00cc78b8db1381004fec6b069db6563`，并记录 T_Grid 范围状态。
2. 独立运行完整 unittest、compileall、禁止 API/assert AST 扫描。
3. 在系统临时目录执行离线 CLI 成功/失败 smoke；不得在仓库内创建 DB、日志或真实配置。
4. 执行 Event Queue 集成 smoke，验证 FIFO、单 worker、stop-drain、join、无线程泄漏。
5. 汇总 G0-T001 至 G0-T005 的设计、代码、测试、Failure Injection、不变量和 Git 证据。
6. 生成 `docs/GATE_0_REPORT.md`，交由 Desktop ChatGPT 最终裁决。

## Out of Scope

- 任何 `src/**`、`tests/**`、`config/**`、`README.md`、`pyproject.toml` 修改。
- 修复或重构已验收代码；发现任何失败时 fail closed，进入 `BLOCKED` 并报告，不得在本任务顺手修复。
- QMT/XtQuant 连接、行情、账号、持仓、委托、成交、策略、下单或撤单。
- 创建 Gate 1 任务、Gate 1 文件或宣布 Gate 0 PASS。
- 修改 `work/gates/GATE_0/RESULT.md`；最终 Gate 裁决只由 Desktop ChatGPT 发布。
- 自动开启 live trading；`live_trading_allowed` 必须保持 `false`。

## Design References

- 设计 §35 / §50：Gate 0 能力范围及明确禁止项。
- 设计 Gate 0 验收：必须提交 `docs/GATE_0_REPORT.md`，包含实施内容、文件列表、测试命令、
  测试结果、已知问题、下一 Gate 建议。
- 协作协议 §18：Gate PASS 必须具备 Design/Code/Test/Failure Injection/Invariant/Git Evidence。
- 已验收结果：`work/gates/GATE_0/G0-T001_RESULT.md` 至 `G0-T005_RESULT.md`。

## Invariants

1. `live_trading_allowed: false`，且配置缺省/示例 `live_trading=false`。
2. 无 `xtquant` import，无 `order_stock` / `cancel_order`，无 QMT/账号/行情/交易能力。
3. 生产安全路径无 `assert`。
4. 所有配置、数据库、日志路径显式；失败 fail closed，不泄漏 traceback/secret。
5. SQLite migration 幂等且拒绝损坏、未来版本、schema 身份不一致。
6. JSONL 每行可解析；logger 生命周期确定且失败不伪报成功。
7. CLI 仅离线 preflight，资源在普通异常及 `BaseException` 边界确定清理。
8. Event Queue 有界、FIFO、唯一非 daemon worker；失败进入 FAILED 且无线程泄漏。
9. 不修改已通过能力；认证输出只含文档、控制面和证据。

## Acceptance Criteria

1. Git HEAD 与指定基线一致；认证前 T_Grid 除本任务架构师分配文件外无未知变更。
2. `python -m unittest discover -s tests -p "test_*.py" -v` 全部通过，测试数不得少于 223。
3. `python -m compileall -q src tests` 退出码 0。
4. AST 扫描全部 `src/tgrid/**/*.py`：无 `ast.Assert`、无 `xtquant` import、无
   `order_stock` / `cancel_order` 调用。
5. 离线 CLI：help/version 成功；临时目录 valid preflight 退出 0 且 JSONL 事件顺序恰为
   `startup_begin, preflight_ok, shutdown_complete`；`live_trading=true` 在 DB/log 写入前拒绝。
6. Event Queue 集成 smoke：至少 100 个成功接受事件 FIFO/恰好一次、只在一个 worker 处理；stop 后
   join=True、最终 STOPPED、无同名线程；handler failure 路径最终 FAILED 且 pending 不再 dispatch。
7. `docs/GATE_0_REPORT.md` 包含实施内容、完整文件/能力列表、命令与真实结果、五个已通过子任务/commit、
   Failure Injection、不变量、已知问题、风险评估与下一 Gate 建议。
8. 报告必须明确：这是 Claude 的认证报告，不是最终 Gate 裁决；未经 Desktop ChatGPT PASS 不进入 Gate 1。
9. 完整命令输出保存到 `work/reports/tests/G0-T006-gate0-certification.txt`，且无 traceback、
   `Exception in thread`、secret 或残留线程。
10. 只修改 Allowed Files；不提交 commit。

## Required Tests / Failure Injection

必须实际运行并保存完整输出：

```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
python -m tgrid --help
python -m tgrid --version
AST forbidden-API scan
isolated valid preflight
isolated live_trading=true rejection before DB/log write
Event Queue FIFO/single-worker/stop-drain/thread-cleanup smoke
Event Queue handler failure/pending-discard smoke
```

临时配置、SQLite、JSONL 只允许位于 `tempfile.TemporaryDirectory()` 等系统临时目录，并在命令结束后
清理。不得访问真实 QMT、真实账号、真实行情或真实交易配置。

## Allowed Files

Claude 只能新增或修改：

```text
docs/GATE_0_REPORT.md
work/reports/tests/G0-T006-gate0-certification.txt
work/gates/GATE_0/CLAUDE_REPORT.md
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md
work/handoff/claude_to_architect/TEST_REPORT.md
work/handoff/claude_to_architect/QUESTIONS.md
work/control/CLAUDE_HEARTBEAT.md
work/control/WORKFLOW_STATE.yaml
```

`WORKFLOW_STATE.yaml` 仅允许更新 `state`、`owner`、`iteration`、`last_actor`、`last_update`、
`git_head_commit`、`notes` 和必要的 escalation 字段；不得改变 design/protocol/task 路径、Gate、
`git_base_commit` 或 `live_trading_allowed`。

## Forbidden Files

除 Allowed Files 外的全部文件，尤其：

```text
src/**
tests/**
config/**
README.md
pyproject.toml
TGrid_双Agent协作与Gate验收协议_V1.0.md
TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md
work/control/CURRENT_TASK.md
work/control/ARCHITECT_HEARTBEAT.md
work/gates/GATE_0/TASK.md
work/gates/GATE_0/ARCHITECT_REVIEW.md
work/gates/GATE_0/RESULT.md
work/gates/GATE_1/**
父目录 D:/gitee/miniQMT 中 T_Grid 之外的全部文件
```

## Deliverables

1. `docs/GATE_0_REPORT.md`。
2. 完整认证输出 `work/reports/tests/G0-T006-gate0-certification.txt`。
3. 更新 Claude Gate、Implementation、Test、Questions 报告。
4. 无 commit；最终提交和 Gate 裁决由 Desktop ChatGPT 执行。

## Stop Condition

所有认证通过后，检查 diff 只含 Allowed Files，释放 Lease，并原子更新：

```text
state: REVIEW_READY
owner: architect
iteration: 1
last_actor: claude
git_head_commit: 3e3c4529b00cc78b8db1381004fec6b069db6563
live_trading_allowed: false
```

然后停止修改并等待 Review。

任一命令失败、HEAD 漂移、未知范围修改、无法清理线程/临时资源或证据冲突时，不得修生产代码；设置
`BLOCKED`（需要人类决策时用 `USER_ESCALATION`），记录准确原因并停止。
