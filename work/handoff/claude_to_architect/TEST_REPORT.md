# Test Report — G0-T004 / Iteration 4

## Environment
- Python 3.12.10
- PyYAML 6.0.3
- 平台：Windows 10

## Commands Run

```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
python -m tgrid --help
python -m tgrid --version
```

## Results

```text
Ran 178 tests in 1.608s
OK
```

`compileall` 退出码 0；`python -m tgrid --version` / `--help` 退出 0。

完整逐条输出已存档于 `work/reports/tests/G0-T004-test-output.txt`（含 CLI smoke 与 AST 扫描）。

## Fix Verification（Iteration 4）

| Issue | 验证点 | 结果 |
|---|---|---|
| REV-G0T004-006 | DB close SystemExit(9) 传播 + logger shutdown 调用一次 + registry 空 | PASS |
| REV-G0T004-006 | shutdown_complete GeneratorExit 传播 + logger shutdown 调用一次 + registry 空 | PASS |

## Coverage by Requirement（累计）

| 要求 | 测试 | 结果 |
|---|---|---|
| parser/help/version/缺子命令/缺参 | `TestArgparse.*` | PASS |
| 成功路径 + 三事件 + user_version=1 | `test_success_returns_zero_and_writes_three_events` | PASS |
| 重复 preflight 幂等 | `test_repeat_preflight_idempotent` | PASS |
| live_trading=true 拒绝 / 路径冲突 / alias | `TestPreflightRejections.*` | PASS |
| 注入 initialize/emit/DB close/shutdown 失败 | `TestFailureInjection.*` | PASS |
| startup+shutdown 同时失败 | `test_startup_and_shutdown_both_fail` | PASS |
| KeyboardInterrupt 130 + 清理 | `test_keyboard_interrupt_returns_130` | PASS |
| stdout/stderr 契约、无敏感泄漏 | `TestOutputContract.*` | PASS |
| 子进程 smoke | `TestSubprocessSmoke.*` | PASS |
| Iteration 2/3/4 修复 | `TestIteration2Fixes` / `TestIteration3Fixes` / `TestIteration4Fixes` | PASS |
| AST 扫描 | `TestForbiddenApiScan.*` | PASS |
| 原 142 项回归 | `test_config`/`test_models`/`test_persistence`/`test_logging` | PASS（178 项总通过） |

## Failure Injection（累计）

Iteration 1 的 8 项 + Iteration 2 的 6 项 + Iteration 3 的 3 项 + Iteration 4：DB close SystemExit、shutdown_complete GeneratorExit。

全部 fail closed，无 QMT、无订单、无伪成功、无敏感泄漏、资源清理完整（含所有 BaseException 路径）。

## Additional Verification
- AST 扫描：`src/tgrid/` 全部 12 个 `.py` 无 `ast.Assert`、无 `xtquant` import、无 `order_stock`/`cancel_order`。
- CLI smoke：`--version` 输出 `tgrid 0.1.0`、`--help` 显示 `preflight`。
