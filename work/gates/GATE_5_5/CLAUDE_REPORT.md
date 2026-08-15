# Gate 5.5 / Claude Report — Live Broker Adapter (Pre-Live Only)

## Status

`AUDIT_READY_PRELIVE (ITERATION 4)` — Node B Iteration-3 复审（`3b0d53f`，
`work/gates/GATE_5_5/NODE_B_REVIEW_ITER3_REFERENCE_20260815.md`）判定
`CHANGES_REQUIRED`；**NODEB-RR-001..006 已全部修复（SELF_CERTIFIED）**，
等待 Audit Node B 复审。**本任务未调用任何真实 order/cancel；
`live_trading_allowed=false` 保持。**

授权来源：Gate 5 Node A PASS（`4c1cc8c`）+ Node B Iteration-3 授权仅限修复
NODEB-RR-001..006（reference-conformance pass）。

参考实现（QMT 行为基线）：`https://github.com/smhe00/reverse_repo`
pinned commit `c9ecc701d9b1c47d6a8d03539b482368741204a3`。

## Reference-Conformance Matrix（reverse_repo c9ecc70 → TGrid）

| reverse_repo 模式 | 文件 | TGrid 实现/测试 |
|------|------|------|
| `strict_query()` 有界重试，None 永不等于空成功 | `scripts/repo_execution_core.py` | `XtQuantBrokerBridge._strict_query` → `BrokerQueryAmbiguous`（RR-002）|
| `query_order_strict()` 原生 `query_stock_order(account, int)` | 同上 | `query_order` 优先原生单查，否则严格唯一匹配扫描（RR-002）|
| `select_bound_account()` env/path/fingerprint/唯一 normal 账号 | 同上 | `build_live_session` + Gate-1 `load_account_binding`/`_select_normal_account`（RR-001）|
| `AccountBinding` 禁明文账号、SHA-256 fingerprint | 同上 | Gate-1 `parse_account_binding`（沿用）|
| `classify_order()` 已知/未知状态分类 | 同上 | `XT_STATUS_TO_TGRID` + UNKNOWN fail-closed（I2-002）|
| callback 仅 wake/update 信号，broker query 权威 | `BrokerUpdateSignal` | `XtQuantCallbackHandler` → EventQueue 不可变事件（I2-003）|
| AtomicJournal 持久 journal + 确定重启恢复 | 同上 | `SqliteExposureStore` + mandatory `reconcile_open_intents`（RR-003/004）|
| 当前 session/trade-date 校验后 live 执行 | 同上 | `roll_day(session_date=必填)` + ISO 校验（RR-004）|

## NODEB-RR-001..006 Closure（SELF_CERTIFIED）

| # | 级别 | 修复 |
|---|------|------|
| RR-001 | P0 | `build_live_session()` 生产 live-session 工厂：复用 Gate-1/reverse_repo 账号绑定语义（environment 匹配、QMT-path fingerprint 校验、strict 查询 account infos/statuses、唯一 normal securities 账号匹配 fingerprint、subscribe 后 opaque 绑定）；订单能力在验证失败/歧义时不可达（FI：错误 env、path fingerprint 不匹配 → fail closed） |
| RR-002 | P0 | 移植 `strict_query` 有界重试：None/异常重试 3 次后抛 `BrokerQueryAmbiguous`；`query_orders`/`query_trades`/`query_order` 全部 strict；`query_order` 优先原生 `query_stock_order(account, int)`，否则严格唯一匹配；FI：None、瞬时异常→成功、持久异常、空列表成功、重复匹配 |
| RR-003 | P0 | `LiveStack.activate()` 恢复**强制**（不再接受 None）；UNMATCHED_BROKER_ORDER/INTENT_ONLY/UNKNOWN/歧义阻塞激活并 engage SAFE_MODE；`reconcile_and_resume()` 为 reconciliation 驱动的 SAFE_MODE 释放（成功对账后才 `clear_safe_mode`）；restart 测试证明不能跳过恢复、不能裸翻转标志 |
| RR-004 | P0 | 具体 `SqliteExposureStore`（SQLite `daily_exposure` 表）由生产 bootstrap 自建（调用方不可替换 in-memory fake）；`roll_day` 的 `session_date` 在重置路径**必填**且须等于新日期；重建不依赖原始 QMT `order_time` 字符串格式（ISO 前缀或 durable 日期）；用具体 durable store 做 restart 测试 |
| RR-005 | P0 | `execution_healthy` 读取**真实 EventQueue 生命周期状态**（FAILED/STOPPING/STOPPED 即使无后续 callback 也立即拒单）+ handler 入队健康；`on_disconnected` 立即标记 unhealthy；`mark_connected()` 显式恢复；测试：worker 失败无后续 callback、断开后立即下单被拒、显式恢复后放行 |
| RR-006 | P1 | 修正 `WORKFLOW_STATE.yaml` `git_base_commit` SHA typo（`cb7aeb6006618…` 而非 `cb7aeb6606618…`）；新增 `reference_repository`/`reference_commit` 字段记录 pinned 参考 |

## Evidence

- 回归：`python -m unittest discover -s tests -p "test_*.py"` → **943 tests OK**（较 929 新增 14：strict-query FI、EventQueue 生命周期健康、durable SQLite exposure restart、account-binding FI、mandatory recovery、reconcile-driven SAFE_MODE）。
- `python -m compileall -q src tests scripts` → exit 0。
- capability 扫描：`src` 55 文件；真实 `order_stock`/`cancel_order_stock` 调用点 **桥内 2 处（白名单）、桥外 0 处**；`RESULT: PASS`。
- 测试文件：`test_xtquant_bridge.py`（strict-query FI 扩展）、`test_live_bootstrap.py`（durable store / EventQueue health / mandatory recovery / account binding 扩展）。
- 既有 AST 扫描（assert / xtquant import / 桥外 order call）保持 PASS。

## Boundary

- 本任务**绝不 invoke** 真实 order/cancel；所有 broker 调用经注入 fake/bridge。
- 未实现/未授权：真实资金运行、Gate 6、live-soak。
- `live_trading_allowed=false`；Gate 6/7 BLOCKED。
- 授权令牌：`AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`。

## Recommendation

`AUDIT_READY_PRELIVE`（Iteration 4）——等待 Audit Node B 复审 NODEB-RR-001..006；
首笔真实订单须 Node B PASS + 用户显式授权。
