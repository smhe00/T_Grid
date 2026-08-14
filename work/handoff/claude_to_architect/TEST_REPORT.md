# Test Report — G0-T001 / Iteration 3

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
Ran 61 tests in 0.084s
OK
```

`compileall` 退出码 0。

完整逐条输出已存档于 `work/reports/tests/G0-T001-test-output.txt`。

## Fix Verification（Iteration 3）

| Issue | 验证点 | 结果 |
|---|---|---|
| REV-G0-006 | `? [a, b] : value` 拒绝为 `ConfigError`（含 line 与 key 信息），不泄漏 `TypeError` | PASS |
| REV-G0-007 | root 层重复 `global` 拒绝，错误含 `duplicate`/`global`/`line` | PASS |

## Full Coverage by Requirement（累计）

| 要求 | 测试 | 结果 |
|---|---|---|
| 示例配置成功加载 | `test_load_example_config_success` | PASS |
| 缺省 `live_trading=false` | `test_default_live_trading_false` | PASS |
| `lot_size`/`price_tick` 未写死 | `test_lot_size_and_price_tick_not_hardcoded` | PASS |
| 非 `ACCUMULATE` 拒绝 | `test_neutral_rejected` 等 | PASS |
| `t_unit` 非 `lot_size` 倍数拒绝 | `test_t_unit_not_multiple_of_lot_size_rejected` | PASS |
| 零/负 `price_tick` 拒绝 | `test_zero/negative_price_tick_rejected` | PASS |
| `target_qty < core_qty` 拒绝 | `test_target_less_than_core_rejected` | PASS |
| `max_t_lots < 1` 拒绝 | `test_max_t_lots_less_than_one_rejected` | PASS |
| bool 冒充整数拒绝 | `test_bool_as_int_rejected` | PASS |
| NaN/Infinity 拒绝 | `test_nan/infinity_price_tick_rejected` | PASS |
| 未知/缺失/错误根结构拒绝 | `test_unknown_*` / `test_missing_*` / `test_root_not_mapping_rejected` | PASS |
| 重复键拒绝（global/symbol 字段、symbol 名、root global） | `TestDuplicateKeys.*` | PASS |
| 不可哈希/非标量 key fail-closed | `test_unhashable_*` | PASS |
| 枚举字段 fail-closed | `TestEnumValidation.*` | PASS |
| symbols 只读映射 | `TestSymbolsReadOnly.*` | PASS |
| 异常可捕获、不用 assert | `TestRiskExceptions.*` + AST assert 扫描 | PASS |

## Failure Injection（累计）

1. 文件不存在、2. YAML 语法损坏、3. 根节点非 mapping、4. 未知键、5. `t_unit: true`、6. `price_tick: .nan`、7. 非法交易模式、8. 重复键（live_trading / core_qty / symbol / root global）、9. 非法 bar_period / anchor、10. 不可哈希 sequence key、11. symbols 映射各类修改尝试。

全部抛出明确、可审计的 `ConfigError`（或对只读映射的 `AttributeError`/`TypeError`/`FrozenInstanceError`），未回退宽松默认值，无裸 `TypeError` 泄漏。

## Additional Verification
- `import tgrid` 无副作用。
- AST 扫描：源码无 `ast.Assert`、无 `xtquant` import、无 `order_stock`/`cancel_order` 调用。
