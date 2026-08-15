# TGrid Gate 体系状态

> **Independent audit override — 2026-08-15:** DSH implementation/self-review is `SELF_CERTIFIED` and never substitutes for independent Gate acceptance.
>
> **Gate 5:** independent Audit Node A PASS（commit `4c1cc8c`）。
>
> **Gate 5.5 / Audit Node B:** Iteration 3 implementation (`469116c8`) materially closes the earlier BrokerPort/int-order-id/UNKNOWN/EventQueue/basic exposure/executor-hardening findings. During the independent re-review the user identified `smhe00/reverse_repo` as the actual production miniQMT reference. The audit was therefore reset to a pinned reference-conformance review rather than continuing to rediscover QMT semantics. Reference: `smhe00/reverse_repo@c9ecc701d9b1c47d6a8d03539b482368741204a3`. Verdict remains **CHANGES_REQUIRED**, but scope is now finite: `NODEB-RR-001..006` only. See `work/gates/GATE_5_5/NODE_B_REVIEW_ITER3_REFERENCE_20260815.md`.

| Gate | 内容 | 当前状态 | 说明 / 验收证据 |
|------|------|----------|-----------------|
| G0 | 项目骨架：配置/模型/风险异常/日志/CLI/Event Queue/SQLite | PASS | 历史 Gate 证据 `work/gates/GATE_0/` |
| G1 | QMT 只读接入：Trader/MarketData/QuoteSubscription Adapter + Runtime Bridge | PASS | 已有 hardened account/runtime binding；Gate 5.5 production path 应复用，不应旁路 |
| G2 | Position + Ledger + Reconciliation | **PROVISIONAL / SELF_CERTIFIED** | G2-T005 有独立历史验收；其余保留，后续抽审 |
| G3 | 策略算法离线模拟 | **PROVISIONAL / SELF_CERTIFIED** | 保留现有实现与测试 |
| G4 | Execution Dry Run：OrderIntent/Reservation、SimBroker、Executor、恢复 | **PROVISIONAL / SELF_CERTIFIED** | Gate 5.5 正在复用其 Reservation/Idempotency |
| G5 | Shadow：REAL market/broker query + WOULD orders | **PASS** | Node A independent PASS commit `4c1cc8c` |
| G5.5 | Real Broker Adapter / pre-live capability | **CHANGES_REQUIRED — IT4 reference-conformance** | 仅修 `NODEB-RR-001..006`; golden QMT reference = `smhe00/reverse_repo@c9ecc701...` |
| G6 | 极小真实资金验证 | **BLOCKED** | Node B independent PASS + 用户显式授权前禁止开始 |
| G7 | V1 正式运行 | **BLOCKED** | Gate 6 完成并独立通过前禁止开始 |

## Iteration 3 accepted / frozen

以下事项已在 Node-B 审计中接受，后续不得无故重构：

- `ExecutionEngine -> BrokerPort -> LiveBrokerAdapter -> XtQuantBrokerBridge` 架构；
- XtQuant 真实 `order_stock/cancel_order_stock` 仅存在于单一 audited bridge；
- native int order-id 与 TGrid string serialization 的边界转换；
- OrderIntent + Reservation-before-send + client key 幂等；
- UNKNOWN broker status -> reconciliation error + SAFE_MODE；
- duplicate key/remark recovery candidate fail-closed；
- real TGrid EventQueue 的 immutable/data-only callback 接线；
- kill switch 阻止新单但保留 cancel/query；
- BUY daily exposure 在 broker send 前持久预留；
- Executor/Adapter NaN/Inf 在持久化/算术/broker 前拒绝；
- legacy Core authority guard；
- `live_trading_allowed=false` 且尚未执行真实 TGrid order/cancel。

## Final Node-B remediation — reference conformance only

`CURRENT_TASK.md` 只授权以下六项：

1. **NODEB-RR-001:** production live bootstrap 必须复用已验证的 environment/QMT-path/account binding，不能接受任意 raw account 作为生产入口。
2. **NODEB-RR-002:** 复用/移植 `reverse_repo.strict_query` 的 bounded retry + `None` ambiguous 语义；live query 不得自行发明另一套行为。
3. **NODEB-RR-003:** startup order recovery 必须强制执行；SAFE_MODE 只能经成功 reconciliation 解除，不能裸 `clear`。
4. **NODEB-RR-004:** concrete durable exposure journal/store + trusted current session rollover；不以未经规范化的 broker `order_time` 字符串格式作为安全依据。
5. **NODEB-RR-005:** new-order health gate 必须直接观察 EventQueue lifecycle；disconnect 立即 unhealthy；不能等下一次 callback 才发现失败。
6. **NODEB-RR-006:** exact Git SHA/control metadata；上一轮 `cb7aeb660...` 为 typo，正确是 `cb7aeb600...`。

## QMT golden reference

Pinned repository/commit:

```text
https://github.com/smhe00/reverse_repo
c9ecc701d9b1c47d6a8d03539b482368741204a3
```

最低必读：

```text
scripts/repo_execution_core.py
scripts/gc001_live_daily_90pct_093042.py
tests/test_repo_execution_core.py
```

其已验证模式包括：strict query、native int order id、完整 order-status 分类、account/QMT-path fingerprint binding、durable intent/journal before submission、restart recovery、callback-only wake/update、current trading date/session validation、以及 1000 元真实通道认证。TGrid 不应重复重新发明这些 QMT 语义。

## 当前测试证据

DSH 报告 Iteration 3：

```text
929 tests OK
compileall exit 0
capability scan: bridge 内真实 order/cancel call sites = 2，bridge 外 = 0
```

这些仍属于 `SELF_CERTIFIED` evidence，不自动构成 Node B PASS。

## 下一独立审计节点

DSH 完成 `NODEB-RR-001..006` 后：

```text
state = AUDIT_READY_PRELIVE
authorized_next = AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER
live_trading_allowed = false
```

下一轮独立审计将以 pinned `reverse_repo` commit 为 QMT 行为基线，并且不会在没有具体 regression 的情况下重新打开已经 frozen 的 Node-B 项。

首次真实 TGrid 订单仍要求：

```text
Audit Node B = PASS
AND
用户显式授权 = YES
```
