# Test Report — G0-T006 Gate 0 集成认证

## Environment
- Python 3.12.10
- PyYAML 6.0.3
- 平台：Windows 10
- 基线：`3e3c4529b00cc78b8db1381004fec6b069db6563`

## Commands Run（完整输出见 `work/reports/tests/G0-T006-gate0-certification.txt`）

| 检查 | 结果 |
|---|---|
| `git rev-parse HEAD` | `3e3c452...` 与基线一致 |
| `python -m unittest discover -s tests -p "test_*.py" -v` | 223 项 OK |
| `python -m compileall -q src tests` | 退出 0 |
| AST 禁止 API / assert 扫描（13 文件） | 干净 |
| 隔离 valid preflight | 退出 0；事件序正确；SQLite user_version=1、migration=1 |
| 隔离 live_trading=true | 退出 1；DB/log 未创建 |
| Event Queue 480 事件 smoke | 恰好一次、单 worker、STOPPED、无线程泄漏 |
| Event Queue handler failure smoke | FAILED、pending 丢弃、EventQueueWorkerError |

## Certification Evidence
- 全部检查 `PASS`，无 traceback、无 `Exception in thread`、无 secret、无残留线程。
- `work/reports/tests/G0-T006-gate0-certification.txt`（Iteration 2 重新生成）为**逐条完整输出**：223 个 `test_...` 用例行全部 verbatim 保存（含 5 个通过用例的 stderr 交错内容），`Ran 223 tests ... OK` 摘要；无截断、无 `... ok` 占位。
- artifact 共 285 行，27 个 `[PASS]` 检查行，末尾 `ALL CHECKS PASSED`。
- 仅更新证据文件与报告；未修改任何生产代码、测试或 `docs/GATE_0_REPORT.md`。
