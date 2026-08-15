# TGrid Gate 体系状态

> **2026-08-15 Independent Audit Node B Iteration 1:** Gate 5 保持独立 `PASS`；Gate 5.5
> Live Broker Adapter 的首次 pre-live 审计结论为 `CHANGES_REQUIRED`。当前实现保留，但尚未形成
> 可审计的 `ExecutionEngine -> LiveBrokerAdapter -> XtQuantTrader` 真实执行链，且 kill-switch、
> callback 隔离、持久化日敞口、live recovery 等存在 pre-live blocker。详细见
> `work/gates/GATE_5_5/NODE_B_REVIEW_20260815.md`。

| Gate | 内容 | 当前状态 | 说明 / 验收证据 |
|------|------|----------|-----------------|
| G0 | 项目骨架：配置/模型/风险异常/日志/CLI/Event Queue/SQLite | PASS | 历史 Gate 证据 `work/gates/GATE_0/` |
| G1 | QMT 只读接入：Trader/MarketData/QuoteSubscription Adapter + 探针 + Runtime Bridge | PASS | 只读边界 |
| G2 | Position + Ledger + Reconciliation | **PROVISIONAL / SELF_CERTIFIED** | G2-T005 有独立历史验收；其余保留待后续抽审 |
| G3 | 策略算法离线模拟 | **PROVISIONAL / SELF_CERTIFIED** | 保留现有实现与测试 |
| G4 | Execution Dry Run：OrderIntent/Reservation、SimBroker、Executor、恢复 | **PROVISIONAL / SELF_CERTIFIED** | 仅 dry-run 路径；不能视为 live broker 已集成 |
| G5 | Shadow 模式：REAL market/broker query + WOULD orders | **PASS**（Node A 独立审计） | `work/gates/GATE_5/NODE_A_FINAL_REVIEW_20260815.md` |
| G5.5 | Real Broker Adapter / pre-live capability | **CHANGES_REQUIRED**（Node B Iteration 1） | `work/gates/GATE_5_5/NODE_B_REVIEW_20260815.md`；禁止真实 order/cancel |
| G6 | 极小真实资金验证 | **BLOCKED** | 仅 Node B PASS + 用户显式授权后才可开始 |
| G7 | V1 正式运行 | **BLOCKED** | Gate 6 完成并独立通过前禁止开始 |

## Node B 当前结论

### 已接受

- Gate 5 / Node A PASS 保持有效；
- NODEB-P0-001 legacy reconciliation Core mismatch guard 已接通；
- LiveBrokerAdapter scaffold 默认 live/confirmation=false；
- allowlist 与基础 per-order qty/cash policy 存在；
- Gate-5.5 evidence 期间未执行真实 order/cancel。

### 仍阻塞首次真实订单

1. `ExecutionEngine` 仍强制 `SimBroker`，并依赖 `get_order/tick_order` 仿真接口；`LiveBrokerAdapter` 无法直接接入。
2. 尚无 concrete XtQuant execution bridge；当前 capability scan 的“0 个 order_stock/cancel_order_stock”说明真实 capability 尚未实现。
3. Gate-4 OrderIntent/Reservation/idempotency/recovery 未通过 live-adapter 集成路径证明。
4. kill switch 当前也阻断 cancel，紧急状态下无法通过 adapter 撤已有挂单。
5. callback wrapper 仍执行任意 callable，未结构性保证“callback -> Event Queue only”。
6. daily cash exposure 为内存计数且可任意 reset，进程重启可重新获得完整日额度。
7. cash/price 校验未拒绝 NaN/Inf，存在比较绕过风险。
8. production double-enable 尚需绑定 trusted config + 每次重启后重新显式 runtime confirmation。

## 当前自证测试状态

DSH 报告 `865 tests OK`、compileall exit 0、capability scan 无真实调用点；这些仍属于
`SELF_CERTIFIED`，不构成 Node B PASS。Node B 要求新增完整 pre-live execution integration tests。

## 关键不变量

INV-001 Core Floor / INV-002 T Capacity / INV-003 Target Ceiling / INV-004 单方向单挂单 /
INV-005 Broker Authority / INV-006 禁止静默对账 / INV-007 禁止自动止损 / INV-008 禁止退出
Core/Strategic / INV-009 Live Default OFF / INV-010 Fail Closed / INV-011 禁止 assert 安全 /
INV-012 Reservation 先行 / INV-013 订单意图幂等 / INV-014 Callback 隔离 / INV-015 Corporate
Action HALT / INV-016 人工变化检测 / INV-017 数据新鲜度。

## 下一独立审计节点

**AUDIT NODE B — Iteration 2:** DSH 仅修复 `work/gates/GATE_5_5/NODE_B_REVIEW_20260815.md`
中的 pre-live blocker。完成后必须停在 `AUDIT_READY_PRELIVE`。任何真实 order/cancel 仍被禁止。

首次真实订单的必要条件仍为：

```text
Audit Node B = PASS
AND
用户显式授权 = YES
```
