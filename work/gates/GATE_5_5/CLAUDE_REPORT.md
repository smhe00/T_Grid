# Gate 5.5 / Claude Report — Live Broker Adapter (Pre-Live Only)

## Status

`AUDIT_READY_PRELIVE (ITERATION 3)` — Node B Iteration-2 复审（`cb7aeb6`，
`work/gates/GATE_5_5/NODE_B_REVIEW_ITER2_20260815.md`）判定 `CHANGES_REQUIRED`；
**NODEB-I2-001..006 已全部修复（SELF_CERTIFIED）**，等待 Audit Node B 复审。
**本任务未调用任何真实 order/cancel；`live_trading_allowed=false` 保持。**

授权来源：Gate 5 Node A PASS（`4c1cc8c`）+ Node B Iteration-2 授权仅限修复
NODEB-I2-001..006。

## Scope（Iteration 3）

| 文件 | 内容 |
|------|------|
| `src/tgrid/integrations/xtquant_bridge.py` | 原生 **int** order-id 契约（I2-001）；桥边界单点 audited str↔int 转换；真实 TGrid EventQueue 接线（`.enqueue`/`.put` 双通道）（I2-003）；disconnect/account-status/order-error/cancel-error 不可变事件；`execution_healthy` 健康信号 |
| `src/tgrid/execution/executor.py` | UNKNOWN broker 状态 → `OrderReconciliationError` + SAFE_MODE（新单被阻，`clear_safe_mode` 显式恢复）（I2-002）；NaN/±Inf 在 `create_intent` **之前**拒绝（I2-005） |
| `src/tgrid/execution/recovery.py` | 拒绝 UNKNOWN broker 状态 / 多候选 key/remark 匹配 → fail-closed（I2-002） |
| `src/tgrid/integrations/daily_exposure.py` | `trade_date` 校验为真实 ISO 日历日期；重建包含**当日终态** managed BUY 单（I2-004） |
| `src/tgrid/integrations/live_broker_adapter.py` | live 构造**强制** durable exposure store；`exposure_ready` 启动门（新单前必须重建成功）；BUY 名义在 broker send **之前**持久预留（关闭 crash 窗口）（I2-004）；`roll_day` 绑定可信 session 日期 |
| `src/tgrid/integrations/live_bootstrap.py` | 单一生产 bootstrap 工厂：config+policy+durable store+EventQueue+bridge+adapter+startup reconciliation+非持久 runtime confirm+engine；activate 前无法下单；歧义恢复 fail-closed（I2-006） |

## NODEB-I2-001..006 Closure（SELF_CERTIFIED）

| # | 级别 | 修复 |
|---|------|------|
| I2-001 | P0 | fake trader 改为原生 **int** order-id（`5001`…）；桥 `_to_native_order_id` 为唯一 audited 转换；`cancel_order_stock` 收到的是 **int**（测试断言 `type(args[1]) is int`）；TGrid DTO/store 保持确定性 str 序列化 |
| I2-002 | P0 | `poll_order` 对 UNKNOWN 抛 `OrderReconciliationError` 并进入 SAFE_MODE（新单被阻直到 `clear_safe_mode`）；`reconcile_open_intents` 拒绝 UNKNOWN 状态与多候选 key/remark 匹配；测试证明歧义阻止新执行 |
| I2-003 | P0 | 桥直连真实 TGrid `EventQueue`（`.enqueue()`）；测试实例化真实 queue、start、喂 fake XtQuant callback、worker 线程消费不可变事件；disconnect/account-status/order-error/cancel-error 均有事件；queue FAILED/stopped → `execution_healthy=False` → adapter 拒单 |
| I2-004 | P0 | live 构造无 durable store 即拒绝；`exposure_ready` 启动门（`ExposureNotReadyError`）；BUY 名义 send 前持久预留；重建含当日终态 managed 单；`trade_date` 真实 ISO 校验；`roll_day` 可绑定可信 session 日期；bogus/future roll 输入测试 |
| I2-005 | P1 | `ExecutionEngine._send` 对 `limit_price`/`expected_available_cash`/`cash_amount` 全部 `math.isfinite` 校验，先于任何算术/持久化/broker 调用；测试证明 NaN/Inf → 零 store 变更、零 broker 调用 |
| I2-006 | P1 | `build_live_stack` 单一工厂按审计顺序组装；`activate()` 先重建 exposure、再 startup reconciliation（UNMATCHED_BROKER_ORDER → fail-closed）、最后 token 确认；activate 前无法下单；全部用 fake XtQuant |

## Evidence

- 回归：`python -m unittest discover -s tests -p "test_*.py"` → **929 tests OK**（较 906 新增 23：int 契约、UNKNOWN/SAFE_MODE、EventQueue 集成、exposure crash-safety、executor NaN、bootstrap）。
- `python -m compileall -q src tests scripts` → exit 0。
- capability 扫描：`src` 54 文件；真实 `order_stock`/`cancel_order_stock` 调用点 **桥内 2 处（白名单）、桥外 0 处**；`RESULT: PASS`。
- 测试文件：`test_live_bootstrap.py`（新）、`test_xtquant_bridge.py`（int 契约重写）、`test_execution_live_chain.py`（UNKNOWN/SAFE_MODE/int 扩展）、`test_live_broker_adapter.py`（exposure 门扩展）、`test_execution.py`（NaN 扩展）。
- 既有 AST 扫描（assert / xtquant import / 桥外 order call）全部保持 PASS。

## Boundary

- 本任务**绝不 invoke** 真实 order/cancel；所有 broker 调用经注入 fake/bridge。
- 未实现/未授权：真实资金运行、Gate 6、live-soak。
- `live_trading_allowed=false`；Gate 6/7 BLOCKED。
- 授权令牌：`AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`。

## Recommendation

`AUDIT_READY_PRELIVE`（Iteration 3）——等待 Audit Node B 复审 NODEB-I2-001..006；
首笔真实订单须 Node B PASS + 用户显式授权。
