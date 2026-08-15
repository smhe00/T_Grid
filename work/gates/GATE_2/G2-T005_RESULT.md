# G2-T005 Result — PASS

## Status

`PASS`（Architect independent review，`2026-08-15T04:00:00+08:00`）。

G2-T005 仅验收离线、fail-closed 的 T-Lot 业务转换策略守卫：在 G2-T004 原子 writer 之上收窄
可执行动作集合，将 `action + expected_status` 纯函数解析为唯一转换边，并在任何数据库写入前
拒绝未批准组合。不授权 CRUD、人工授权动作、QMT、下单、撤单或 live trading。

## Scope Delivered

- `src/tgrid/persistence/t_lot_transition_policy.py`（新增）：
  - `T_LOT_ACTIONS` 闭集（五边：BUY_FILL_CONFIRMED / PREPARE_SELL / SELL_FILL_CONFIRMED /
    SUSPEND_T / RESUME_T），`_T_LOT_TRANSITIONS` 固定映射，event_type 完全由 action 派生。
  - `resolve_t_lot_transition` 纯函数：exact-str 校验 → 人工/no-op 动作拒绝 →
    七状态校验 → terminal 状态无出边 → 五边查表 → 拒绝 self-transition。
  - `apply_t_lot_transition`：先解析（未批准组合零 DB 写入），再委托 G2-T004 writer 恰好一次。
  - `KEEP_SUSPENDED` / `CONVERT_TO_STRATEGIC` / `MANUAL_EXIT` 显式不可执行（§16.1 需人工授权）。
- `tests/unit/test_t_lot_transition_policy.py`（新增，21 项）。
- 复用 `T_LOT_STATUSES`（migrations 单一来源）、`TLotWriterError` 层（单一异常根）。

## Independent Verification

- 完整回归：**638 tests OK**（含本任务 21 项）；compileall exit 0。
- AST 禁止能力扫描：25 个 `src` Python 文件，assert/QMT/order/cancel/download/subscribe 命中 0。
- 独立失败注入重放：未知 action、人工/no-op 动作、terminal 出边、非法 expected_status、
  action/status 错配、self-transition 均在任何 DB 写入前抛 `TLotTransitionRejectedError`；
  恶意 action/status dunder 隔离（exact-str 先于 membership）；writer 异常不吞不重试；
  合法五边各产生唯一 (to_status, event_type)。
- diff-check clean；无 QMT/账号/行情访问；`live_trading_allowed=false`。

## Deliberate Boundary（保持）

- 不实现人工授权动作的实际执行；不实现 SUSPENDED review 编排；不实现 OrderIntent/成交驱动规则。
- 不新增表/migration/审计文件；不修改既有 writer 语义与 schema 预期。

## Independent Architect Review

- 五边闭集与设计 §7（LIFO 卖出）、§16.1（SUSPENDED review）、§6（状态变化必须审计）一致。
- 解析先于写入满足 INV-010（fail closed）；单一异常根满足既有 persistence 分层。
- `REV` 无未决项；`G2-T005 PASS`。
