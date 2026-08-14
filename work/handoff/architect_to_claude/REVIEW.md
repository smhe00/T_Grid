# Architecture Review — G0-T005 / Iteration 4

Status: `PASS`

Reviewed at: `2026-08-14T18:52:23+08:00`

独立 223 项回归、compileall、禁止 API/assert 扫描与范围检查通过。额外确定性暂停目标
`Thread.start()`，再交错 start failure、join 与 stop：start 仅抛安全项目异常，join 返回 True，
最终 FAILED/failure_type 正确，stop 立即返回且无残留线程。REV-G0T005-005/-006 已关闭。

G0-T005 Event Queue 骨架通过。Gate 0 仍须完成集成复核与总报告，不得提前进入 Gate 1。

---

# Architecture Review — G0-T005 / Iteration 3

Status: `CHANGES_REQUIRED`

Reviewed at: `2026-08-14T18:45:58+08:00`

独立 221 项回归与 compileall 通过；慢启动期间 stop prompt、join 单 deadline 与唯一 worker 已实现。
但并发 join 在 start failure 后仍使用等待前缓存的未启动 Thread，泄漏裸 RuntimeError；新增“永不启动”
测试还故意留下存活 daemon controller。详见 REV-G0T005-005/-006。

Gate 0 未通过，不得生成总报告或进入 Gate 1。

---

# Architecture Review — G0-T005 / Iteration 2

Status: `CHANGES_REQUIRED`

Reviewed at: `2026-08-14T18:40:33+08:00`

独立 219 项回归与 compileall 通过；start failure、有限 timeout 校验和 queue.Full 公共异常边界已修复。
但 worker.start 在 lifecycle lock 内执行，暂停启动会让 stop 和 join(timeout=0.01) 同时阻塞约 0.094 秒，
join timeout 未约束整个调用。现有 pause 测试还 patch 了控制线程自身并依靠 5 秒超时推进。详见
REV-G0T005-004。

Gate 0 未通过，不得生成总报告或进入 Gate 1。

---

# Architecture Review — G0-T005 / Iteration 1

Status: `CHANGES_REQUIRED`

Reviewed at: `2026-08-14T18:34:24+08:00`

独立 213 项回归与 compileall 通过，基础 FIFO、单 worker、stop/drain、handler BaseException 与
Lease/范围检查有效。但确定性 start/join 交错证明 RUNNING 会在线程真正启动前发布；Thread.start
失败泄漏原始异常并留下虚假 RUNNING。另有 NaN/Infinity timeout 未拒绝、EventQueueFull 链接
queue.Full 两项边界问题。详见 `FIX_REQUEST.md` 顶部。

Gate 0 未通过，不得生成总报告或进入 Gate 1。

---

# Architecture Review — G0-T004 / Iteration 4

Status: `PASS`

Reviewed at: `2026-08-14T18:19:15+08:00`

REV-G0T004-006 已关闭。独立 178 项回归、compileall、CLI smoke、成功事件顺序与禁止 API/assert
扫描全部通过；DB-close SystemExit 和 shutdown-complete GeneratorExit 均原样传播，同时 logger
shutdown 调用一次、registry 为空，真实 DB/log 文件可移动。Lease 已释放，范围符合任务。

G0-T004 离线 CLI 与 startup/shutdown 编排通过。Gate 0 仍有 Event Queue 与总报告任务。

---

# Architecture Review — G0-T004 / Iteration 3

Status: `CHANGES_REQUIRED`

Reviewed at: `2026-08-14T18:15:18+08:00`

独立 176 项回归、compileall 与 CLI smoke 通过；failure-event KeyboardInterrupt、startup
SystemExit/GeneratorExit 均已执行 DB close 与 logger shutdown。但 DB close、shutdown-complete emit
和 logger shutdown 仍在同一个 finally suite：前两步抛 SystemExit/GeneratorExit 会跳过 logger
shutdown，实际留下 registry 与打开的 handler。详见 REV-G0T004-006。

Gate 0 未通过，不得进入 Event Queue 或后续 Gate。

---

# Architecture Review — G0-T004 / Iteration 2

Status: `CHANGES_REQUIRED`

Reviewed at: `2026-08-14T18:09:51+08:00`

独立 173 项回归、compileall、CLI smoke 均通过，REV-G0T004-001、-003、-004 的直接问题已关闭，
DB close 的普通 Exception/KeyboardInterrupt 也不会再跳过 logger shutdown。但 DB close 仍不在覆盖
后续流程的 `finally` 中：failure-event emit 的 KeyboardInterrupt 以及按契约不应捕获的
SystemExit/GeneratorExit 都会在 DB 已打开后跳过 close。详见 `FIX_REQUEST.md` 顶部
REV-G0T004-005。

