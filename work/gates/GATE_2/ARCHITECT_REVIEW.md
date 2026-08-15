# Gate 2 Architect Review

## Verdict

`GATE 2 PASS`（Architect independent review，`2026-08-15T04:00:00+08:00`）。

Gate 2（Position + Ledger + Reconciliation）六个任务全部离线验收通过，允许进入 Gate 3。

## Task-by-Task

- **G2-T001 PASS**（离线 Core Position Guard）：`PositionSnapshot` / `CorePositionGuard` 双卖保护
  （Core Floor → CanUseVolume → Reservation 优先级），`AvailableTQty = min(CanUse, OpenTLot) -
  ReservedSellQty`；Broker 必须等于 Core+Strategic+OpenT 分解，禁止静默修复。
- **G2-T002 PASS**（事务化 T-Lot Ledger schema，migration 2）：`t_lots` 表 + 禁止 DELETE 触发器，
  数据库级存储类约束，SUSPENDED review 字段（§16.1）。
- **G2-T003 PASS**（append-only Audit schema，migration 3）：`t_lot_audit_log` 表 + UPDATE/DELETE
  双禁止触发器，外键必须引用既有 t_lots。
- **G2-T004 PASS**（原子 T-Lot status transition writer）：`BEGIN IMMEDIATE` 单事务 CAS + audit，
  all-or-nothing；BaseException 覆盖 rollback；已有事务拒绝；两连接确定性竞争恰一成功。
- **G2-T005 PASS**（T-Lot 业务转换策略）：五边闭集，action+expected_status 纯解析，未批准组合
  零 DB 写入；人工/no-op 动作显式不可执行。
- **G2-T006 PASS**（离线 Position Reconciliation 决策引擎）：Core 唯一权威来自
  `SymbolConfig.core_qty`；broker<core → CORE_FLOOR_BREACH 优先；其它非零 delta →
  BROKER_POSITION_MISMATCH；相等 → MATCH。不重分类、不静默修复。

## Independent Verification Evidence

- 完整回归：`python -m unittest discover -s tests -p "test_*.py"` → **638 tests OK**
  （G2 模块专项 163 项：manager 48 + reconciliation 20 + t_lot_schema 32 + audit_schema 24 +
  writer 18 + transition_policy 21）。
- `python -m compileall -q src tests` → exit 0。
- AST 禁止能力扫描（`src` 25 个 Python 文件）：`assert` / `order_stock` / `cancel_order_stock` /
  `subscribe_quote` / `download_history_data` / `xtquant` import 命中 **0**。
- `git diff --check` clean；全部 Gate 2 测试输出归档于 `work/reports/tests/G2-T00*.txt`。
- 独立失败注入重放覆盖：CAS 冲突、缺 lot、duplicate audit_id、commit failure 回滚、两连接竞争、
  KI/SE/GE 传播 + rollback、rollback 失败连接失效、恶意 dunder/secret 隔离、t_unit 级 delta 不推断、
  broker<core 优先级。

## Invariants（§34 + V1.1）覆盖

- INV-001（Core Floor）：G2-T001 `CoreFloorViolation` + G2-T006 `CORE_FLOOR_BREACH` 双重独立实现。
- INV-002（T Capacity）：`max_t_lots` 容量约束在 Gate 2 由 schema/状态策略承载，Gate 3 策略接入。
- INV-005（Broker Authority）：G2-T001 分解等式 + G2-T006 对账。
- INV-006（No Silent Reconcile）：G2-T006 任何 delta → SAFE_MODE，不重分类。
- INV-011（No Assert Safety）：AST 扫描 assert 命中 0。
- INV-013（Idempotent Order Intent）：OrderIntent 由 Gate 4 承接，Gate 2 未实现（范围声明）。
- INV-015/016：Corporate Action HALT / 人工变化检测由 Gate 3 策略状态机接入，Gate 2 提供
  `CORPORATE_ACTION_HALT` 所需的 schema 与对账原语。

## Boundary Acknowledged

Gate 2 未实现也不授权：策略信号、OrderIntent/Reservation 持久化、Crash Recovery 编排、
SAFE_MODE 持久化、QMT 连接、下单/撤单、真实数据访问。`live_trading_allowed=false`。

## Next Gate

进入 **GATE 3 — 策略算法离线模拟**：ATR14 / VWAP20 / 统一复权口径 / Adaptive Grid / ACCUMULATE /
LIFO / Max T Lots / Volatility Halt / Event Block / Data Quality Guard / Corporate Action 指标
连续性测试，场景 A-D。仍禁止真实交易接口。
