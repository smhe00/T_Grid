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
