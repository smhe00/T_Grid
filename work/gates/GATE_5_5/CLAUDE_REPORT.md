# Gate 5.5 / Claude Report — Live Broker Adapter (Pre-Live Only)

## Status

`AUDIT_READY_PRELIVE (ITERATION 5)` — Node B Iteration-4 复审（`66264f1`，
`work/gates/GATE_5_5/NODE_B_REVIEW_ITER4_REFERENCE_20260815.md`）判定
`CHANGES_REQUIRED`；**NODEB-RR4-001..005 已全部修复（SELF_CERTIFIED）**，
等待 Audit Node B 复审。**本任务未调用任何真实 order/cancel；
`live_trading_allowed=false` 保持。**

授权来源：Gate 5 Node A PASS（`4c1cc8c`）+ Node B Iteration-4 授权仅限修复
NODEB-RR4-001..005（final production-glue correction）。

参考实现（QMT 行为基线）：`https://github.com/smhe00/reverse_repo`
pinned commit `c9ecc701d9b1c47d6a8d03539b482368741204a3`。

## NODEB-RR4-001..005 Closure（SELF_CERTIFIED）

| # | 级别 | 修复 |
|---|------|------|
| RR4-001 | P0 | `build_live_session()` 改为**真实生产路径**：消费已校验 `RootConfig`（`global.live_trading` 默认 OFF，缺失/false 保持执行禁用），不再复用 simulation-only Gate-1 parser 作为 live parser；严格按参考生命周期顺序：construct trader → `start` → `connect`（精确 int 成功）→ strict account 发现 → 唯一 bound normal 账号 → `subscribe`（精确 int 成功）；错误 env/path/account、非零/错误类型 connect/subscribe 结果、零/多账号匹配 → 在 order-capable stack 就绪前失败；新增 positive production-shaped fake 测试（live_trading=true 全流程成功） |
| RR4-002 | P0 | SAFE_MODE 释放改为 reconciliation 驱动：`clear_safe_mode_after_reconciliation(results)` 仅在所有 outcome 已解析（无 UNMATCHED/INTENT_ONLY/UNKNOWN）时清除，裸 `clear_safe_mode` 保留为 test-internal hook；broker 断开恢复改为权威 `reconnect()`：EventQueue RUNNING + verified connect（精确 int 0）+ account-status 验证，disconnect latch（`_disconnected`）无法被裸 health flip 清除；测试证明裸翻转不能恢复订单能力 |
| RR4-003 | P0 | 日敞口重建从**持久 OrderIntent.created_at** join broker orders（broker id / client key / remark），绝不依赖原始 QMT `order_time` 格式化；无法安全分日的 managed 单**保守计入**（绝不因时间戳格式未知而静默跳过）；FI：原生 int 风格 order_time、非 ISO 字符串、空值、终态订单、broker/local 匹配 intents 证明重启无少算 |
| RR4-004 | P1 | `daily_exposure` 进入正常 schema 迁移生命周期（Migration 6 + no-delete trigger）；`SqliteExposureStore` 要求已迁移表（拒绝 raw/:memory: 连接）；生产工厂从 validated config 打开数据库（不接受任意 caller connection） |
| RR4-005 | P1 | `git_head_commit` 记录**已推送的元数据/交接 HEAD**（与 `implementation_commit` 明确区分）；state/task/docs/report 一致 |

## Evidence

- 回归：`python -m unittest discover -s tests -p "test_*.py"` → **950 tests OK**（较 943 新增 7：positive/negative production session 生命周期、connect/subscribe exact-result FI、global.live_trading 双确认（默认 false + 显式 true）、SAFE_MODE 无裸清除、断开无裸重连、exposure 原生 int order_time FI、持久 DB/迁移生命周期）。
- `python -m compileall -q src tests scripts` → exit 0。
- capability 扫描：真实 `order_stock`/`cancel_order_stock` 调用点 **桥内 2 处（白名单）、桥外 0 处**；`RESULT: PASS`。
- 测试文件：`test_live_bootstrap.py`（session 生命周期 / SAFE_MODE / disconnect / exposure FI / 迁移扩展）、`test_xtquant_bridge.py`（strict-query 保持）、迁移测试（`test_t_lot_schema` / `test_t_lot_audit_schema` / `test_persistence` / `test_cli` 版本断言同步为 MAX_SCHEMA_VERSION=6）。
- 既有 AST 扫描（assert / xtquant import / 桥外 order call）保持 PASS。

## Boundary

- 本任务**绝不 invoke** 真实 order/cancel；所有 broker 调用经注入 fake/bridge。
- 未实现/未授权：真实资金运行、Gate 6、live-soak。
- `live_trading_allowed=false`；Gate 6/7 BLOCKED。
- 授权令牌：`AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`。

## Recommendation

`AUDIT_READY_PRELIVE`（Iteration 5）——等待 Audit Node B 复审 NODEB-RR4-001..005；
首笔真实订单须 Node B PASS + 用户显式授权。
