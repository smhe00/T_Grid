# GATE 5 NODEA Fix Report（Iteration 3, NODEA-001..006）

## Status

`SELF_CERTIFIED` — 修复完成，状态 `AUDIT_READY`，等待独立审计 NODE A 复审（Iteration 3）。

审计基线：`910a727d3ef66c262abfd9dea45b092106f6d4a6`
（`work/gates/GATE_5/NODE_A_REVIEW_20260815.md`）。

## NODEA-001 (P0) — ADJUSTED 指标域 → RAW 交易域显式转换 ✅

- 新增 `src/tgrid/strategy/basis_transform.py`：`resolve_same_day_factor` /
  `to_raw_domain` / `to_raw_domain_factor` —— 显式、可审计的 ADJUSTED→RAW 同日因子
  （RAW = ADJUSTED × factor）；factor 缺失/非正/非有限 → fail closed；RAW 采集不得
  假装需要 ADJUSTED factor。
- `AccumulateStrategy.begin_day` 新增 `adjusted_to_raw_factor` + `daily_price_basis`
  参数：ADJUSTED 指标历史经显式因子把 anchor/previous_close 转到 RAW 交易域，之后所有
  价格比较（买层、波动暂停、gap 暂停）均为 RAW vs RAW；`DailyBasis` 记录 factor 元数据。
  无量纲值（ATR%、grid%）绝不转换。
- `BasisBinding` 元数据一致性校验：`dividend_type=front` 必须 `price_basis=ADJUSTED`，
  `none` 必须 `RAW`；不一致构造即拒绝。
- 测试：`test_node_a_fixes.py::TestNodeA001BasisTransform` — factor 校验、2:1 拆股
  变换（ADJUSTED 200 × 0.5 → RAW 100）、BasisBinding 不一致拒绝、fetch_bars 元数据一致。

## NODEA-002 (P1) — settlement 可卖量跨日持续结转 ✅

- `SettlementTracker` 重写为**持续余额模型**：`_released_balance` 一旦释放（T1 次日 /
  T0 当日）便保持，跨所有后续交易日直到被建模卖出消耗；不再绑定单日 key。
- 测试：`TestNodeA002SettlementCarryForward` — Day1 BUY → Day2 释放不卖 → Day3 仍可卖；
  多日多次买入；部分卖出后余量跨日；T0 未卖结转。

## NODEA-003 (P1) — 显式结算规则 + symbol fail-closed ✅

- `gate5_shadow_live.py`：
  - `_load_symbol_and_global`：symbol 不在配置中 → `SystemExit`（不再合成宽松
    SymbolConfig）。
  - `_settlement_rule_for`：仅 `.HK` → T0、`.SH/.SZ` → T1；未知市场后缀 → `SystemExit`；
    另支持显式 `--settlement` 参数。
- 测试：`TestNodeA003FailClosed` — 未知规则/未知市场 fail closed。

## NODEA-004 (P1) — reconciliation 不推断 Strategic/OpenT ✅

- `generate_remediation_evidence.py`：`strategic_extra` 改为**独立显式参数**，不再
  `max(0, held - core_qty)` 推断；nonzero 场景用"core 600（配置）+ strategic 100
  （已知本地状态）= broker 700"的独立分解。
- `ShadowEngine.reconcile` 要求显式 strategic/open_t；缺失组件时 expected 仅含 core，
  broker 残差 → 不匹配（SAFE_MODE 输入），绝不静默归类（INV-006）。
- 测试：`TestNodeA004NoResidualInference` — 独立分解 reconciled；缺 strategic 时不
  推断、显式不匹配。

## NODEA-005 (P1) — 从 HEAD 删除跟踪的 `_tmp/**` ✅

- 正常 forward commit `git rm -r _tmp`（266 个文件），未重写历史 / 未 force push。
- `.gitignore` 已含 `_tmp/`，后续不会重新跟踪。

## NODEA-006 (P1) — 控制面/证据元数据一致 ✅

- 测试数统一为 **832 tests OK**（818 + 12 NODEA + 2 timestamp）。
- 本次提交记录实际 SHA（非 PENDING_PUSH）。
- 证据状态用语：`REAL_QMT_REPLAY_VERIFIED`（历史回放）；连续 wall-clock live-soak
  保留为独立类别 `LIVE_SOAK_VERIFIED`，本次未执行。

## 验证

- 全量回归：`python -m unittest discover -s tests -p "test_*.py"` → **832 tests OK**。
- `python -m compileall -q src tests` → exit 0。
- AST 能力扫描：`assert` / `order_stock` / `cancel_order_stock` / `xtquant` import
  → 0 命中。
- `git diff --check` clean。
- `live_trading_allowed=false`；无真实 order/cancel 能力；Gate 5.5/6/7 BLOCKED。

## 未决 / 移交

- 真实连续实时 live-soak（wall-clock ≥5 日）未执行；作为 `LIVE_SOAK_VERIFIED`
  独立类别保留。
- 非零持仓 REAL_QMT 实机证据（含真实持仓）不提交（AUD-R1-005）；脱敏离线合成版在
  `work/reports/shadow/remediation-evidence/nonzero-core-position/`。
