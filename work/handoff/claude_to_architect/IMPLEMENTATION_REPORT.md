# Implementation Report — G2-T004

## Task
G2-T004 — Atomic T-Lot Status Transition Writer。Iteration 2 只修 REV-G2T004-001..003；不新增
writer API、schema、状态矩阵、CRUD、外部依赖或交易能力。

## Summary
Iteration 1 的 592 项回归通过但独立 FI 发现三个边界缺陷。Iteration 2 完成：
- 事务边界覆盖 `BaseException`：CAS/audit/COMMIT 任一步主失败先 rollback（或无法确认时失效连接），
  再决定传播/转换；KI/SE/GE 保持原对象/类型传播，普通异常/sqlite 错误转固定 data-free
  `TLotWriteFailedError`，异常图干净；rollback 自身异常不覆盖主异常。
- status 校验先 exact non-empty `str` 再做 membership，不再调用任意对象 `__eq__`。
- 两连接 CAS 竞争测试改为 Event 驱动的真实交错（conn1 持 BEGIN IMMEDIATE 未提交时 conn2 发起写入并
  争锁），确定性释放后最多一个成功。

## Review Issues — Iteration 2 逐项回复

### REV-G2T004-001 — BaseException 在 CAS 后跳过 rollback — **FIXED**
- `transition_t_lot_status` 重构：`try: BEGIN IMMEDIATE → CAS → audit INSERT → COMMIT` 包在一个事务
  边界内，`except TLotWriterError` / `except Exception`（含 sqlite3.Error）/ `except BaseException` 分别
  捕获，全部先 `_rollback_or_invalidate` 再传播/转换。
- `KeyboardInterrupt/SystemExit/GeneratorExit` 在 rollback 成功后保持原对象/类型传播，不转换为项目错误
  （独立重放 `propagated=True cause_none=True context_none=True in_txn=False status=OPEN audits=0`）。
- 普通未知 `Exception` 与 sqlite3.Error：rollback 后转固定、data-free `TLotWriteFailedError`，
  `__cause__`/`__context__` 均 None（重放 `secret_in_msg=False`）。
- `_rollback_or_invalidate`：ROLLBACK 成功则返回；ROLLBACK 自身抛普通异常/BaseException 时关闭连接
  使底层不可再 commit（重放 `conn_closed=True`），且不覆盖主异常。
- 测试矩阵：三类主 BaseException、普通 RuntimeError secret、主失败 × rollback failure（普通与
  BaseException 两变体），均检查 lot/audit/history/version 与连接可提交性。

### REV-G2T004-002 — status exact-type 校验发生得太晚 — **FIXED**
- `_require_status` 现在先调用 `_require_exact_nonempty_str`（`type(value) is str and value != ""`），
  再做 `value in T_LOT_STATUSES`；拒绝 str subclass、bool、bytes、容器及任意对象，不调用其
  `__eq__/str/repr/bool/iter`。
- 回归：恶意 `__eq__` 对象注入 → `TLotWriterInputError`，message/`__cause__`/`__context__` 无 secret，
  失败前后 DB 逐值不变（`test_malicious_status_dunder_not_called`）。

### REV-G2T004-003 — 两连接测试没有确定性交错 — **FIXED**
- `test_two_connections_deterministic_cas_race` 重写为 Event/线程驱动：conn2 先初始化就绪；conn1 持
  `BEGIN IMMEDIATE`（含未提交 CAS+audit）时由 `in_txn` Event 通知；conn2 等待 `in_txn` 后发起同一
  expected-status 写入（`BEGIN IMMEDIATE` 在 conn1 写锁上真实争锁）；`release` 确定性释放后 conn1
  commit、conn2 冲突。无 sleep。
- 结果：conn1 成功（1 条 audit），conn2 `TLotStatusConflictError`，最终 lot 唯一目标状态 SUSPENDED、
  audit 恰一条、两连接均无 active transaction、无 retry。

## Files Changed（Iteration 2 增量）
- `src/tgrid/persistence/t_lot_writer.py`：`_require_status` 先 exact-str 校验；`_safe_rollback` →
  `_rollback_or_invalidate`（ROLLBACK 失败关闭连接）；writer 主流程 `try/except BaseException` 事务边界。
- `tests/unit/test_t_lot_writer.py`：新增 5 项（三类 BaseException、RuntimeError secret、主失败×rollback
  失败普通/BaseException、恶意 status dunder）；两连接测试改为确定性交错。

（Iteration 1 已交付的 writer API / frozen result / 异常 / migrations 共享状态 / exports 保持不变。）

## Test Commands / Results
```text
python -m unittest discover -s tests -p "test_*.py" -v   -> Ran 597 tests ... OK（592 基线 + 5 新增）
python -m compileall -q src tests                         -> exit 0
AST scan src/tgrid（24 文件）                             -> PASS，forbidden=0
git diff --check（本任务文件）                            -> exit 0
独立 FI 重放（REV-G2T004-001..003）                       -> 全部符合边界
```
完整输出：`work/reports/tests/G2-T004-test-output.txt`。

## Failure Injection
- 三类 BaseException 注入 audit insert 点 → 传播原对象、rollback、lot/audit 逐值不变。
- RuntimeError secret → `TLotWriteFailedError`，message/`__cause__`/`__context__` 无 secret。
- COMMIT+ROLLBACK 双失败 → 连接失效（不可 commit），主异常（转换/BaseException）传播。
- 恶意 status `__eq__` → 不调用 dunder，`TLotWriterInputError`。
- 两连接确定性竞争 → 一个成功一个 conflict，一条 audit。

## Invariant Check
1. status update 与 audit insert all-or-nothing（含 BaseException 主失败）：通过。
2. CAS rowcount != 1 fail closed，不猜测/重试/upsert：通过。
3. expected 不匹配时原 lot/audit 逐值不变：通过。
4. audit 失败时 lot/updated_at 完整回滚：通过。
5. 不接受已有事务，不提交/回滚调用者事务：通过。
6. 不执行未知对象 str/repr/bool/iter：通过（status 先 exact-str）。
7. SQLite 异常转固定 data-free PersistenceError，异常图干净：通过。
8. 无 assert 承担安全、无自动 retry：通过。
9. `live_trading_allowed=false`，无 QMT/order/cancel/download/subscribe：通过。

## Known Issues
NONE

## Questions
NONE。

## Recommendation
REVIEW_READY
