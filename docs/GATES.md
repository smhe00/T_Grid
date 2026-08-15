# TGrid Gate 体系状态

> **Independent audit override — 2026-08-15:** 单 Agent（DSH）的实现/自测证据继续标记为 `SELF_CERTIFIED`；独立 Gate 审计状态以本文件与 `work/gates/` 下独立审计文件为准。
>
> **Gate 5：PASS。** Node A 独立审计已通过（`4c1cc8c`）。
>
> **Gate 5.5：PASS_PRELIVE。** Node B 在六轮 `CHANGES_REQUIRED` 修复循环后，于 Iteration 7 对实现 `8d51a471a9ae60338153b4d020b5d034c0f3d384` 完成独立 pre-live 验收。最终审计见 `work/gates/GATE_5_5/NODE_B_FINAL_PASS_PRELIVE_20260815.md`，QMT 行为参考固定为 `smhe00/reverse_repo@c9ecc701d9b1c47d6a8d03539b482368741204a3`。
>
> **重要边界：** `PASS_PRELIVE` 不是实盘授权。`live_trading_allowed=false` 保持；Gate 6 在用户显式授权首次极小资金验证前继续 `BLOCKED`，Gate 7 继续 `BLOCKED`。快捷指令 `f` 仅表示 fetch/audit，不构成交易授权。

| Gate | 内容 | 当前状态 | 说明 / 验收证据 |
|------|------|----------|-----------------|
| G0 | 项目骨架：配置/模型/风险异常/日志/CLI/Event Queue/SQLite | PASS | 历史 Gate 证据 `work/gates/GATE_0/` |
| G1 | QMT 只读接入：Trader/MarketData/QuoteSubscription Adapter + 探针 + Runtime Bridge | PASS | 只读边界；真实交易能力仍禁止 |
| G2 | Position + Ledger + Reconciliation | **PROVISIONAL / SELF_CERTIFIED** | G2-T005 已有独立历史验收；其余保留现有实现并按后续 Gate 风险点抽审 |
| G3 | 策略算法离线模拟 | **PROVISIONAL / SELF_CERTIFIED** | 保留现有实现与测试；按后续 Gate 风险点抽审 |
| G4 | Execution Dry Run：OrderIntent/Reservation、SimBroker、Executor、恢复 | **PROVISIONAL / SELF_CERTIFIED** | 核心执行不变量已被 Node-B pre-live 审计覆盖；历史实现保留 |
| G5 | Shadow 模式：REAL market/broker query + WOULD orders | **PASS**（Node A 独立审计） | 独立审计 PASS commit `4c1cc8c`；证据 `work/gates/GATE_5/` |
| G5.5 | Real Broker Adapter / pre-live capability | **PASS_PRELIVE**（Node B 独立审计） | 最终审计 `work/gates/GATE_5_5/NODE_B_FINAL_PASS_PRELIVE_20260815.md`；reviewed implementation `8d51a471...`；不代表实盘授权 |
| G6 | 极小真实资金验证 | **BLOCKED — AWAIT USER AUTHORIZATION** | Node B 已 PASS_PRELIVE，但仍要求用户显式授权；`live_trading_allowed=false` |
| G7 | V1 正式运行 | **BLOCKED** | Gate 6 完成并独立通过前禁止开始 |

## 当前测试证据

DSH 自证（`SELF_CERTIFIED`）：

```text
python -m unittest discover -s tests -p "test_*.py"   # 957 tests OK
python -m compileall -q src tests scripts              # exit 0
capability_scan                                         # PASS
真实 order/cancel 调用点                                # bridge 内 2，bridge 外 0
```

GitHub 未提供 reviewed implementation 的独立 CI status/checks，因此上述运行结果不转换为“独立执行测试”声明。Node B `PASS_PRELIVE` 基于独立代码、测试逻辑、控制面及 pinned `reverse_repo` reference-conformance 审计。

## Gate 5 修复摘要（AUD-R1-001..007）

- **AUD-R1-001**：`tgrid.shadow.marketdata` 显式 RAW/ADJUSTED 复权绑定（`dividend_type` 显式传给底层调用，bar 携带 basis 元数据，未知模式 fail closed）。
- **AUD-R1-002**：T+1 结算策略（总持仓 vs 可卖分离；同日买入锁定，次交易日释放）。
- **AUD-R1-003**：真实对账与影子假设 delta 分离；禁止静默重分类。
- **AUD-R1-004**：证据分类 `REAL_QMT_HISTORICAL_REPLAY + REAL_BROKER_SNAPSHOT`。
- **AUD-R1-005**：临时/敏感数据清理与报告脱敏。
- **AUD-R1-006**：控制面统一；DSH 自审标注 `SELF_CERTIFIED`；Gate 6/7 默认阻塞。
- **AUD-R1-007**：ExecutionEngine exact-type / finite-number hardening。

## Node B 最终接受范围

Node B pre-live 审计累计接受并冻结：

- BrokerPort live chain 与单一 XtQuant order/cancel bridge；
- native int order-id boundary；
- strict broker query（`None`/异常 bounded retry、empty-list legit success、unique match）；
- OrderIntent + Reservation before send、idempotency；
- UNKNOWN/duplicate/ambiguous fail closed 与 mandatory startup recovery；
- immutable callback → EventQueue，worker FAILED/STOPPING/STOPPED 即时阻断；
- kill-switch cancellation/query path；
- Core guard、exact-type、NaN/Inf hardening；
- durable daily exposure、pre-send reservation、restart reconstruction、trusted session rollover；
- production persistent DB / Migration 6；
- Gate-5.5 独立 `simulation/live` session parser，Gate-1 simulation-only parser 不变；
- production QMT lifecycle：construct → start → connect → exact bound normal security account → subscribe → recovery → runtime confirmation；
- SAFE_MODE 只能经引擎自身 authoritative broker/local reconciliation 清除，不接受 caller-supplied reconciliation results；
- disconnect transport recovery 不足以恢复订单能力；完整恢复要求 EventQueue RUNNING、connect、精确 account id/type/status、re-subscribe、exposure reconstruction、authoritative reconciliation、runtime reconfirm，最后才 clear latch；
- reconnect 使用 production session 解析出的精确 `SECURITY_ACCOUNT` + `ACCOUNT_STATUS_OK`；
- canonical state 不再使用自指 `git_head_commit`。

## 关键不变量（§34）

INV-001 Core Floor / INV-002 T Capacity / INV-003 Target Ceiling / INV-004 单方向单挂单 /
INV-005 Broker Authority / INV-006 禁止静默对账 / INV-007 禁止自动止损 / INV-008 禁止退出
Core/Strategic / INV-009 Live Default OFF / INV-010 Fail Closed / INV-011 禁止 assert 安全 /
INV-012 Reservation 先行 / INV-013 订单意图幂等 / INV-014 Callback 隔离 / INV-015 Corporate
Action HALT / INV-016 人工变化检测 / INV-017 数据新鲜度。

## 下一 Gate

1. **Audit Node A：PASS。**
2. **Audit Node B：PASS_PRELIVE。** 最终审计对象 implementation `8d51a471a9ae60338153b4d020b5d034c0f3d384`。
3. **Gate 6：等待用户显式授权。** 在此之前禁止任何真实 order/cancel；`f` 不构成授权。
4. Gate 6 完成后仍需独立验收，方可讨论 Gate 7。

详细当前控制面以 `work/control/WORKFLOW_STATE.yaml`、`work/control/CURRENT_TASK.md` 和最终 Node-B 审计文件为准。
