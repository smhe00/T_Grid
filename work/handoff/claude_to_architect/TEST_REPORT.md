# Test Report — G1-T001

## Task
G1-T001 — Gate 1 QMT 只读环境与 API 边界调查（离线，纯调查，无生产代码变更）

## 说明
本任务为环境/API 调查，不新增或修改单元测试；执行任务规定的检查项并以完整输出存档。

## 执行的检查

### 1. 解释器与 find_spec（未导入）
```text
python --version               -> Python 3.12.10
py --list                      -> 3.12.10（默认）、3.11.9
find_spec('xtquant')           -> 默认解释器 MISSING；.venv(3.12.10) FOUND；.venv-bigquant/3.11.9 MISSING
```

### 2. 静态 API 面（AST 离线反射，未 import xtquant、未实例化 trader）
```text
XtQuantTrader.connect/start/stop/run_forever           FOUND
XtQuantTrader.query_stock_asset/positions/orders/trades FOUND
XtQuantTraderCallback.on_connected/on_disconnected/on_account_status ... FOUND
xtdata.connect/get_full_tick/get_market_data(_ex)/subscribe_quote/unsubscribe_quote ... FOUND
xtdata.get_divid_factors/get_instrument_detail/get_trading_calendar/get_trading_dates/get_trading_period ... FOUND
FORBIDDEN: order_stock(_async)/cancel_order_stock(_async)/cancel_order_stock_sysid(_async) 静态存在，禁止调用
```

### 3. 安全范围检查
```text
git diff --check -- T_Grid     -> exit 0
AST scan src/tgrid (13 files)  -> PASS：无 ast.Assert、无 xtquant import、无 order/cancel 调用，exit 0
git HEAD                       -> 34169aa9873af9ae7f94994ed7301956d491585d == 基线
```

### 4. 补充：Gate 0 回归（AC8 声明无需重跑，本轮为完整性补跑）
```text
python -m unittest discover -s tests -p "test_*.py" -> Ran 223 tests ... OK，exit 0
python -m compileall -q src tests                    -> exit 0
```

## 完整输出
`work/reports/tests/G1-T001-environment-probe.txt`（112 行，含上述全部命令与结果）。

## 结果汇总
| 检查项 | 结果 |
|---|---|
| TGrid 默认解释器 XtQuant 可用性 | MISSING → 环境未就绪（按 AC5 如实声明） |
| `.venv`(3.12.10) XtQuant 可用性 | FOUND（静态） |
| 候选只读 API 静态存在 | 全部 FOUND（AVAILABLE_UNVERIFIED） |
| 禁止交易 API 未调用 | 通过 |
| 未连接/未导入/未实例化/未查询 | 通过 |
| git diff --check / AST 扫描 | 通过（exit 0） |
| 无敏感值入报告 | 通过 |

## 结论
全部检查通过，无 traceback、无敏感输出；环境缺失作为调查结论如实记录，不构成本任务 BLOCKED。
REVIEW_READY。
