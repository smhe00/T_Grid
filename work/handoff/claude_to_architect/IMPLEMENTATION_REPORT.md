# Implementation Report — G2-T005

## Task
G2-T005 — T-Lot Business Transition Policy Guard（闭集 action → 唯一状态边，复用 G2-T004 原子 writer）。
纯离线、fail-closed；不连接 QMT、不生成 OrderIntent、不实现真实人工授权。

## Summary
在 G2-T004 已验收的 `transition_t_lot_status` 之上新增业务状态转换策略层：
- 纯函数 resolver `resolve_t_lot_transition(action, expected_status)` → frozen `TLotTransitionPlan`；
- guarded apply `apply_t_lot_transition(...)`：先解析策略（拒绝时不触碰数据库），再恰好一次调用
  G2-T004 writer；
- 五条批准边闭集；`KEEP_SUSPENDED`/`CONVERT_TO_STRATEGIC`/`MANUAL_EXIT` 明确不可执行；
  `CLOSED`/`CONVERTED_TO_STRATEGIC`/`ERROR` 无自动出边；self-transition 全拒绝。

## Files Changed
- `src/tgrid/persistence/t_lot_transition_policy.py`（新增）：`T_LOT_ACTIONS` 闭集、
  `_T_LOT_TRANSITIONS` 固定边表（action → (to_status, event_type)）、`_MANUAL_OR_NOOP_ACTIONS`、
  `_TERMINAL_STATUSES`、`TLotTransitionPlan`（frozen）、异常
  `TLotTransitionPolicyError(TLotWriterError)` / `TLotTransitionRejectedError`、
  `resolve_t_lot_transition` / `apply_t_lot_transition`。
- `src/tgrid/persistence/__init__.py`：仅导出本任务批准的 resolver/apply/plan/exceptions。
- `tests/unit/test_t_lot_transition_policy.py`（新增，19 项）。
- `work/reports/tests/G2-T005-test-output.txt`（新增完整证据）。

未修改 `t_lot_writer.py` / `migrations.py` / `database.py` 及任何既有测试/实现（G2-T005 Forbidden）。

## Exact Transition Matrix
| action | expected_status | to_status | event_type |
|---|---|---|---|
| `BUY_FILL_CONFIRMED` | `PENDING_BUY` | `OPEN` | `BUY_FILL_CONFIRMED` |
| `PREPARE_SELL` | `OPEN` | `PENDING_SELL` | `PREPARE_SELL` |
| `SELL_FILL_CONFIRMED` | `PENDING_SELL` | `CLOSED` | `SELL_FILL_CONFIRMED` |
| `SUSPEND_T` | `OPEN` | `SUSPENDED` | `SUSPEND_T` |
| `RESUME_T` | `SUSPENDED` | `OPEN` | `RESUME_T` |

其余任意 (action, status) 组合全部拒绝（全 5×7 矩阵测试：35 组合中 5 批准、30 拒绝，含全部
self-transition 与 terminal-source）。

## Reuse Evidence
- `apply_t_lot_transition` 直接调用 G2-T004 `transition_t_lot_status`（import 复用，不复制 SQL/CAS/rollback）；
  writer 独占事务/回滚/异常语义，policy 不自行 `BEGIN/UPDATE/INSERT/COMMIT/ROLLBACK`。
- 七状态复用 `T_LOT_STATUSES`（migrations 单一来源），未新建第三份状态列表。
- 新异常继承 `TLotWriterError` → `PersistenceError` 层，未建新的无关异常根。

## Rejected Manual / No-op Actions
- `KEEP_SUSPENDED`：no-op review decision，拒绝，绝不以 `SUSPENDED -> SUSPENDED` 制造假审计。
- `CONVERT_TO_STRATEGIC`：需显式人工授权机制，本任务拒绝执行。
- `MANUAL_EXIT`：需真实人工成交/对账证据，本任务不得直接映射 `CLOSED`。

## Deviations
NONE

