# GATE 5 NODEA-R3 Fix Report（Iteration 4, NODEA-R3-001..004）

## Status

`SELF_CERTIFIED` — 修复完成，状态 `AUDIT_READY`，等待独立审计 NODE A 复审（Iteration 4）。

审计基线：`03d392341d0c558c5a2461637e6ac5cade6645ed`
（`work/gates/GATE_5/NODE_A_REVIEW_ITER3_20260815.md`）。

## NODEA-R3-001 (P0) — 逐日可信因子 + 策略级 2:1 不变量 ✅

- 新增 `src/tgrid/shadow/daily_factor.py`：`DailyFactorRegistry` —— 按
  `(symbol, trade_date)` 的显式可信因子表，**无 1.0 默认**、缺失日 fail closed；
  provenance（XTQUANT / TRUSTED_LOCAL_FACTOR_MAP）逐绑定记录；`sanitized_summary`
  只报来源/数量/日期/符号，不泄露因子数值（AUD-R1-005）。
- runner：删除 `--adjusted-to-raw-factor`（默认 1.0）标量；改为 `--factor-map`
  逐日 JSON；每个回放日必须存在因子，否则 fail closed；移除 pre-loop
  `shadow.begin_day(daily, ...)` 种子（避免向后的交易日过渡）；交易日严格单调。
- 策略级 2:1 拆股不变量测试（`test_node_a_iter4.py`）：同一经济场景分别以 RAW
  尺度（factor 1.0）和 ADJUSTED 双倍尺度（factor 0.5）表达，BUY / NO_ACTION /
  VOLATILITY_HALT 决策与原因完全一致——证明归一化后经济不变。
- `BasisBinding` 元数据一致性（前一轮已接受）保持。

## NODEA-R3-002 (P1) — 可信策略/结算/会话配置 ✅

- runner 新增必填 `--strategy-config`：加载**可信本地策略配置**（绝不使用
  `config.example.yaml` 作为运行时状态）；symbol 必须存在于该配置，否则 fail closed。
- settlement 必须显式：`--settlement` 或策略配置中的 `settlement_rule`；删除
  后缀推断默认。
- 市场限制：runner 仅支持 SH/SZ（`SUPPORTED_MARKETS`）；HK 会话策略未实现 →
  fail closed，而非套用错误会话。
- 测试：缺失策略配置 / 缺失 symbol / 未知结算规则 / 非 SH/SZ 市场均 fail closed。

## NODEA-R3-003 (P1) — 真实对账可信分解 ✅

- runner 新增必填 `--reconciliation-state`：从可信本地 JSON 加载
  Core/StrategicExtra/OpenT；任一组件缺失或非非负 int → fail closed，**绝不静默
  当作 0**（INV-006）。
- `ShadowEngine.reconcile`：expected = core + strategic + openT 均来自显式状态；
  未知组件时 expected 仅含已知项，broker 残差 → 显式不匹配（SAFE_MODE 输入）。
- 测试：`TestNodeAR3003ReconciliationState` — 缺 strategic 时 expected=core-only、
  不匹配，不推断。

## NODEA-R3-004 (P1) — 控制面/证据元数据一致 ✅

- 测试数统一为 **840 tests OK**（832 + 8 Iter4）。
- 本次提交记录实际 SHA（推送后回填，非 PENDING_PUSH）。
- 证据用语：`REAL_QMT_REPLAY_VERIFIED`（历史回放）；`LIVE_SOAK_VERIFIED`
  保留为独立未来里程碑。
- WORKFLOW_STATE / CURRENT_TASK / docs/GATES / 本报告一致。

## 验证

- 全量回归：`python -m unittest discover -s tests -p "test_*.py"` → **840 tests OK**。
- `python -m compileall -q src tests` → exit 0。
- AST 能力扫描：`assert` / `order_stock` / `cancel_order_stock` / `xtquant` import
  → 0 命中。
- `git diff --check` clean。
- `_tmp/` 保持从 HEAD 移除。
- `live_trading_allowed=false`；无真实 order/cancel 能力；Gate 5.5/6/7 BLOCKED。

## 未决 / 移交

- 真实连续实时 live-soak（wall-clock ≥5 日）未执行；`LIVE_SOAK_VERIFIED` 保留。
- 非零持仓 REAL_QMT 实机证据（含真实持仓）不提交（AUD-R1-005）；脱敏离线合成版在
  `work/reports/shadow/remediation-evidence/nonzero-core-position/`。若审计要求
  REAL_QMT 非零摘要且 MiniQMT 不可用，该接受项显式标记 BLOCKED。
