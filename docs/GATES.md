# TGrid Gate 体系状态

> **Independent audit override — 2026-08-15:** 最新单 Agent（DSH）提交保留，但其 Gate 2–5 `Architect Review` 属于 `SELF_CERTIFIED`，不等同于独立验收。独立阶段审计已将 Gate 5 调整为 `CHANGES_REQUIRED`，Gate 6/7 在后续独立审计前保持 `BLOCKED`。详细要求见 `work/gates/GATE_5/INDEPENDENT_AUDIT_20260815.md`。

| Gate | 内容 | 当前状态 | 说明 / 验收证据 |
|------|------|----------|-----------------|
| G0 | 项目骨架：配置/模型/风险异常/日志/CLI/Event Queue/SQLite | PASS | 历史 Gate 证据 `work/gates/GATE_0/` |
| G1 | QMT 只读接入：Trader/MarketData/QuoteSubscription Adapter + 探针 + Runtime Bridge | PASS | 只读边界；真实交易能力仍禁止 |
| G2 | Position + Ledger + Reconciliation | **PROVISIONAL / SELF_CERTIFIED** | G2-T005 已有独立历史验收；G2-T006 与汇总 Gate 2 由 DSH self-certify，保留实现，后续抽审 |
| G3 | 策略算法离线模拟 | **PROVISIONAL / SELF_CERTIFIED** | 保留现有实现与测试；等待周期性独立抽审 |
| G4 | Execution Dry Run：OrderIntent/Reservation、SimBroker、Executor、恢复 | **PROVISIONAL / SELF_CERTIFIED** | 架构方向保留；真实 Broker 复用前需 exact-type/fail-closed hardening |
| G5 | Shadow 模式：REAL market/broker query + WOULD orders | **CHANGES_REQUIRED** | Independent Audit `work/gates/GATE_5/INDEPENDENT_AUDIT_20260815.md` |
| G5.5 | Real Broker Adapter / pre-live capability | **NOT AUTHORIZED / BLOCKED** | 仅 Gate 5 Audit Node A 独立 PASS 后另行授权；实现完成后必须 Audit Node B |
| G6 | 极小真实资金验证 | **BLOCKED** | Audit Node B 独立 PASS + 用户显式授权前禁止开始 |
| G7 | V1 正式运行 | **BLOCKED** | Gate 6 完成并独立通过前禁止开始 |

## 当前测试证据

DSH 最新提交自报：

```text
python -m unittest discover -s tests -p "test_*.py"   # 799 tests OK
python -m compileall -q src tests                      # exit 0
src AST scan (assert/order_stock/cancel_order_stock/xtquant)  # reported 0 forbidden live-order hits
```

这些是 **SELF_CERTIFIED evidence**，不自动构成 independent Gate PASS。

## 当前强制安全边界

- `live_trading_allowed=false`。
- Gate 5 remediation 不得新增或调用真实 `order_stock` / real cancel 路径。
- Gate 6/7 不得开始。
- `_tmp/` / local runtime config / account or environment details不得进入新提交。
- RAW/ADJUSTED 口径、settlement/T+1 sellability、real-vs-shadow reconciliation 必须在 Gate 5 remediation 中修复并测试。

## 下一独立审计节点

1. **AUDIT NODE A**：DSH 完成 Gate 5 remediation，push `main`，状态置 `AUDIT_READY` 后停止；ChatGPT 独立审计实际 diff/测试/实机证据。
2. **AUDIT NODE B**：Node A PASS 后，未来 Gate 5.5 实现真实 Broker capability；在首次真实订单调用前再次停止并独立审计。

详细执行清单以 `work/control/CURRENT_TASK.md` 和 `work/gates/GATE_5/INDEPENDENT_AUDIT_20260815.md` 为准。