Gate 0 未通过，不得进入 Event Queue 或后续 Gate。

---

# Architecture Review — G0-T004 / Iteration 1

Status: `CHANGES_REQUIRED`

Reviewed at: `2026-08-14T18:03:43+08:00`

独立 167 项回归、compileall、`python -m tgrid --help/--version`、成功 preflight、路径/live/DB/log
基础注入均通过，Lease 已释放且代码范围符合任务。但 cleanup 失败仍伪记 `shutdown_complete`，
cleanup 阶段 KeyboardInterrupt 会跳过 logger shutdown，logger 建立前未知异常会逃出 main，未知异常
原文会泄露到 stderr。详见 `FIX_REQUEST.md` 顶部。

以下内容均为已关闭历史记录。

---

# Architecture Review — G0-T003 / Iteration 1

Status: `CHANGES_REQUIRED`

Reviewed at: `2026-08-14T17:37:17+08:00`

独立 126 项回归与 compileall 通过，JSONL 字段、UTF-8、并发与基本 write/flush 注入有效，
Lease 已释放，代码范围符合任务。但补充 Failure Injection 发现未配置/shutdown 后静默丢日志、
root logger 可被修改、打开异常边界缺失、flush 失败跳过 close、level 校验过宽。

详细证据与修复要求见 `FIX_REQUEST.md` 顶部。Gate 0 未通过。

## Architecture Review — G0-T003 / Iteration 3

Status: `PASS`

Reviewed at: `2026-08-14T17:50:57+08:00`

REV-G0T003-006 与 -007 已关闭。独立证据：

```text
python -m unittest discover -s tests -p "test_*.py" -v
Ran 142 tests — OK

python -m compileall -q src tests
PASS

emit/shutdown deterministic interleaving:
  shutdown blocked until emit complete; one JSON line; handler closed;
  registry empty; old path not recreated

20-thread same-name configure:
  one managed handler; registry identity exact; all files movable after shutdown;
  one emit produced exactly one line

emit after shutdown -> LoggingEmitError
AST assert / xtquant / order_stock / cancel_order scan -> PASS
Lease released -> PASS
```

G0-T003 的结构化 JSONL logging 契约、Failure Injection 与生命周期不变量全部满足。
该 PASS 不代表 Gate 0 整体完成。

## Architecture Review — G0-T003 / Iteration 2

Status: `CHANGES_REQUIRED`

Reviewed at: `2026-08-14T17:45:11+08:00`

REV-G0T003-001 至 -005 已关闭：139 项独立回归、compileall 与五项原始 Failure Injection
全部通过。但确定性并发交错证明 emit/shutdown 不是原子生命周期边界，会在 shutdown 返回后重开
文件；同名并发 configure 也会留下两个 handler、registry 仅记录一个。详见 Iteration 3 Active
Fix Request。Gate 0 仍未通过。

以下内容均为已关闭的 G0-T001/G0-T002 历史记录。

---

# Architecture Review — G0-T001 / Iteration 1

> Current task is now G0-T002. No review has been issued for G0-T002; the remaining content is accepted G0-T001 history.

# Architecture Review — G0-T002 / Iteration 1

Status: `CHANGES_REQUIRED`

Reviewed at: `2026-08-14T17:01:07+08:00`

## Scope and Baseline

- 实现源文件位于 G0-T002 Allowed Files；Lease 已由 Claude 释放。
- `CURRENT_TASK.md`、架构师 heartbeat、Gate task pointer 等基线差异来自架构师发布 G0-T002，不计入 Claude 越权。
- 架构师已修正 TGrid `.gitignore`，解除父仓库 `reports/` 规则对 Gate 测试证据的屏蔽；Claude 不需要修改 `.gitignore`。

## Independent Verification

```text
82 tests — PASS
compileall — PASS
AST assert/QMT/order scan — PASS
```

但独立数据库 Failure Injection 发现 schema 逻辑一致性未验证、畸形 migration 表泄漏原始 SQLite 异常、migration 约束缺失；本任务暂不通过。详见当前 `FIX_REQUEST.md`。

## G0-T002 / Iteration 2 Review

Status: `CHANGES_REQUIRED`

Reviewed at: `2026-08-14T17:08:35+08:00`

独立 96 项回归、compileall、AST 扫描、缺表/篡改/异常边界均通过。以下问题已关闭：

- REV-G0T002-002 — CLOSED
- REV-G0T002-004 — CLOSED
- REV-G0T002-005 — CLOSED

REV-G0T002-001 与 REV-G0T002-003 尚未满足：当前通过 DDL 文本中是否存在任意 `UNIQUE` 和宽松 CHECK 正则判断约束，存在语义 false positive。详细证据见 Iteration 3 Active Fix Request。

## G0-T002 / Iteration 3 Review

