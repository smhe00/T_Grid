# Test Report — G0-T002 / Iteration 4

## Environment
- Python 3.12.10
- PyYAML 6.0.3
- 平台：Windows 10

## Commands Run

```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
```

## Results

```text
Ran 101 tests in 0.615s
OK
```

`compileall` 退出码 0。

完整逐条输出已存档于 `work/reports/tests/G0-T002-test-output.txt`（含 AST 扫描与独立语义探针）。

## Fix Verification（Iteration 4）

| Issue | 验证点 | 结果 |
|---|---|---|
| REV-G0T002-001 | partial unique index（`WHERE version > 100`）拒绝；合法单列 UNIQUE(name) 接受 | PASS |

## 独立语义 Failure Injection（行为探针）

```text
unique_wrong_column  REJECTED
composite_unique     REJECTED
check_always_true    REJECTED
partial_unique_name  REJECTED
```

## Coverage by Requirement（累计）

| 要求 | 测试 | 结果 |
|---|---|---|
| 新数据库初始化 / 幂等 / 重开 | `TestInitialize.*` | PASS |
| `foreign_keys` / `busy_timeout` / journal mode | `test_foreign_keys_and_busy_timeout` / `test_journal_mode_safe_on_windows` | PASS |
| 路径校验 | `TestPathValidation.*` | PASS |
| 未来版本 / 不一致 / 断档 | `TestCorruptionAndVersion.*` | PASS |
| 损坏字节不变 | `test_corrupt_bytes_rejected_and_file_unchanged` | PASS |
| migration 中途回滚 | `test_migration_failure_rolls_back_completely` | PASS |
| 无领域表 | `test_no_domain_tables_created` | PASS |
| Bootstrap Schema Contract（含 UNIQUE 语义 + partial） | `TestSchemaContractValidation.*` | PASS |
| 畸形表边界 | `TestMalformedTableBoundary.*` | PASS |
| CHECK(version > 0) 语义 | `TestVersionCheckConstraint.*` | PASS |
| AST 安全扫描 | `TestForbiddenApiScan.*` | PASS |
| 异常层级 | `TestExceptionHierarchy` | PASS |
| 原 61 项配置回归 | `test_config.py` / `test_models.py` | PASS（101 项总通过） |

## Additional Verification
- AST 扫描：`src/tgrid/` 全部 8 个 `.py` 无 `ast.Assert`、无 `xtquant` import、无 `order_stock`/`cancel_order`。
- 独立语义探针：wrong-UNIQUE / composite-UNIQUE / always-true-CHECK / partial-UNIQUE 全部 REJECTED；合法 schema ACCEPTED。
