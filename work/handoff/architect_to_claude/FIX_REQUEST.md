# Fix Request — G0-T001 / Iteration 2

> G0-T001 的 REV-G0-001 至 REV-G0-007 已全部关闭。Iteration 3 已由架构师判定 PASS；本文件现仅作为历史证据，不再授权任何修改。

# Iteration 3 Fixes（CLOSED）

## P1 — REV-G0-006：Strict YAML Loader 泄漏原始 TypeError

### Evidence

独立 Failure Injection：

```yaml
? [a, b]
: value
```

实际结果：

```text
unhashable_key WRONG_EXCEPTION TypeError unhashable type: 'list'
```

`_construct_mapping_strict` 捕获 `key in mapping` 的 `TypeError` 后继续执行 `mapping[key] = ...`，再次触发未包装的 `TypeError`。

### Affected File

```text
src/tgrid/config.py
tests/unit/test_config.py
```

### Required Behavior

- 不可哈希或非标量 YAML mapping key 必须 fail closed。
- 对调用方统一暴露 `ConfigError`，不得泄漏 `TypeError` 或其他实现异常。
- 错误信息包含键所在 line/column，且说明 mapping key 不合法。
- 不得用宽泛的 `except Exception` 吞掉无关编程错误；应在严格构造器中显式处理键类型/可哈希性。

### Required Test

新增文件级测试，验证 sequence/list key 被拒绝为 `ConfigError`，包含位置和 key 相关说明。

## P1 — REV-G0-007：缺少 root 层重复键回归测试

### Evidence

Iteration 2 已测试重复 global 字段、symbol 字段和 symbol 名称，但没有上一轮 Required Behavior 明确要求的 root 层重复 `global` 或 `symbols` 测试。独立探针证明当前代码可以拒绝，但缺少自动回归证据。

### Required Behavior / Test

新增文件级测试，至少验证 root 层重复 `global` 被 `ConfigError` 拒绝，并检查 duplicate/key/location 信息。

## Iteration 3 Completion

1. 只修 REV-G0-006 和 REV-G0-007，不扩大范围。
2. 运行完整单测、compileall 和 AST 安全扫描。
3. 更新报告与完整测试输出，逐 Issue 标记 `FIXED`。
4. 使用实际本机时间更新 `REVIEW_READY / owner=architect`，释放 Lease 并等待。

---

## Iteration 2 Historical Fixes

只修复本文件列出的问题，不扩大任务范围。

## P0 — REV-G0-001：YAML 重复键被静默覆盖（CLOSED）

### Evidence

`src/tgrid/config.py::load_config` 使用默认 `yaml.safe_load`。独立探针输入重复键后得到：

```text
DUPLICATE_KEYS_ACCEPTED live_trading=True core_qty=0
```

即同一文件中后一个值可静默覆盖：

```yaml
live_trading: false
live_trading: true

core_qty: 600
core_qty: 0
```

### Affected File

```text
src/tgrid/config.py
tests/unit/test_config.py
```

### Why It Matters

重复键可绕过人工审阅，使安全敏感配置与阅读者看到的首个值不一致，违反 fail-closed、INV-009 和 Core Floor 安全意图。

### Required Behavior

- YAML 任意 mapping 层级出现重复键时必须抛出 `ConfigError`。
- 至少覆盖 root、global、symbol 字段和重复 symbol 名称。
- 错误应包含重复键名称及尽可能明确的路径/位置。
- 不得退回默认 `safe_load` 的 last-key-wins 行为。

### Required Test

新增文件级 Failure Injection，至少验证重复 `live_trading`、重复 `core_qty` 和重复 symbol 都被拒绝。

---

## P0 — REV-G0-002：已验证配置的 symbols 映射仍可修改

### Evidence

独立探针：

```python
cfg = parse_config(valid_data)
cfg.symbols.clear()
```

实际结果：

```text
FROZEN_ROOT_MAPPING_MUTABLE before=2 after=0
```

`RootConfig` 虽为 frozen dataclass，但内部保存普通 dict；调用方可在校验后替换或删除证券配置。

### Affected File

```text
src/tgrid/models.py
src/tgrid/config.py
tests/unit/test_models.py
```

### Why It Matters

校验后可变配置会使 `core_qty`、模式和风险参数绕过配置加载校验，且当前报告“不可变模型”的结论不成立。

### Required Behavior

- `parse_config` 返回的 `RootConfig.symbols` 必须是运行时只读映射。
- 调用方不能通过赋值、`clear`、`pop`、`update` 等方式改变它。
- 不要求本任务实现配置热更新。

### Required Test

验证对 `cfg.symbols` 的赋值和 `clear()` 均失败，并确认失败后原映射内容未变化。

---

## P1 — REV-G0-003：设计限定的枚举字段接受任意字符串

### Evidence

独立探针结果：

```text
UNSUPPORTED_ENUM_ACCEPTED bar_period=tick
UNSUPPORTED_ENUM_ACCEPTED anchor=UNSUPPORTED
```

### Affected File

```text
src/tgrid/config.py
src/tgrid/models.py（如需常量）
tests/unit/test_config.py
```

### Why It Matters

设计 V1 明确使用 5 分钟 K 线且禁止 Tick 驱动交易；Anchor 只定义了 `VWAP20` 与数据不足时的 `EMA20`。任意字符串会把错误推迟到未来策略执行阶段并形成设计漂移。

### Required Behavior

- `bar_period` 在 V1 只接受 `5m`。
- `anchor` 只接受设计已定义的 `VWAP20` 或 `EMA20`；未知值必须 `ConfigError`。
- 错误包含字段路径和允许值。

### Required Test

至少验证 `bar_period: tick`、`bar_period: 1m`、`anchor: UNSUPPORTED` 被拒绝，`VWAP20` 与 `EMA20` 被接受。

---

## P1 — REV-G0-004：交接时间戳晚于监控捕获时间

### Evidence

本地监控在：

```text
2026-08-14T16:24:46+08:00
```

捕获 `REVIEW_READY`，但状态与 heartbeat 写入：

```text
last_update: 2026-08-14T16:30:00+08:00
```

### Affected File

```text
work/control/WORKFLOW_STATE.yaml
work/control/CLAUDE_HEARTBEAT.md
```

### Why It Matters

未来时间会破坏 Lease/heartbeat 陈旧判断和审计顺序。

### Required Behavior

Iteration 2 完成交接时必须从本机实际时钟读取 ISO-8601 Asia/Shanghai 时间，不得估算或手写未来时间。两处时间保持一致。

### Required Test

交接前读取本机时间并在 Implementation Report 中记录所用命令与结果；该项人工验收。

---

## P2 — REV-G0-005：测试中的 assert 扫描不完整

### Evidence

当前测试只检查：

```python
line.strip().startswith("assert ")
```

无法发现 `assert(...)`、多行或其他合法语法形式。架构师 AST 扫描本轮确认源码当前没有 `ast.Assert`，因此此问题不代表当前实现已使用 assert。

### Required Behavior

建议将测试改为 `ast.parse` + `ast.walk` 检测 `ast.Assert`。该项为 P2，不单独阻塞本任务；若修改，仍须保持在 Allowed Files 内。

## Completion

修复 P0/P1 后：

1. 运行原 41 项及新增测试。
2. 更新 Implementation Report、Test Report、完整测试输出和 Claude Report。
3. 对每个 Issue ID 写明 `FIXED` / `NOT_FIXED` / `DISAGREE` 及证据。
4. 使用真实本机时间更新为 `REVIEW_READY / owner=architect`。
5. 释放 Lease并停止。
