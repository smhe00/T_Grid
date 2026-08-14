# Active Fix Request — G0-T002 / Iteration 4

## P1 — REV-G0T002-001（OPEN）：partial unique index 仍被误判为完整 name 唯一约束

### Evidence

独立探针将内联 `name TEXT NOT NULL UNIQUE` 替换为：

```sql
CREATE UNIQUE INDEX uq_partial_name
ON schema_migrations(name)
WHERE version > 100;
```

`PRAGMA index_info` 仍返回单列 `name`，当前 `_get_unique_index_column_sets` 忽略
`PRAGMA index_list` 的 `partial` 标志，因此 `initialize()` 接受该 schema；但正常 migration
版本并不受这个索引约束，`name` 实际可重复。

```text
partial_unique_name ACCEPTED [(1, 'bootstrap', ...)]
```

### Required Behavior

- 只有覆盖恰好 `("name",)` 且 `partial=0` 的 UNIQUE index 才能满足契约。
- partial unique index 无论谓词为何，均不得被当作完整单列唯一约束。
- 保持 Iteration 3 已通过的 wrong-column、composite、CHECK 行为探针及合法 history 无副作用性质。

### Required Test

- 使用 `WHERE version > 100` 的 partial unique index 必须被 `SchemaVersionError`（或其他明确
  `PersistenceError` 子类）拒绝。
- 合法 bootstrap schema、`UNIQUE(applied_at)`、composite UNIQUE、永真 CHECK 的现有测试继续通过。
- 全量回归、compileall、AST 禁止 API 扫描继续通过。

### Scope / Completion

只修改 `src/tgrid/persistence/database.py`、`tests/unit/test_persistence.py` 及本任务允许的
Claude 报告/测试输出/状态文件。不得进入 logging、CLI、Event Queue、Gate 2 或 QMT。
完成后设置 `REVIEW_READY / owner=architect / iteration=4`，使用真实本机时间，释放 Lease并停止。

---

# Historical Fix Requests

> 下面内容均为已关闭或已被 Iteration 4 取代的历史记录；当前唯一授权是文件顶部的 Iteration 4 Active Fix Request。

# Active Fix Request — G0-T002 / Iteration 2

> Iteration 2 后 REV-G0T002-002、-004、-005 已关闭。REV-G0T002-001 与 -003 保持 OPEN；当前只处理下面的 Iteration 3 Active Fix Request。

# Iteration 3 Active Fix Request

## P1 — REV-G0T002-001（OPEN）：UNIQUE 约束验证未绑定 name 列

### Evidence

伪造 schema 使用：

```sql
CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY CHECK(version > 0),
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL UNIQUE
);
```

列形状正确且 DDL 含 `UNIQUE`，当前 `_verify_bootstrap_schema` 接受。独立行为探针结果：

```text
unique_wrong_column INITIALIZE_ACCEPTED DUPLICATE_NAME_ACCEPTED
```

### Required Behavior

- 验证唯一性约束确实覆盖且只覆盖 `schema_migrations.name`，不得只搜索任意 `UNIQUE` 文本。
- 优先使用 `PRAGMA index_list` + `PRAGMA index_info/index_xinfo` 等 SQLite 结构化元数据。
- 缺失 name 唯一约束、唯一约束落在错误列或错误组合列时必须 `PersistenceError` 子类。

### Required Test

- 上述 `UNIQUE(applied_at)` 伪造表必须拒绝。
- `UNIQUE(name, applied_at)` 但 name 单列不唯一时必须拒绝。
- 合法 bootstrap schema 必须接受。

## P1 — REV-G0T002-003（OPEN）：CHECK 正则接受永真约束

### Evidence

伪造 schema 使用：

```sql
version INTEGER PRIMARY KEY CHECK(version > 0 OR 1=1)
```

当前正则匹配到前缀后接受。行为探针结果：

```text
check_always_true INITIALIZE_ACCEPTED VERSION_ZERO_ACCEPTED
```

### Required Behavior

- 验证数据库实际拒绝 `version=0` 与负数，而不是仅匹配 DDL 文本。
- 建议在 `SAVEPOINT` 内执行约束探针，预期 `sqlite3.IntegrityError`，随后完整 rollback/release；不得留下 probe 行或改变 migration history。
- 若继续解析 DDL，必须能可靠拒绝永真/弱化表达式；不能使用当前前缀正则。
- 验证过程自身出现意外 SQLite 错误时按 persistence 异常边界 fail closed。

### Required Test

- `CHECK(version > 0 OR 1=1)` 伪造表必须拒绝。
- 无 CHECK 表必须拒绝。
- 合法表验证前后 migration history 完全不变。

## Iteration 3 Completion

1. 只修上述两个 OPEN 问题。
2. 完整运行回归、compileall、AST 扫描与两条独立语义 Failure Injection。
3. 更新报告/完整测试输出，逐项回复 `FIXED`。
4. `REVIEW_READY / owner=architect`，释放 Lease并只读等待。

---

# Iteration 2 Historical Request

只修复以下问题，不扩大到 logging、CLI、Event Queue、Gate 2 领域表或 QMT。

## P0 — REV-G0T002-001：版本记录正确时未验证真实 Bootstrap Schema

### Evidence

独立探针初始化合法数据库后执行：

```sql
DROP TABLE application_metadata;
```

