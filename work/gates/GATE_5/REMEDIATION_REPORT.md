# GATE 5 Remediation Report（AUD-R1-001..007）

## Status

`SELF_CERTIFIED` — 修复完成，状态 `AUDIT_READY`，等待独立审计 NODE A。

审计基线：`2f4957b215beec9f6b6e40054cc6a0375198c29d`
（`work/gates/GATE_5/INDEPENDENT_AUDIT_20260815.md`）。

## AUD-R1-001 — 显式 RAW/ADJUSTED 复权绑定 ✅

- 新增 `src/tgrid/shadow/marketdata.py`：`fetch_bars(..., dividend_type=...)` 将显式
  复权模式传给底层 `get_market_data_ex`（不再依赖终端默认状态）；返回
  `(bars, BasisBinding)`，每根 bar 携带解析后的 `price_basis`。
- `resolve_basis`：`none -> RAW`、`front -> ADJUSTED`；未知/不支持模式 fail closed，
  零底层调用。
- `BasisBinding`：period/dividend_type/price_basis 可审计元数据，非法组合拒绝。
- 测试：`test_gate5_remediation.py::TestAudR1001BasisBinding` — 断言底层调用收到精确
  `dividend_type`、bar basis 正确、未知模式不调用底层、RAW/ADJUSTED 不混用。

## AUD-R1-002 — 结算感知可卖数量（T+1） ✅

- 新增 `src/tgrid/shadow/settlement.py`：`SettlementPolicy`（T0/T1 显式规则，未知规则
  fail closed）+ `SettlementTracker`（同日买入锁定 → 次交易日 `advance_trading_day`
  释放）+ `compute_sellable`（real can_use + released shadow，exact-type）。
- `ShadowEngine` 接入：`effective_can_use = real_can_use + released_shadow`；T1 下同日
  影子买入不增加当日可卖量；`record_sell` 只消费 shadow 释放部分，其余由 real 提供。
- 结算规则按 symbol 显式：A 股/ETF -> T1，港股 -> T0（`_settlement_rule_for`）。
- 测试：`TestAudR1002Settlement`（锁定/释放/消费）+ `TestSettlementT1SameDay`
  （同场反弹 `SELL_REJECTED/INSUFFICIENT_AVAILABLE_VOLUME`；次交易日可 `SELL_T`）。

## AUD-R1-003 — 真实对账与影子假设分离 ✅

- `ReconciliationRow` 重定义：`broker_position` vs `local_expected_position`
  （Core+Strategic+OpenT）——唯一可称为 broker reconciliation 的行。
- 新增 `ShadowDeltaRow`：`shadow_delta` + `effective_position`（real + delta），
  明确标注为假设（hypothetical），绝不混入真实对账。
- `ShadowEngine.reconcile` 只做真实对账；`shadow_delta()` 单独报告假设活动；
  `build_shadow_reports` 输出 `reconciliation` + `shadow_delta` 两组。
- 测试：`TestReconciliation`（真实匹配/不匹配/含 open_t；影子 delta 独立不影响真实
  对账）+ `TestAudR1003` 场景（零基线与非零真实持仓）。

## AUD-R1-004 — 证据分类 ✅

- 运行器输出 `EVIDENCE_CLASS = "REAL_QMT_HISTORICAL_REPLAY + REAL_BROKER_SNAPSHOT"`；
  报告 `evidence.json` 含 class/basis/settlement/run_days。
- `LIVE_VERIFICATION.md` 明确：历史回放 ≠ 连续自然日 live-soak；实时连续运行作为
  独立证据类别另行记录。

## AUD-R1-005 — 仓库卫生 / 运行时数据 ✅

- 删除工作区 `_tmp/`；`.gitignore` 增加 `_tmp/`、`tmp/`、`*.tmp`、全局 `*.local.json`/
  `*.local.yaml`/`*_local.json`/`*_local.yaml`（AUD-R1-005：本地运行时文件无论生成于
  何处均排除）。
- `LIVE_VERIFICATION.md` 脱敏：移除 QMT 路径、端点/端口、账户资金、持仓明细。
- 未重写历史 / 未 force push（按审计要求）。

## AUD-R1-006 — 控制面一致性 ✅

- 本报告与 `docs/GATES.md` 将 DSH Gate 2-5 标注 `SELF_CERTIFIED` / `PROVISIONAL`。
- Gate 5 修复后状态 `AUDIT_READY`；Gate 6/7 保持 `BLOCKED`，`live_trading_allowed=false`。
- 独立审计记录单独保留（`INDEPENDENT_AUDIT_20260815.md` 未改动）。

## AUD-R1-007 — ExecutionEngine exact-type hardening ✅（本次关闭）

- `executor.py::_send` 在算术前对 `expected_available_cash` / `cash_amount`
  （BUY：非负 number）与 `expected_available_qty`（SELL：plain non-negative int）
  做 exact-type 校验；删除 `int(...)`/`float(...)` 对 untrusted 输入的强制转换。
- 测试：`TestAudR1007ExecutorCoercion` — 拒绝 EvilNumber/字符串/小数容量，且不调用
  其 dunder；plain 合法值仍正常。

## 证据

- 回归：`python -m unittest discover -s tests -p "test_*.py"` → **818 tests OK**。
- `python -m compileall -q src tests` → exit 0。
- AST 扫描（`assert` / `order_stock` / `cancel_order_stock` / `xtquant` import）→ 0 命中。
- 实机 shadow 证据（修复后刷新）：`work/reports/shadow/*/{shadow_orders,signal_log,
  reconciliation,shadow_delta,daily_report,evidence}.json`，含零真实持仓与非零真实
  持仓场景、结算策略与复权口径证据。

## 未决 / 移交

- 真实连续实时 live-soak（wall-clock ≥5 日）未执行；作为独立证据类别保留给用户/后续。
- Gate 5.5（真实 Broker Adapter）未实现；按审计要求等待 Audit Node A PASS。
