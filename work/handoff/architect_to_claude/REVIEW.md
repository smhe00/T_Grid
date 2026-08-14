# Architecture Review — G0-T001 / Iteration 1

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

