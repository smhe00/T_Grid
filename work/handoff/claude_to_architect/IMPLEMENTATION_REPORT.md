# Implementation Report — G1-T003 / Iteration 2

## Task
G1-T003 — 离线依赖注入的 MarketData 查询只读 Adapter 边界（Iteration 2 修复 REV-G1T003-001）

## Summary
只修复架构师指出的 sequence 参数多观察问题：每个 sequence 只物化一次为私有 snapshot，成员验证与
底层调用共用同一 snapshot；snapshot 期间的普通异常转安全 `MarketDataValidationError`（异常图干净）。
保持八个固定只读方法和现有 API 不变，不新增订阅/下载/连接/账号/交易能力。

## Files Changed（Iteration 2 增量）
- `src/tgrid/adapters/marketdata_readonly.py`：
  - 删除 `_require_symbol_sequence`（先 `len(value)` 再迭代，然后 public method 又 `list(value)`）。
  - 新增 `_snapshot_symbol_sequence(value, name, *, allow_empty) -> list`：
    - 拒绝 str/bytes 与非 Sequence；
    - 用**列表推导** `[item for item in value]` 单次物化（不走 C 级 length hint，`__len__` bomb 免疫）；
    - 物化/迭代期间的普通 `Exception` 记录为 iter_error，`_reject` 在 **except 块外**抛
      `MarketDataValidationError`（`__cause__`/`__context__` 均为 None）；BaseException 原样传播；
    - 对 snapshot 做非空（allow_empty 时允许）与成员非空字符串校验；
    - 返回该 snapshot。
  - `get_full_tick` / `get_market_data` / `get_market_data_ex` 改为用 `_snapshot_symbol_sequence`
    返回的 snapshot 直接传给底层，不再二次 `list()` 或重复读取原对象。
- `tests/unit/test_marketdata_readonly.py`：新增 5 项（38 项总计）——`TestSingleSnapshotSequence`。

## Deviations
NONE

## Tests Added（Iteration 2）
`TestSingleSnapshotSequence`（REV-G1T003-001）：
1. `test_len_bomb_is_unaffected`：`__len__` 抛 `RuntimeError(LEN_SECRET_7A)` 的 list 子类；adapter 正常
   返回、底层收到 `['600000.SH']`，secret 未泄漏。
2. `test_first_pass_iterator_bomb_becomes_safe_validation_error`：iterator 首个 `next()` 抛
   `RuntimeError(FIRST_PASS_SECRET_9B)` → `MarketDataValidationError`，异常图干净，底层调用 0。
3. `test_changing_sequence_uses_first_snapshot_only`：第一次迭代返回 `['600000.SH']`、第二次返回 `['']`
   的有状态 Sequence → 只观察一次，底层收到已验证的 `['600000.SH']`，不含 `['']`。
4. `test_secret_iterator_exception_not_leaked`：iterator 抛 `RuntimeError(ITERATOR_SECRET_XYZ)` →
   安全 validation error，cause/context None，stdout/stderr 无 secret。
5. `test_market_data_snapshot_shared_for_validation_and_call`：get_market_data 的 stock_list 同样只
   观察一次，底层收到已验证 snapshot。

原有 33 项保持通过；全量 325 项通过。

## Test Commands / Results
```text
python -m unittest discover -s tests -p "test_*.py" -v   -> Ran 325 tests ... OK（含 5 项新增）
python -m compileall -q src tests                         -> exit 0
AST scan src/tgrid（16 文件）                             -> PASS
Single-snapshot probe                                     -> len_bomb 不受影响；first-pass/secret cause=None context=None 且底层 0；changing 仅 1 pass
git diff --check -- :/T_Grid                              -> exit 0
```
完整输出：`work/reports/tests/G1-T003-test-output.txt`（357 行）。

## Failure Injection（Iteration 2）
- len bomb（`__len__` 抛唯一 secret）：证明单次物化不触发 `__len__`。
- first-pass iterator bomb（首个 next 抛 secret）：转干净 validation error。
- changing sequence（两次迭代内容不同）：只观察一次，底层只收已验证值。
- unique-secret iterator exception：cause/context None，stdout/stderr 无 secret。

## Invariant Check
1. Gate 1 严格只读，离线 transport boundary：通过。
2. 八个底层调用固定、显式、可审计，无动态逃逸口：通过。
3. `live_trading_allowed=false`：通过。
4. 外部普通异常完整异常图不携带敏感信息；BaseException 不被吞掉：通过。
5. 无实际 XtQuant import/实例化/连接/查询，无第三方依赖：通过。

## Static / Type / Lint Check
- AST 扫描 16 文件：无 `ast.Assert`、无 `xtquant` import、无 order/cancel/subscribe/download 调用、
  无动态 getattr/call 绕过。
- `git diff --check -- :/T_Grid`：exit 0。

## Git Diff Summary
- HEAD == 基线 `a2f5fa3cb826e14a89bc478492f900d93d25b9fa`。
- 变更仅限本任务 Allowed Files；父目录文件未改动；未 commit/push。

## Known Issues
NONE

## Questions
NONE

## Recommendation
REVIEW_READY（iteration=2）