Status: `CHANGES_REQUIRED`

Reviewed at: `2026-08-14T17:16:07+08:00`

独立全量回归结果为 `100 tests — PASS`，compileall 与 AST 禁止 API/assert 扫描通过；
`UNIQUE(applied_at)`、composite UNIQUE、永真 CHECK 均已正确拒绝，合法 schema 验证前后
history 不变。REV-G0T002-003 已关闭。

REV-G0T002-001 仍有一个窄边界：仅覆盖 `name` 的 partial unique index 会被当作完整唯一约束，
即使谓词使其不覆盖任何正常 migration 版本。独立探针得到
`partial_unique_name ACCEPTED`。进入聚焦 Iteration 4，详见 `FIX_REQUEST.md` 顶部。

## G0-T002 / Iteration 4 Review

Status: `PASS`

Reviewed at: `2026-08-14T17:19:59+08:00`

REV-G0T002-001 已关闭：实现只接受 `partial=0` 且列集合恰好为 `("name",)` 的唯一索引。

独立证据：

```text
python -m unittest discover -s tests -p "test_*.py" -v
Ran 101 tests — OK

python -m compileall -q src tests
PASS

wrong-column UNIQUE -> REJECTED SchemaVersionError
composite UNIQUE -> REJECTED SchemaVersionError
partial UNIQUE(name) -> REJECTED SchemaVersionError
always-true CHECK -> REJECTED SchemaVersionError
valid schema -> ACCEPTED; migration history unchanged
AST assert / xtquant / order_stock / cancel_order scan -> PASS
Lease released -> PASS
```

G0-T002 的 Acceptance Criteria、Failure Injection 与安全不变量全部满足。该 PASS 仅接受
SQLite 初始化与迁移基础；Gate 0 整体尚未完成。



Status: `CHANGES_REQUIRED`

Reviewer: Desktop ChatGPT / Gate Owner  
Reviewed at: `2026-08-14T16:27:54+08:00`

## Scope Check

- Claude 的持久化文件均在 G0-T001 Allowed Files 内。
- 两份权威设计/协议文件、`CURRENT_TASK.md`、架构师 heartbeat 和父目录其他项目未发现被 Claude 修改的证据。
- `__pycache__` 是测试产生且已被 `.gitignore` 排除的派生文件，不作为越权变更。
- Worktree Lease 已释放。

## Independent Verification

实际运行：

```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
AST scan: assert / xtquant imports / order_stock / cancel_order
```

结果：

```text
Ran 41 tests in 0.039s — OK
compileall — PASS
AST_SCAN_OK
```

## Verdict

现有测试虽通过，但独立 Failure Injection 证明配置仍存在可绕过校验的路径。详见 `FIX_REQUEST.md`。

G0-T001 当前不得 PASS；Gate 0 仍未完成。

---

# Architecture Review — G0-T001 / Iteration 2

Status: `CHANGES_REQUIRED`

Reviewed at: `2026-08-14T16:40:46+08:00`

## Closed Issues

- REV-G0-001：重复键静默覆盖 — CLOSED
- REV-G0-002：symbols 映射可变 — CLOSED
- REV-G0-003：bar_period / anchor 未限制 — CLOSED
- REV-G0-004：交接时间戳 — CLOSED
- REV-G0-005：assert 扫描不完整 — CLOSED

独立运行 58 项测试全部通过；重复 root/global/symbol 字段的实现探针均返回 `ConfigError`，只读映射和 V1 枚举约束有效。

## Remaining Finding

严格 YAML Loader 对不可哈希 mapping key 泄漏 `TypeError`，未满足统一 `ConfigError` 契约；上一轮要求的 root 层重复键测试也未落盘。详见 `FIX_REQUEST.md` 顶部的 Iteration 3 Active Fixes。

---

# Architecture Review — G0-T001 / Iteration 3

Status: `PASS`

Reviewed at: `2026-08-14T16:45:29+08:00`

## Closed Issues

- REV-G0-006：不可哈希 YAML key 泄漏 TypeError — CLOSED
- REV-G0-007：缺少 root 重复键回归测试 — CLOSED

## Independent Evidence

```text
python -m unittest discover -s tests -p "test_*.py" -v
Ran 61 tests — OK

python -m compileall -q src tests
PASS

unhashable YAML key -> ConfigError
duplicate root key -> ConfigError
AST assert / xtquant / order_stock / cancel_order scan -> PASS
Lease released by Claude -> PASS
```

G0-T001 的 Acceptance Criteria、Failure Injection 和安全不变量全部满足。

Gate 0 尚有 SQLite、logging、CLI 和 Event Queue 子任务，因此本结论只授权架构师创建下一 Gate 0 任务，不代表 Gate 0 整体通过。
