# Test Report — G2-T006

## Task
G2-T006 — Offline Position Reconciliation Decision Engine。

## Environment
- 默认 Python 3.12.10；全部测试纯离线（无 QMT/SQLite/filesystem/network）。

## Commands Run（完整输出见 `work/reports/tests/G2-T006-test-output.txt`）

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p "test_*.py" -v` | **638 项全部 OK**（618 基线 + 20 新增） |
| `python -m compileall -q src tests` | 退出 0 |
| PACKAGE_SCAN（26 文件） | PASS：assert=0 / xtquant=0 / order-cancel=0 |
| NEW_MODULE_SCAN（reconciliation.py） | asserts=0；sqlite3/open/socket/network token=none |
| `git diff --check`（本任务文件） | exit 0 |

## 独立 Failure Injection 重放（artifact 内全文）

| 输入 | 结果 |
|---|---|
| 决策矩阵（zero/core+strategic/mixed） | RECONCILED/MATCH，delta=0 |
| +100（t_unit-like）/ -100 / 大 delta | SAFE_MODE/BROKER_POSITION_MISMATCH（不推断） |
| broker<core 与 mismatch 并存 | SAFE_MODE/CORE_FLOOR_BREACH（优先级） |
| EvilInt（`__int__/__eq__` secret） | PositionInvariantError，cause/context None、无 secret |
| FakeConfig | PositionInvariantError |
| 结果变异 | FrozenInstanceError（frozen） |
| mismatch 后组件 | core/strat/opent/local 保留原值（不重分类） |

## 新增测试覆盖（`tests/unit/test_position_reconciliation.py`，20 项）

### happy path
- zero-only、core+strategic、core+T、mixed 精确相等 → RECONCILED/MATCH，expected/delta 正确；frozen result。

### mismatch / 优先级
- 正/负 delta、t_unit-like +100 不重分类、大 delta → SAFE_MODE/BROKER_POSITION_MISMATCH。
- broker<core 优先级 → CORE_FLOOR_BREACH；core=0/broker=0 合法匹配。

### 校验 / dunder 隔离
- 负数量、bool/float/str/bytes/list/dict/int-subclass、fake/subclass SymbolConfig、None → PositionInvariantError。
- 空/空白/非 str/str-subclass symbol → PositionInvariantError。
- EvilInt/EvilStr secret 注入不执行 dunder，异常图干净。

### 不变量 / AST
- 输入组件不变、结果 data-only、无 mutation/repair callback。
- 新模块 AST：无 assert、无 sqlite3/xtquant/order/cancel/download/subscribe/socket/filesystem/network。

## 结果汇总
| 检查项 | 结果 |
|---|---|
| 638 项 unittest | OK |
| compileall | exit 0 |
| PACKAGE / NEW_MODULE AST 扫描 | PASS / PASS |
| 独立 FI 重放 | 全部符合边界 |
| 无 QMT/SQLite/账号访问 | 通过（纯离线） |

## 结论
全部检查通过。REVIEW_READY。
