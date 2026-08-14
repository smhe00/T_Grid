# Implementation Report — G1-T002 / Iteration 2

## Task
G1-T002 — 离线依赖注入的 QMT Trader 只读 Adapter 边界（Iteration 2 修复 REV-G1T002-001 / -002）

## Summary
只修复架构师指出的两个问题：异常链 `__context__` 仍携带原异常（P0），constructor descriptor 泄漏
裸异常且 bound methods 未冻结（P1）。保持固定只读 API、状态机和既有行为不变，不新增 QMT/行情/账号
能力。

## Files Changed（Iteration 2 增量）
- `src/tgrid/adapters/qmt_readonly.py`：
  - 新增 `_run_client_op(method, *args)`：调用冻结 callable 并返回 `(result, None)` 或
    `(None, 类型名)`（BaseException 先标记 FAILED 再原样传播）；所有项目异常的 `raise ... from None`
    都发生在 except 块之外，保证 `__cause__`/`__context__` 为 None。
  - constructor 改为 `_resolve_client_methods`：8 个固定字面量属性读取（无 getattr），每个读取独立
    守卫；抛异常 descriptor / 缺失属性 → `QmtAdapterConfigError`（异常图干净）；校验后冻结 8 个
    bound callable 到 `self._methods`。
  - 移除 `self._client`；connect/subscribe/stop/query/start 全部改用 `self._methods[...]` 冻结 callable。
- `tests/unit/test_qmt_readonly.py`：新增 7 项（64 项总计）——
  1. `_assert_safe_exception_graph`：递归断言 `__cause__ is None`、`__context__ is None`、全图无 secret。
  2. subscribe / stop 的 unique secret 不泄漏（此前只覆盖 start/connect/query）。
  3. constructor descriptor secret：`_SecretDescriptor` 抛 `RuntimeError(secret)` → `QmtAdapterConfigError`
     异常图干净、含类型名与方法名。
  4. constructor 缺失属性名称被报告且 cause/context 干净。
  5. 构造后替换 client 目标属性为危险 callable → 仍用冻结原方法（`test_frozen_methods_after_construction`）。
  6. 替换为指向 `order_stock` 的转发 → 危险计数 0。
  7. 替换 `stop` 后仍用冻结原方法。

## Deviations
NONE

## Tests Added
见 Files Changed；原有 57 项保持通过，新增 7 项 → 全量 287 项通过。

## Test Commands / Results
```text
python -m unittest discover -s tests -p "test_*.py" -v   -> Ran 287 tests ... OK
python -m compileall -q src tests                         -> exit 0
AST scan src/tgrid（15 文件）                             -> PASS（无 assert/xtquant/order-cancel/动态 getattr）
Exception graph probe                                     -> 全部 cause=None context=None
git diff --check -- :/T_Grid                              -> exit 0
```
完整输出：`work/reports/tests/G1-T002-test-output.txt`（322 行）。

## Failure Injection（Iteration 2）
- start/connect/subscribe/query/stop 注入 `RuntimeError(UNIQUE_SECRET)`：断言项目异常
  `__cause__ is None`、`__context__ is None`、文本/输出无 secret、failure_type 正确。
- constructor 注入抛 `RuntimeError(CONSTRUCTOR_DESCRIPTOR_SECRET_XYZ)` 的 descriptor：断言
  `QmtAdapterConfigError` 异常图干净。
- 构造后替换 client 属性为危险 descriptor / order 转发：断言冻结方法不被绕过、危险计数 0。

## Invariant Check
1. Gate 1 严格只读，无报单/撤单路径：通过。
2. QMT 调用只经过固定方法，无动态逃逸口：通过（字面量属性读取 + 冻结 callable）。
3. `live_trading_allowed=false`：通过。
4. 外部失败 fail closed，状态/异常类型可审计，敏感 message/对象不泄漏：通过（cause/context 递归断言）。
5. start/stop 幂等，失败后可清理，不依赖 assert：通过。
6. 无 XtQuant import/实例化/连接/账号/行情访问：通过。

## Static / Type / Lint Check
- AST 扫描 15 文件：无 `ast.Assert`、无 `xtquant` import、无 order/cancel call、无动态 getattr/call 绕过。
- `git diff --check -- :/T_Grid`：exit 0。

## Git Diff Summary
- HEAD == 基线 `73cbe3be6abf3744fd16b322c45fb4a17ee6bb40`。
- 变更仅限本任务 Allowed Files；父目录文件未改动；未 commit/push。

## Known Issues
NONE

## Questions
NONE

## Recommendation
REVIEW_READY（iteration=2）
