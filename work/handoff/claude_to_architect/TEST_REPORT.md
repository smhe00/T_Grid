# Test Report — G1-T002 / Iteration 2

## Task
G1-T002 — 离线依赖注入的 QMT Trader 只读 Adapter 边界（Iteration 2 修复 REV-G1T002-001 / -002）

## Environment
- Python 3.12.10
- 基线：`73cbe3be6abf3744fd16b322c45fb4a17ee6bb40`
- 全部测试使用 fake client，无 XtQuant import、无 QMT 连接、无真实账号/行情访问。

## Commands Run（完整输出见 `work/reports/tests/G1-T002-test-output.txt`，322 行）

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p "test_*.py" -v` | **287 项全部 OK**（223 Gate 0 + 64 本模块） |
| `python -m compileall -q src tests` | 退出 0 |
| AST 扫描 `src/tgrid/**/*.py`（15 文件） | PASS：无 assert、无 xtquant import、无 order/cancel 调用、无动态 getattr/call 绕过 |
| 异常图 probe（start/connect/subscribe/query/stop + ctor-descriptor） | 全部 `cause=None context=None`，无 secret |
| `git diff --check -- :/T_Grid` | exit 0 |
| HEAD 与基线 | `73cbe3b...` == base，一致 |

## Iteration 2 新增/强化测试

### REV-G1T002-001 — 异常图安全（`__context__` 也为 None）
- `_assert_safe_exception_graph`：递归遍历 `__cause__`/`__context__`，断言二者为 None 且全图无 secret。
- 覆盖路径：start / connect / subscribe / query / stop 各注入 `RuntimeError(UNIQUE_SECRET)`；
  公共异常文本为 `"<op> failed: RuntimeError"`，`__cause__`/`__context__` 均为 None，stdout/stderr 无 token。

### REV-G1T002-002 — constructor 安全 + 方法冻结
- `_SecretDescriptor`（`__get__` 抛 `RuntimeError(CONSTRUCTOR_DESCRIPTOR_SECRET_XYZ)`）注入 `connect`：
  constructor 抛 `QmtAdapterConfigError`，异常图干净（cause/context None），消息含类型名 `_DescriptorSecretClient` 与方法名 `connect`，无 secret。
- constructor 缺失属性（`_MissingAttr`）：`QmtAdapterConfigError` 含方法名，cause/context None。
- 构造后替换 client 属性：
  - 替换 `query_stock_asset` 为危险 callable → 返回冻结原结果，危险计数 0。
  - 替换 `query_stock_positions` 为指向 `order_stock` 的转发 → 返回冻结原结果，危险计数 0。
  - 替换 `stop` 为危险 callable → 冻结原 stop 被调用一次，危险计数 0。

## Failure Injection 汇总（Iteration 2）
见上文；唯一 secret token 在 exception/cause/context/stdout/stderr 全路径断言不出现。

## 结果汇总
| 检查项 | 结果 |
|---|---|
| 287 项 unittest | OK |
| compileall | exit 0 |
| AST 安全扫描 | PASS（15 文件，无 assert/xtquant/order-cancel/动态转发） |
| 异常图安全 | PASS（全部 `__cause__ is None`、`__context__ is None`） |
| constructor descriptor 安全 | PASS（`QmtAdapterConfigError`，异常图干净） |
| 方法冻结（构造后替换不可绕过） | PASS（危险计数 0） |
| 无真实 QMT/账号/行情访问 | 通过（仅 fake client） |

## 结论
REV-G1T002-001 / -002 均已修复并有回归证据。REVIEW_READY（iteration=2）。
