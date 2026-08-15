# TGrid Gate 体系状态

| Gate | 内容 | 状态 | 验收证据 |
|------|------|------|----------|
| G0 | 项目骨架：配置/模型/风险异常/日志/CLI/Event Queue/SQLite | PASS | `work/gates/GATE_0/` |
| G1 | QMT 只读接入：Trader/MarketData/QuoteSubscription Adapter + 探针 + Runtime Bridge | PASS（离线） | `work/gates/GATE_1/` |
| G2 | Position + Ledger + Reconciliation：CorePositionGuard / t_lots / audit / 原子 writer / 转换策略 / 对账引擎 | PASS（离线） | `work/gates/GATE_2/ARCHITECT_REVIEW.md` |
| G3 | 策略算法离线模拟：VWAP20/EMA20/ATR14、自适应网格、复权口径、数据质量、波动/事件暂停、ACCUMULATE 引擎（场景 A-D） | PASS（离线） | `work/gates/GATE_3/ARCHITECT_REVIEW.md` |
| G4 | Execution Dry Run：OrderIntent/Reservation、SimBroker、Executor、崩溃恢复、DryRun 全链路 PnL（§39 失败矩阵） | PASS（离线） | `work/gates/GATE_4/ARCHITECT_REVIEW.md` |
| G5 | Shadow 模式：WOULD_BUY/WOULD_SELL、Signal Log、对账、Daily Report（§40 四交付物） | PASS（离线代码 + 人工运行手册） | `work/gates/GATE_5/ARCHITECT_REVIEW.md` |
| G6 | 极小真实资金验证（1 symbol / 1 t_unit / max_t_lots=1） | **用户人工执行** | `work/gates/GATE_6/GATE67_MANUAL_CHECKLIST.md` |
| G7 | V1 正式运行（多 symbol / ACCUMULATE only / max_t_lots≤2） | **用户人工执行** | 同上 |

## 当前测试基线

```text
python -m unittest discover -s tests -p "test_*.py"   # 794 tests OK
python -m compileall -q src tests                      # exit 0
src AST 扫描（assert / order_stock / cancel_order_stock / xtquant import）: 0 命中
```

## 关键不变量（§34）

INV-001 Core Floor / INV-002 T Capacity / INV-003 Target Ceiling / INV-004 单方向单挂单 /
INV-005 Broker Authority / INV-006 禁止静默对账 / INV-007 禁止自动止损 / INV-008 禁止退出
Core/Strategic / INV-009 Live Default OFF / INV-010 Fail Closed / INV-011 禁止 assert 安全 /
INV-012 Reservation 先行 / INV-013 订单意图幂等 / INV-014 Callback 隔离 / INV-015 Corporate
Action HALT / INV-016 人工变化检测 / INV-017 数据新鲜度。

全部以自动化测试承载（`tests/unit/`）。
