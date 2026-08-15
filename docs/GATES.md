# TGrid Gate 体系状态

> **Independent audit override — 2026-08-15:** 最新单 Agent（DSH）提交保留，但其 Gate 2–5
> 的 `Architect Review` 属于 `SELF_CERTIFIED`，不等同于独立验收。独立阶段审计已将 Gate 5
> 调整为 `CHANGES_REQUIRED`，Gate 6/7 在后续独立审计前保持 `BLOCKED`。详细要求见
> `work/gates/GATE_5/INDEPENDENT_AUDIT_20260815.md`。
>
> **2026-08-15 NODEA-R4（Iteration 5）修复后状态：** Gate 5 修复（AUD-R1-001..007 +
> NODEA-001..006 + NODEA-R3-001..004 + NODEA-R4-001..004）已完成并自证
> （`SELF_CERTIFIED`），**独立审计 NODE A PASS**（GitHub main commit `4c1cc8c`）。
> Gate 5.5 Live Broker Adapter（pre-live 能力）实现完成（`SELF_CERTIFIED`）。
> **独立审计 NODE B 四轮复审（`0f8e0a19`、`cb7aeb6`、`3b0d53f`、`66264f1`）
> 均返回 CHANGES_REQUIRED；Iteration 2..5（NODEB-001..007、NODEB-I2-001..006、
> NODEB-RR-001..006、NODEB-RR4-001..005，参考基线 reverse_repo `c9ecc70`）
> 修复已完成（SELF_CERTIFIED）**，状态 `AUDIT_READY_PRELIVE`，等待 NODE B
> 复审后才允许首次真实订单。证据见 `work/gates/GATE_5_5/CLAUDE_REPORT.md`。

| Gate | 内容 | 当前状态 | 说明 / 验收证据 |
|------|------|----------|-----------------|
| G0 | 项目骨架：配置/模型/风险异常/日志/CLI/Event Queue/SQLite | PASS | 历史 Gate 证据 `work/gates/GATE_0/` |
| G1 | QMT 只读接入：Trader/MarketData/QuoteSubscription Adapter + 探针 + Runtime Bridge | PASS | 只读边界；真实交易能力仍禁止 |
| G2 | Position + Ledger + Reconciliation | **PROVISIONAL / SELF_CERTIFIED** | G2-T005 已有独立历史验收；G2-T006 与汇总 Gate 2 由 DSH self-certify，保留实现，后续抽审 |
| G3 | 策略算法离线模拟 | **PROVISIONAL / SELF_CERTIFIED** | 保留现有实现与测试；等待周期性独立抽审 |
| G4 | Execution Dry Run：OrderIntent/Reservation、SimBroker、Executor、恢复 | **PROVISIONAL / SELF_CERTIFIED** | 架构方向保留；AUD-R1-007 exact-type hardening 已在本次修复关闭 |
| G5 | Shadow 模式：REAL market/broker query + WOULD orders | **PASS**（NODE A 独立审计） | 独立审计 PASS commit `4c1cc8c`；证据 `work/gates/GATE_5/` |
| G5.5 | Real Broker Adapter / pre-live capability | **IMPLEMENTED / AUDIT_READY_PRELIVE (IT5)** | NODE B 复审 `66264f1` CHANGES_REQUIRED → NODEB-RR4-001..005 已修复（SELF_CERTIFIED）；证据 `work/gates/GATE_5_5/CLAUDE_REPORT.md`；NODE B 复审 PASS 前禁止首次真实订单 |
| G6 | 极小真实资金验证 | **BLOCKED** | Audit Node B 独立 PASS + 用户显式授权前禁止开始 |
| G7 | V1 正式运行 | **BLOCKED** | Gate 6 完成并独立通过前禁止开始 |

## 当前测试证据（SELF_CERTIFIED）

```text
python -m unittest discover -s tests -p "test_*.py"   # 950 tests OK
python -m compileall -q src tests                      # exit 0
src AST 扫描（assert / xtquant import / 桥外 order_stock/cancel_order_stock）: 0 命中
capability_scan: 真实 order/cancel 调用点仅限 xtquant_bridge.py（桥内 2、桥外 0）
```

这些是 **SELF_CERTIFIED evidence**，不自动构成 independent Gate PASS。

## Gate 5 修复摘要（AUD-R1-001..007）

- **AUD-R1-001**：`tgrid.shadow.marketdata` 显式 RAW/ADJUSTED 复权绑定（`dividend_type`
  显式传给底层调用，bar 携带 basis 元数据，未知模式 fail closed，测试断言精确参数）。
- **AUD-R1-002**：`tgrid.shadow.settlement` T+1 结算策略（总持仓 vs 可卖分离；同日买入
  锁定，次交易日释放；T0/T1 显式规则；同场反弹不可卖 / 次日可卖测试）。
- **AUD-R1-003**：真实对账（real broker vs Core+Strategic+OpenT）与影子假设 delta 分离；
  `reconciliation` + `shadow_delta` 两组独立报告，禁止静默重分类。
- **AUD-R1-004**：证据分类 `REAL_QMT_HISTORICAL_REPLAY + REAL_BROKER_SNAPSHOT`，
  运行器输出 `evidence.json`。
- **AUD-R1-005**：`_tmp/` 清理 + .gitignore 完善（`*.local.json` 全局排除）；报告脱敏
  （路径/端口/资金/持仓不提交）。
- **AUD-R1-006**：控制面统一；DSH 自审标注 `SELF_CERTIFIED`；Gate 6/7 `BLOCKED`。
- **AUD-R1-007**：`ExecutionEngine` exact-type 校验先于算术（拒绝 untrusted
  int()/float() 强制转换）+ 测试。

## 关键不变量（§34）

INV-001 Core Floor / INV-002 T Capacity / INV-003 Target Ceiling / INV-004 单方向单挂单 /
INV-005 Broker Authority / INV-006 禁止静默对账 / INV-007 禁止自动止损 / INV-008 禁止退出
Core/Strategic / INV-009 Live Default OFF / INV-010 Fail Closed / INV-011 禁止 assert 安全 /
INV-012 Reservation 先行 / INV-013 订单意图幂等 / INV-014 Callback 隔离 / INV-015 Corporate
Action HALT / INV-016 人工变化检测 / INV-017 数据新鲜度。

全部以自动化测试承载（`tests/unit/`）。

## 下一独立审计节点

1. **AUDIT NODE A**：**已 PASS**（GitHub main commit `4c1cc8c`，审计对象 `df1cbb5`，接受实现 `5a2e2fd`）。
2. **AUDIT NODE B**：Gate 5.5 LiveBrokerAdapter 实现完成；NODE B 四轮独立复审
   （`0f8e0a19` NODEB-001..007、`cb7aeb6` NODEB-I2-001..006、`3b0d53f`
   NODEB-RR-001..006、`66264f1` NODEB-RR4-001..005；参考基线 reverse_repo
   pinned `c9ecc70`）均返回 `CHANGES_REQUIRED`，修复已完成
   （`AUDIT_READY_PRELIVE`，`SELF_CERTIFIED`）。在首次真实订单调用前必须
   独立复审 PASS，并由用户显式授权。授权令牌 `AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`。

详细执行清单以 `work/control/CURRENT_TASK.md` 和
`work/gates/GATE_5/INDEPENDENT_AUDIT_20260815.md` 为准。
