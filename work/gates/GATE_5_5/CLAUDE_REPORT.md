# Gate 5.5 / Claude Report — Live Broker Adapter (Pre-Live Only)

## Status

`AUDIT_READY_PRELIVE (ITERATION 2)` — Node B 审计（`0f8e0a19`，
`work/gates/GATE_5_5/NODE_B_REVIEW_20260815.md`）判定 `CHANGES_REQUIRED`；
**NODEB-001..007 已全部修复（SELF_CERTIFIED）**，等待 Audit Node B 复审。
**本任务未调用任何真实 order/cancel；`live_trading_allowed=false` 保持。**

授权来源：Gate 5 Node A PASS（`4c1cc8c`）+ Node B 授权仅限修复 NODEB-001..007。

## Scope（Iteration 2）

| 文件 | 内容 |
|------|------|
| `src/tgrid/execution/port.py` | 共享 broker 执行端口 `BrokerPort` + 类型化 DTO（`BrokerOrder`/`BrokerTrade`）+ 共享错误层级（NODEB-001 #1/#4） |
| `src/tgrid/execution/executor.py` | `ExecutionEngine` 只依赖 `BrokerPort`，不再要求 `SimBroker`、不再调用 `tick_order/get_order`（NODEB-001 #2） |
| `src/tgrid/execution/simdriver.py` | `SimulationDriver`：确定性脚本仅在 simulation-only 路径（NODEB-001 #2） |
| `src/tgrid/execution/simbroker.py` | `SimBroker(BrokerPort)`：读侧返回类型化 DTO；`get_order/tick_order` 保留为 simulation hook |
| `src/tgrid/integrations/xtquant_bridge.py` | **唯一**具体 XtQuant 桥：`order_stock`/`cancel_order_stock` 唯一调用点 + 状态/边常量映射 + 桥自有 callback handler（NODEB-001 #3/#4） |
| `src/tgrid/integrations/live_broker_adapter.py` | kill switch 不再阻塞取消（NODEB-003）；移除通用 `register_callback`（NODEB-004）；持久化日敞口（NODEB-005）；NaN/Inf 拒绝（NODEB-006）；bootstrap 契约（NODEB-007） |
| `src/tgrid/integrations/daily_exposure.py` | `DailyExposureLedger`：trade_date 绑定、持久化、启动重建、单调 roll_day |
| `scripts/capability_scan.py` | 白名单 = 桥文件；桥外任何真实调用 → FAIL（NODEB-001 #5） |

## NODEB-001..007 Closure（SELF_CERTIFIED）

| # | 级别 | 修复 |
|---|------|------|
| NODEB-001 | P0 | `BrokerPort` 单一窄端口；`ExecutionEngine` 只依赖端口 + DTO；`SimulationDriver` 独占确定性脚本；`XtQuantBrokerBridge` 为仓库唯一 `order_stock`/`cancel_order_stock` 调用点（capability scan 白名单验证：桥内 2 处、桥外 0 处）；XtQuant 对象映射为 TGrid DTO；测试用 fake 后端 |
| NODEB-002 | P0 | `test_execution_live_chain.py`：`ExecutionEngine -> LiveBrokerAdapter -> XtQuantBrokerBridge(FakeTrader)` 全链路集成 —— intent+reservation 先于 send、client_order_key 幂等不二次 send、crash-before-send 不盲重发（INTENT_ONLY）、crash-after-accept 启动对账 MATCHED 恢复、部分成交保持剩余 reservation、timeout=cancel→re-query→reconcile、未匹配标记单→SAFE_MODE、查询失败/状态歧义→fail-closed |
| NODEB-003 | P0 | `cancel_order`/`cancel_all_managed_open_orders`/`query_*` 不依赖 `_require_ready_to_trade`；kill switch 仅阻止新单；测试证明 kill_switch=True 时新单被拒但取消+re-query 可用 |
| NODEB-004 | P0 | 移除 `register_callback` 通用任意回调边界；`XtQuantCallbackHandler` 桥自有，把 XtQuant payload 转成不可变数据事件，仅 `event_sink.put(event)`；handler 不持有 engine/store/adapter 引用（测试断言无属性 + frozen 事件） |
| NODEB-005 | P0 | `DailyExposureLedger` 绑定 `trade_date` + 持久 store；启动 `reconstruct_daily_exposure()` 从 managed broker 订单保守重建；`roll_day` 仅接受单调交易日推进；无公共无条件清零；计数规则=提交 BUY 名义（cancel/reject/partial/restart 下确定性保守）；restart + same-day-reset fault-injection 测试 |
| NODEB-006 | P0 | `LiveBrokerPolicy` 与 `place_order` 用 `math.isfinite` 拒绝 NaN/±Inf（exact-type 之后、任何算术/broker 调用之前）；NaN/Inf 测试覆盖 policy 值与 limit_price |
| NODEB-007 | P1 | `live_enabled`/`runtime_confirmed` 不再是构造字段（init=False）；`apply_config_enable(flag)` 只接受 trusted bool；`confirm_runtime(token)` 需精确匹配启动 token；重启（新实例）恒为 runtime_confirmed=false；callback 结构性无法触碰 enable/confirm |

## Evidence

- 回归：`python -m unittest discover -s tests -p "test_*.py"` → **906 tests OK**（较 865 新增 41：live chain 集成、bridge 映射、callback 隔离、exposure 持久化、kill-switch 取消、NaN/Inf、bootstrap 契约）。
- `python -m compileall -q src tests scripts` → exit 0。
- capability 扫描：`src` 53 文件；真实 `order_stock`/`cancel_order_stock` 调用点 **桥内 2 处（白名单）、桥外 0 处**；`RESULT: PASS`。
- 测试文件：`test_execution_live_chain.py`（新）、`test_xtquant_bridge.py`（新）、
  `test_live_broker_adapter.py`（重写）、`test_execution.py`（SimulationDriver 路由）。
- 既有 AST 扫描（assert / xtquant import / 桥外 order call）全部保持 PASS（4 个测试文件白名单同步）。

## Boundary

- 本任务**绝不 invoke** 真实 order/cancel；所有 broker 调用经注入 fake/bridge。
- 未实现/未授权：真实资金运行、Gate 6、live-soak。
- `live_trading_allowed=false`；Gate 6/7 BLOCKED。
- 授权令牌：`AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`。

## Recommendation

`AUDIT_READY_PRELIVE`（Iteration 2）——等待 Audit Node B 复审 NODEB-001..007；
首笔真实订单须 Node B PASS + 用户显式授权。
