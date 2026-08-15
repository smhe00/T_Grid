# GATE 5 NODEA-R4 Fix Report（Iteration 5, NODEA-R4-001..004）

## Status

`SELF_CERTIFIED` — 修复完成，状态 `AUDIT_READY`，等待独立审计 NODE A 复审（Iteration 5）。

审计基线：`e6091ee77e1a9e534c02318eec6dd91a974b894e`
（`work/gates/GATE_5/NODE_A_REVIEW_ITER4_20260815.md`）。

## NODEA-R4-001 (P0) — 无 look-ahead 的严格前日 basis ✅

- runner `_strict_prior_daily_bars(daily, day)`：日 D 的指标历史只用 `bar_date < D`
  的日线；日 D 的 15:00 日线是未来信息，绝不进入当日 basis；无前日 bar → fail closed。
- `AccumulateStrategy.begin_day` 防御性过滤：内部也仅保留 `bar.time[:10] < trade_date`
  的 bar，否则 fail closed（调用方误传也安全）。
- 策略级 FI（`test_node_a_iter5.py`）：把日 D 的日线 OHLC/volume 改为极端值
  （999999），日 D 的 anchor/previous_close 与日内决策（BUY）完全不变；边界测试证明
  最后一日（08-11）包含、当日（08-12）排除。
- 已接受：逐日因子注册表无 1.0 默认、缺日 fail-closed。

## NODEA-R4-002 (P0) — 单一 Core 权威 ✅

- `SymbolConfig.core_qty` 是唯一 Core 来源；`ShadowEngine` 用 `symbol_cfg.core_qty`
  构造，不再从 reconciliation-state 读 Core。
- `_load_reconciliation_state` 只要求 `strategic_extra` / `open_t_position`；
  `_check_core_authority`：若 state 仍带 `core_qty`，必须与配置精确相等（否则
  SystemExit fail-closed），相等后丢弃，绝不作第二 Core。
- FI 测试：state core=700 vs 配置 600 → fail closed；state 无 core → 接受。

## NODEA-R4-003 (P1) — 运行手册/证据刷新 ✅（部分）

- `GATE5_RUNBOOK.md` 重写为当前 CLI（`--strategy-config` / `--factor-map` /
  `--reconciliation-state` / `--settlement`），全部占位符、无机器绝对路径；
  HK 市场限制说明。
- `LIVE_VERIFICATION.md` 标记 `SUPERSEDED`：旧 `LIVE VERIFIED` + +13.3 为
  NODEA-R4-001 修复前历史，不作为当前 Gate-5 验收证据。
- 当前代码 REAL_QMT 回放证据需用新 CLI 重新生成（证据需绑定 implementation SHA、
  symbol class、回放日期数、因子注册表 provenance/hash、对账状态 provenance/hash、
  basis、settlement、信号/订单计数、对账结果）。若真实非零持仓符号不可用，该接受项
  显式标 BLOCKED，不把合成证据称为 REAL_QMT。

## NODEA-R4-004 (P1) — canonical SHA 修正 ✅

- WORKFLOW_STATE 使用完整精确 GitHub SHA：`implementation_commit` 与
  metadata/handoff 提交区分；推送后回填实际 SHA。
- 状态统一 `AUDIT_READY`、测试数 846、`REAL_QMT_REPLAY_VERIFIED` 用语；
  Gate 5.5/6/7 BLOCKED、`live_trading_allowed=false`。

## 验证

- 全量回归：`python -m unittest discover -s tests -p "test_*.py"` → **846 tests OK**。
- `python -m compileall -q src tests` → exit 0。
- AST 能力扫描（`assert` / `order_stock` / `cancel_order_stock` / `xtquant` import）→ 0 命中。
- `_tmp/` 保持从 HEAD 移除；无本地路径/账户值进入提交证据。
- 无真实 order/cancel 能力；`live_trading_allowed=false`。

## 未决 / 移交

- 当前代码 REAL_QMT 历史回放证据（含非零持仓符号）需在真实环境重跑生成；
  若不可用则该项显式 BLOCKED。
- `LIVE_SOAK_VERIFIED`（连续 wall-clock live-soak）为未来独立里程碑。