## Tests Added
`tests/unit/test_t_lot_transition_policy.py`，19 项：
1. 五条批准边 resolver 正确（frozen plan、event_type 固定映射）。
2. 全 action×status 矩阵（35 组合）负向覆盖。
3. self-transition 全拒绝（无批准边为自环，其余拒绝）。
4. unknown action 拒绝。
5. manual/no-op 三动作拒绝。
6. terminal source（CLOSED/CONVERTED_TO_STRATEGIC/ERROR）拒绝。
7. wrong source 拒绝。
8. 空/NULL/非 exact-str/str subclass/bool/bytes/container 输入拒绝，无 dunder。
9. 恶意 action `__eq__` / 恶意 status `__eq__` 不被调用，异常 message/`__cause__`/`__context__` 干净。
10. SQLite 集成：五条批准边逐条 apply → DB status 与 audit（event_type/from/to）完全一致。
11. 拒绝边零 DB 写入（lot/history 逐值不变、0 audit）。
12. manual/no-op apply → DB 不变。
13. stale source 走底层 CAS conflict，无 retry、值不变。
14. writer spy：拒绝前 0 call；成功恰 1 call 且参数为 plan 推导值。
15. writer conflict / BaseException 不吞、不重试、恰好一次。
16. 新模块 AST：无 raw SQL token（BEGIN/UPDATE/INSERT INTO/DELETE FROM/COMMIT/ROLLBACK）、无
    `assert`、无 xtquant、无 order/cancel。

## Failure Injection
- 恶意 action/status 对象注入 secret `__eq__` → 不调用 dunder，异常无 secret、异常图干净。
- 全矩阵负向、self-transition、terminal-outbound、action/source mismatch。
- manual/no-op 三动作不可执行且 DB 不变。
- writer spy：reject 0 call / accept 1 call；writer 抛 conflict/BaseException 不吞不重试。
- stale source 真实 conflict，无 upsert/猜测/retry。
- 独立重放（artifact 内全文）全部符合边界。

## Test Commands / Results
```text
python -m unittest discover -s tests -p "test_*.py" -v   -> Ran 616 tests ... OK（597 基线 + 19 新增）
python -m compileall -q src tests                         -> exit 0
AST scan src/tgrid（25 文件）                             -> PASS，forbidden=0
policy 模块 raw-SQL token 扫描                            -> none
git diff --check（本任务文件）                            -> exit 0
```
完整输出：`work/reports/tests/G2-T005-test-output.txt`。

## Invariant Check
1. apply 不接受任意 new_status/event_type：通过（仅闭集 action 推导）。
2. 未列出组合在 writer 前拒绝、DB 逐值不变：通过。
3. 一个成功 apply 恰好调用一次 G2-T004 writer：通过（spy）。
4. stale expected 由底层 CAS fail closed，无预读/猜测/retry：通过。
5. `KEEP_SUSPENDED` 不以 self-transition 造假审计：通过。
6. `CONVERT_TO_STRATEGIC`/`MANUAL_EXIT` 本任务绝不执行：通过。
7. terminal 状态无自动出边：通过。
8. 输入拒绝不调用未知对象 dunder，异常固定/data-free/无 secret 图：通过。
9. 未删除/弱化 G2-T004 writer 或 schema/verifier 测试：通过。
10. `live_trading_allowed=false`，无 QMT/order/cancel/download/subscribe：通过。

## Static / Type / Lint Check
- AST 扫描 25 文件：无 `ast.Assert`、无 xtquant、无 order/cancel。
- 新模块无 raw SQL token；`git diff --check` 本任务文件 exit 0。

## Git Diff Summary
- 变更：新增 t_lot_transition_policy.py + test_t_lot_transition_policy.py + 报告/证据/控制文件 +
  `persistence/__init__.py` 导出；`t_lot_writer.py`/`migrations.py`/`database.py` 未改。
- **未 commit/push**：本地 Git 仓库（miniQMT monorepo）与 GitHub `T_Grid` 无共同祖先，无法安全执行
  协议要求的 ff-only merge / 普通 push；由用户/架构师决定 GitHub 侧的推送方式。

## Known Issues
NONE

## Questions
NONE（见 QUESTIONS.md）。

## Recommendation
REVIEW_READY
