# TGrid Gate 体系状态

> **Independent audit status — 2026-08-15:** Gate 5 Shadow Mode 已完成独立 Audit Node A 并 PASS。
> Gate 5.5 pre-live execution capability 仍在 Audit Node B；Iteration 2 复审结论为
> `CHANGES_REQUIRED`。在 Node B PASS + 用户显式授权之前，禁止首次真实 order/cancel，
> `live_trading_allowed=false` 保持。

| Gate | 内容 | 当前状态 | 说明 / 验收证据 |
|------|------|----------|-----------------|
| G0 | 项目骨架：配置/模型/风险异常/日志/CLI/Event Queue/SQLite | PASS | 历史 Gate 证据 `work/gates/GATE_0/` |
| G1 | QMT 只读接入：Trader/MarketData/QuoteSubscription Adapter + 探针 + Runtime Bridge | PASS | 只读边界 |
| G2 | Position + Ledger + Reconciliation | **PROVISIONAL / SELF_CERTIFIED** | G2-T005 有独立历史验收；其余保留并后续抽审 |
| G3 | 策略算法离线模拟 | **PROVISIONAL / SELF_CERTIFIED** | 保留现有实现与测试 |
| G4 | Execution Dry Run：OrderIntent/Reservation、SimBroker、Executor、恢复 | **PROVISIONAL / SELF_CERTIFIED** | Gate-4 execution semantics 已被 Gate-5.5 live chain 复用，但 G4 汇总仍为 provisional |
| G5 | Shadow 模式：REAL market/broker query + WOULD orders | **PASS**（NODE A 独立审计） | `work/gates/GATE_5/NODE_A_FINAL_REVIEW_20260815.md` |
| G5.5 | Real Broker Adapter / pre-live capability | **CHANGES_REQUIRED — Node B Iteration 2** | 审计 `work/gates/GATE_5_5/NODE_B_REVIEW_ITER2_20260815.md`；Iteration 3 只允许修 pre-live blockers |
| G6 | 极小真实资金验证 | **BLOCKED** | Audit Node B PASS + 用户显式授权前禁止开始 |
| G7 | V1 正式运行 | **BLOCKED** | Gate 6 完成并独立通过前禁止开始 |

## Iteration 2 已独立接受的 Gate 5.5 方向

- `BrokerPort` 统一 dry-run/live 执行端口；
- `ExecutionEngine` 不再依赖 `SimBroker` 专用 hook；
- `XtQuantBrokerBridge` 为唯一 concrete XtQuant order/cancel bridge；
- full fake chain：`ExecutionEngine -> LiveBrokerAdapter -> XtQuantBrokerBridge(FakeTrader)`；
- OrderIntent + Reservation-before-send、client key 幂等；
- kill switch：阻止新单，不阻止 cancel/query/cancel-all；
- legacy Core mismatch guard；
- adapter policy / limit-price NaN/Inf 拒绝；
- generic arbitrary broker callback registration 已移除；
- 无真实 order/cancel 调用。

## Node B Iteration 2 剩余 blockers

1. **XtQuant native order_id 类型**：官方接口 `order_stock` / `cancel_order_stock` 使用 int order id；当前 bridge 把 id 字符串化后直接用于 cancel，fake 测试没有模拟真实类型。
2. **UNKNOWN / ambiguous broker state**：bridge 映射 UNKNOWN 后，executor 仍把本地订单保持为 SUBMITTED 正常返回；startup recovery 对 UNKNOWN / 多重匹配也未 fail closed。
3. **Callback/EventQueue 真正接线**：TGrid `EventQueue` 使用 `enqueue()`，bridge handler 目前要求 `.put()`；disconnect/account-status/order-error/cancel-error 仍被丢弃。
4. **Daily exposure crash safety**：durable store 仍可选；startup reconstruction 不是强制 readiness gate；broker accept -> ledger persist 存在 crash window；terminal same-day order reconstruction 与“submitted BUY notional”规则不一致；roll_day 只做字符串顺序比较。
5. **Executor 非有限值**：core executor 仍可能在 adapter 之前让 NaN/Inf cash/capacity 进入 durable intent/reservation。
6. **生产 bootstrap**：trusted config / durable exposure / EventQueue / bridge / startup recovery / runtime confirmation / ExecutionEngine 仍是分散步骤，缺少一个可审计安全顺序的构造路径。

## 当前 SELF_CERTIFIED 证据（不构成独立 PASS）

Iteration 2 DSH 报告：

```text
python -m unittest discover -s tests -p "test_*.py"   # 906 tests OK
python -m compileall -q src tests scripts             # exit 0
capability_scan: direct XtQuant order/cancel 仅在 xtquant_bridge.py 白名单中
```

## 关键不变量

INV-001 Core Floor / INV-002 T Capacity / INV-003 Target Ceiling / INV-004 单方向单挂单 /
INV-005 Broker Authority / INV-006 禁止静默对账 / INV-007 禁止自动止损 / INV-008 禁止退出
Core/Strategic / INV-009 Live Default OFF / INV-010 Fail Closed / INV-011 禁止 assert 安全 /
INV-012 Reservation 先行 / INV-013 订单意图幂等 / INV-014 Callback 隔离 / INV-015 Corporate
Action HALT / INV-016 人工变化检测 / INV-017 数据新鲜度。

## 下一审计节点

- **Audit Node A**：PASS。
- **Audit Node B Iteration 3**：DSH 仅修 `NODE_B_REVIEW_ITER2_20260815.md` 中剩余 blockers，完成后回到 `AUDIT_READY_PRELIVE` 并 STOP。
- **Gate 6**：仅在 `Node B PASS + 用户显式授权` 后才可能启动极小真实资金验证。