再次调用 `initialize(path)` 的结果：

```text
missing_metadata ACCEPTED tables=['schema_migrations']
```

将 migration 1 的名称改成 `not_bootstrap` 后也被接受：

```text
name_tamper ACCEPTED [(1, 'not_bootstrap')]
```

### Why It Matters

`user_version` 与数字版本记录一致并不能证明实际 schema 与代码迁移定义一致。系统会把被删表、错表或被篡改迁移身份的数据库误判为可用，违反 fail-closed 和不可静默修复原则。

### Required Behavior

- 在返回已初始化连接前验证当前版本对应的 Bootstrap Schema Contract。
- `schema_migrations` 与 `application_metadata` 必须存在，列名、关键类型、NOT NULL、PK/UNIQUE/CHECK 约束满足契约。
- migration history 的 `(version, name)` 必须逐项匹配代码中的 `MIGRATIONS`，`applied_at` 必须非空。
- `application_metadata` 必须存在唯一 `project_name=TGrid` 且 `updated_at` 非空。
- 缺表、错列、错约束、改名或 metadata 缺失/篡改必须抛出明确的 `PersistenceError` 子类，禁止自动重建或修补。

### Required Tests

至少新增：删除 metadata 表、删除 project_name、篡改 project_name、篡改 migration name、缺列/错表结构，全部 fail closed。

---

## P1 — REV-G0T002-002：畸形 migration 表泄漏原始 OperationalError

### Evidence

数据库包含：

```sql
CREATE TABLE schema_migrations (wrong INTEGER);
PRAGMA user_version=1;
```

实际结果：

```text
malformed_history WRONG_EXCEPTION OperationalError no such column: version
```

### Required Behavior

- `initialize` / `open_database` 的数据库结构或 SQLite 操作失败必须转换成明确的 `PersistenceError` 子类并保留异常链。
- 不得通过宽泛捕获吞掉 `KeyboardInterrupt`/`SystemExit`，也不得把编程错误伪装为数据库损坏。
- 对已识别的 SQLite schema/查询错误做边界转换并关闭连接。

### Required Tests

验证 wrong-column `schema_migrations`、wrong-column `application_metadata` 均抛 `PersistenceError` 子类而非裸 `sqlite3.Error`，且连接/文件仍可审计。

---

## P1 — REV-G0T002-003：schema_migrations 缺少 version > 0 约束

### Evidence

任务的 Bootstrap Schema Contract 明确要求：

```text
version INTEGER PRIMARY KEY, > 0
```

当前 DDL 没有 `CHECK(version > 0)`，独立探针结果：

```text
version_zero INSERT_ACCEPTED
```

### Required Behavior / Test

- Bootstrap DDL 增加数据库级 `CHECK(version > 0)`。
- 测试插入 version 0 与负数均触发 `sqlite3.IntegrityError`。
- schema contract 验证能识别缺失该约束的伪造表并 fail closed。

---

## P1 — REV-G0T002-004：保存的禁止 API 扫描实际执行失败

### Evidence

`G0-T002-test-output.txt` 包含：

```text
grep: xtquant: No such file or directory
/usr/bin/bash: line 1: from: command not found
/usr/bin/bash: line 1: order_stock(: command not found
```

随后仍打印 `NO forbidden imports/calls`，该证据无效。架构师独立 AST 扫描当前源码确实通过，因此这是测试/报告可信度问题，不代表源码含禁用调用。

### Required Behavior / Test

- 使用 Python AST 测试扫描全部 `src/tgrid/**/*.py`：`ast.Assert`、`xtquant` import、`order_stock`/`cancel_order` Call。
- 命令任一错误必须非零退出，不得在失败后打印 PASS。
- 重新生成完整测试输出，不保留上述伪成功文本。

---

## P1 — REV-G0T002-005：journal mode 测试把 off/memory 视为安全

### Evidence

当前测试允许：

```python
{"delete", "wal", "truncate", "persist", "memory", "off"}
```

`OFF` 不提供回滚日志保护，`MEMORY` 也不满足文件数据库 crash durability 目标。

### Required Behavior / Test

- 初始化后的文件数据库 journal mode 只允许明确的持久化安全模式，例如 `delete`、`wal`、`truncate`、`persist`。
- 测试不得把 `off` 或 `memory` 判为 PASS。
- 若代码主动设置 journal mode，必须检查 SQLite 返回的实际模式；设置失败则 fail closed。

## Architect-Owned Audit Fix

父仓库 `.gitignore` 的通用 `reports/` 规则曾忽略完整测试输出。架构师已在 TGrid `.gitignore` 中显式恢复 `work/reports/**` 跟踪；Iteration 2 交接时应确认 `G0-T001-test-output.txt` 与 `G0-T002-test-output.txt` 均出现在 Git status/diff 中。

## Completion

1. 修复 REV-G0T002-001 至 REV-G0T002-005。
2. 运行完整回归、compileall、AST 安全扫描及上述 Failure Injection。
3. 更新 Implementation Report、Test Report、Claude Report 和完整测试输出，逐 Issue 回复 `FIXED`/`NOT_FIXED`/`DISAGREE`。
4. 更新为 `REVIEW_READY / owner=architect`，使用真实本机时间，释放 Lease并只读等待。

---

# Closed G0-T001 History

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
