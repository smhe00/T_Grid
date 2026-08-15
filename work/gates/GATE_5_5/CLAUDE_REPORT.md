# Gate 5.5 / Claude Report — Live Broker Adapter (Pre-Live Only)

## Status

`REVIEW_READY (PRELIVE)` — 实现完成（SELF_CERTIFIED），等待 Audit Node B 独立复审。
**本任务未调用任何真实 order/cancel；`live_trading_allowed=false` 保持。**

授权来源：`work/gates/GATE_5/NODE_A_FINAL_REVIEW_20260815.md`（Gate 5.5
AUTHORIZED_FOR_IMPLEMENTATION_ONLY）。

## Scope

`src/tgrid/integrations/live_broker_adapter.py`：`LiveBrokerAdapter` + `LiveBrokerPolicy`，
封装注入的 order/cancel/query 面（生产为真实 XtQuantTrader 包装、测试为 fake），
带强制 pre-live 安全边界。

## Mandatory Requirements Coverage（14 项）

| # | 要求 | 实现 |
|---|------|------|
| 1 | live_trading 默认 false，不可隐式开启 | `live_enabled=False` 默认 |
| 2 | 二次显式运行时确认 | `confirm_runtime()` 独立于 `enable_live_trading()`；二者皆需 true |
| 3 | 显式 symbol 白名单 | `LiveBrokerPolicy.allowlist` |
| 4 | 每单数量硬上限 | `max_order_qty` |
| 5 | 每单/每日现金敞口硬上限 | `max_cash_per_order` / `max_cash_per_day` + 日计数器 |
| 6 | Kill switch | `engage_kill_switch()` 阻止一切新单 |
| 7 | callback 只能入队 | `register_callback` 包装；callback 无 broker/状态访问面 |
| 8 | 复用 Gate-4 幂等 OrderIntent+Reservation | 适配器与 ExecutionEngine 契约一致；幂等由 Gate-4 层持有 |
| 9 | 部分成交显式建模 | `query_trades`/`query_order` 暴露 filled_qty |
| 10 | 超时 cancel→re-query→reconcile；cancel 不意味零成交 | `cancel_order` 后必须 `query_order`（测试验证部分成交仍可观察） |
| 11 | 订单/成交对账与崩溃恢复确定且 fail-closed | 适配器层查询语义确定；恢复由 Gate-4 recovery 复用 |
| 12 | exact-type 先于算术/券商调用 | `place_order` 入口 exact-type 校验后再调用 broker（AUD-R1-007 纪律） |
| 13 | 无 force push / 历史重写 | 遵循 |
| 14 | 不提交账号/余额/持仓/端口/路径/密钥/本地运行时配置 | 遵循 |

## Mandatory Carry-Forward — NODEB-P0-001 ✅

修复 `_load_reconciliation_state`：legacy `core_qty` 现在被 loader **保留**为
`legacy_core_qty`，`_check_core_authority` 做精确相等校验后才丢弃；不匹配 →
`SystemExit` fail-closed。loader-to-runner 集成测试证明 legacy core=700 vs
配置 600 fail closed（`test_node_a_iter5.py::TestNodeBP0001LegacyCoreGuard`）。

## Evidence

- 回归：`python -m unittest discover -s tests -p "test_*.py"` → **865 tests OK**。
- `python -m compileall -q src tests` → exit 0。
- capability 扫描（`scripts/capability_scan.py`）：src 49 文件，直接
  `order_stock` / `cancel_order_stock` 调用点 **0**；4 个 adapter 级入口
  （executor.place_order/cancel_order → SimBroker 路径；
  live_broker_adapter.place_order/cancel_order → 注入 broker）。
- 测试：`tests/unit/test_live_broker_adapter.py`（16 项：双确认、白名单、硬上限、
  日敞口、kill switch、callback 隔离、exact-type、cancel-re-query、capability 扫描）。

## Boundary

- 本任务**绝不 invoke** 真实 order/cancel；所有 broker 调用经注入对象。
- 未实现/未授权：真实资金运行、Gate 6、live-soak。
- `live_trading_allowed=false`；Gate 6/7 BLOCKED。

## Recommendation

`AUDIT_READY_PRELIVE`（等待 Audit Node B 独立复审；首笔真实订单须
Node B PASS + 用户显式授权）。
