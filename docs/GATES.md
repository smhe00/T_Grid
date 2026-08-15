# TGrid Gate 体系状态

> **Independent Audit Node A — 2026-08-15:** DSH Gate-5 remediation is retained but did not pass independent audit. Gate 5 returns to `CHANGES_REQUIRED`; Gate 5.5 / Gate 6 / Gate 7 remain blocked. See `work/gates/GATE_5/NODE_A_REVIEW_20260815.md`.

| Gate | 内容 | 当前状态 | 说明 / 验收证据 |
|------|------|----------|-----------------|
| G0 | 项目骨架 | PASS | 历史 Gate 证据 |
| G1 | QMT 只读接入 | PASS | 只读边界 |
| G2 | Position + Ledger + Reconciliation | PROVISIONAL / SELF_CERTIFIED | G2-T005 有独立历史验收；其余保留并周期抽审 |
| G3 | 策略算法离线模拟 | PROVISIONAL / SELF_CERTIFIED | 保留现有实现与测试 |
| G4 | Execution Dry Run | PROVISIONAL / SELF_CERTIFIED | AUD-R1-007 exact-type hardening本轮可接受 |
| G5 | Shadow：REAL market/broker query + WOULD orders | **CHANGES_REQUIRED — NODE A** | `work/gates/GATE_5/NODE_A_REVIEW_20260815.md` |
| G5.5 | Real Broker Adapter / pre-live capability | **NOT AUTHORIZED / BLOCKED** | 仅 Node A independent PASS 后另行授权；实现后必须 Node B |
| G6 | 极小真实资金验证 | **BLOCKED** | Node B independent PASS + 用户显式授权前禁止开始 |
| G7 | V1 正式运行 | **BLOCKED** | Gate 6 完成并独立通过前禁止开始 |

## 最新 DSH 自证基线

Latest remediation commit `910a727d3ef66c262abfd9dea45b092106f6d4a6` claims **820 tests OK** and `live_trading_allowed=false`. This is SELF_CERTIFIED evidence; it is not an independent PASS.

## Node A 未关闭问题

1. ADJUSTED daily basis仍直接与RAW 5m价格比较，缺少corporate-action basis-domain normalization。
2. settlement released quantity不能跨多个后续交易日持续可卖。
3. settlement规则/未知symbol仍存在默认猜测；真实QMT runner必须显式策略并fail closed。
4. 非零reconciliation合成证据用 `held-core` 自动推Strategic，违反No Silent Reconcile；真实期望分解必须来自独立可信本地状态。
5. `_tmp/` 虽已加入 `.gitignore`，但仍被GitHub当前HEAD跟踪。
6. canonical state/task/docs/test count/evidence status仍不一致（含 `PENDING_PUSH`、818 vs 820、`LIVE VERIFIED`措辞）。

## 已接受的本轮修复

- XtQuant `dividend_type` 显式透传（front/none）；
- `reconciliation` 与 `shadow_delta` 数据结构分离；
- 历史回放与continuous live soak的证据类别开始区分；
- ExecutionEngine capacity exact-type hardening；
- 没有新增真实 order/cancel capability，Live仍默认关闭。

## 下一独立审计节点

DSH 只执行 `work/control/CURRENT_TASK.md` 的 Node-A Iteration 3 修复。完成后设置 `AUDIT_READY` 并停止。Gate 5.5 仍不得开始。
