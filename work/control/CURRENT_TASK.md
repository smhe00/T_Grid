# Current Task — Gate 5.5 PASS_PRELIVE + Gate 6 Simulation Verification + reverse_repo 状态机移植

## Owner

`DSH (DeepSeek Harness)` — single programming Agent, implementation + self-review allowed.

Self-review must be labelled `SELF_CERTIFIED`; it is not an independent pre-live authorization.

## Status

`NODE_B PASS_PRELIVE` — Gate 5.5 pre-live capability independently accepted (`e252847`).
Gate 6 **simulation** verification executed (user-authorized, QMT sim client, 2026-08-15 21:29).
reverse_repo 状态机 + 形式验证器移植完成（用户 2026-08-15 显式授权；SELF_CERTIFIED，**新能力**）。
Real-money Gate 6/7 remain BLOCKED until explicit user authorization.

## reverse_repo 状态机 + 形式验证器移植（SELF_CERTIFIED — 2026-08-15）

用户显式授权移植 reverse_repo 的完整状态机 + 形式验证器（pinned `c9ecc70`）：

1. `src/tgrid/execution/statemachine.py` — TGrid 单状态机（14 状态）+ SafetyFacts
   （9 布尔不变量）+ `advance()` + `verify_state_machines()`；
2. `src/tgrid/execution/execution_journal.py` — ExecutionJournal（schema v2、
   strategy+trade_date 三元校验、temp+fsync+os.replace 原子写、历史≤500、
   `journal_matches_verification` 绑定 transition_spec + execution_source 哈希）；
3. `src/tgrid/execution/execution_mutex.py` — ExecutionMutex 跨进程执行互斥
   （msvcrt/flock、超时轮询、pid 标记、进程退出 OS 自动释放）；
   `build_live_stack(execution_lock_path=...)` 可选开启，
   `LiveStack.activate()` 先于任何状态变更获取锁（争用 fail-closed），
   `release_execution_lock()` 幂等释放；
4. `ExecutionEngine.recover_unknown_submission()` — SUBMIT_UNKNOWN 后按
   **持久化 intent remark 反查全部 broker 订单**：唯一匹配 + 身份一致 →
   RECOVERED_ACTIVE/CANCEL_PENDING/TERMINAL；**0 匹配 → RECOVERED_NO_MATCH →
   SAFE_HALT 禁自动重发**；查询失败/多匹配/身份不一致/未知状态 →
   RECOVERY_AMBIGUOUS → SAFE_HALT + SAFE_MODE；
5. **journal 驱动崩溃恢复** — `LiveStack.activate()` 按加载机器状态选择启动事件：
   全新 journal → BEGIN→PREFLIGHT_OK；崩溃/中断（PREFLIGHT..RECONCILE）→
   **RESTART→RECOVERY**；终态 journal（DONE/SKIPPED/SAFE_HALT）→
   `LiveBootstrapError` fail-closed。启动对账后按 reconcile 结果驱动机器出口
   （RECOVERY_ACTIVE/CANCEL_PENDING/TERMINAL/CLEAR）；
6. `ExecutionEngine` 成对接入（machine+journal 必须同时提供；send/poll/timeout
   驱动机器事件，转移先于外部副作用原子落盘）；
7. `LiveStack`（`journal_path` 可选开启）— `activate()` 驱动
   BEGIN→PREFLIGHT_OK→RECOVERY_CLEAR/AMBIGUOUS，并在 BEGIN 前
   **fail-closed 校验 journal 绑定**（已绑定哈希失配 → `LiveBootstrapError`，
   绝不静默重绑；显式 `bind_machine_verification()` 为唯一恢复路径）。

验证产物：39 可达抽象状态 / 115 转移 / 0 不可达 / 0 无终态路径 / 0 不变量违例；
`transition_spec_sha256=7d9959dd...`、`execution_source_sha256=92118bb1...`
（7 个执行源文件真实内容绑定）。
回归 **998 tests OK**（+18：ExecutionMutex 6、remark 反查恢复 9、锁串行化 1、
崩溃恢复重启 1、终态 journal 拒绝 1）；compileall exit 0。

**诚实声明**：状态机移植为**新能力**，未经 Audit Node B 复审，不取代 PASS_PRELIVE
（`e252847`）；首笔真实订单前建议纳入 Node B 复审。

## Completion Record — Node B PASS_PRELIVE (2026-08-15)

- **NODEB-RR6-001/002/003** all PASS; Node B final verdict `PASS_PRELIVE`
  (`work/gates/GATE_5_5/NODE_B_FINAL_PASS_PRELIVE_20260815.md`).
- `PASS_PRELIVE` = adapter + safety boundary accepted for the next gated phase;
  NOT authorization to place a real order.

## Gate 6 Simulation Verification (SELF_CERTIFIED — 2026-08-15 21:29)

User explicitly authorized Gate 6 on the QMT **simulation** trading client
(already started). `scripts/gate6_sim_live.py` executed the full pre-live loop:

1. production `build_live_session(simulation)` — connect/discover/subscribe OK,
   bridge constants SECURITY_ACCOUNT=2 / ACCOUNT_STATUS_OK=0;
2. mandatory recovery + runtime confirmation passed;
3. ONE tiny BUY: 510300.SH qty=100 @ 4.726 (caps: 200 qty / 5000 cash / allowlist /
   exposure gate / EventQueue health);
4. real `order_stock` returned native int broker id `1098907651`;
5. polled to **REJECTED** (sim client rejected the order — Saturday, outside
   trading hours); broker reconcile REJECTED / 0 filled; exposure 472.6 booked
   pre-send;
6. evidence: `work/reports/gate6-sim/gate6-sim-2026-08-15.json` (sanitized).

**Honest limitation**: the sim client rejected the order outside trading hours,
so the FILL and CANCEL paths were NOT exercised. A trading-hours rerun is
required to complete Gate 6 simulation verification (real fill, partial fill,
cancel+re-query, T+1/can_use checks).

## Remaining / BLOCKED

- Real-money Gate 6/7: BLOCKED until explicit user authorization (`f` is never
  trading authorization). `live_trading_allowed=false` remains mandatory.
- reverse_repo 状态机移植为**新能力**（SELF_CERTIFIED）：建议首笔真实订单前纳入
  Audit Node B 复审；复审前不视为 PASS_PRELIVE 的延伸。
- Monitor job keeps polling `tgrid-github/main` for any further audit pushes.

## Source of Authorization

Read and comply with:

```text
work/gates/GATE_5/NODE_A_FINAL_REVIEW_20260815.md
```

Audit target:

```text
df1cbb53471d8f765c89c4bc644323d5839d0dd6
```

Accepted Gate-5 implementation commit:

```text
5a2e2fd32e21328badd1ceb2c92b973436c4c95a
```

## Objective

Implement Gate 5.5: the real broker execution adapter and its pre-live safety boundary, while **never invoking a real order or real cancel** during this task.

Target architecture:

```text
ExecutionEngine
    -> LiveBrokerAdapter
    -> XtQuantTrader
```

The adapter may contain the broker capability needed for later live execution, but this task ends before the first real invocation.

## Mandatory Requirements

1. `live_trading` defaults false and cannot be enabled implicitly.
2. A second explicit runtime confirmation is required in addition to configuration before broker execution is permitted.
3. Explicit symbol allowlist.
4. Hard per-order quantity limit.
5. Hard per-order and/or per-day cash exposure limit.
6. Kill switch / emergency disable path.
7. Broker callbacks may only enqueue events; callbacks must not directly mutate T-Lots, position state, reservations, DB strategy state, or issue new orders.
8. Reuse Gate-4 idempotent OrderIntent + Reservation-before-send semantics.
9. Partial fills must be modeled explicitly.
10. Timeout path must be `cancel request -> broker re-query -> reconcile`; cancellation acknowledgement must never be interpreted as proof of zero fill.
11. Order/trade reconciliation and restart/crash recovery must be deterministic and fail closed.
12. Exact-type validation must occur before arithmetic or broker calls.
13. No force push / history rewrite.
14. Do not commit account identifiers, balances, holdings, ports, userdata paths, secrets or local runtime configs.

## Mandatory Carry-Forward Fix — NODEB-P0-001

Fix the legacy reconciliation Core mismatch guard before Node B review.

Current issue: `_load_reconciliation_state()` discards an optional legacy `core_qty` before `_check_core_authority()` can inspect it. Therefore a legacy file containing a Core different from `SymbolConfig.core_qty` is silently ignored instead of failing closed.

Required resolution:

- either reject `core_qty` as an unexpected reconciliation-state field; or
- preserve it, require exact equality with `SymbolConfig.core_qty`, then discard it.

Add a loader-to-runner test proving a mismatched legacy Core fails closed before any broker execution capability can be invoked.

## Forbidden During Gate 5.5

- no real order invocation;
- no real cancel invocation;
- no enabling `live_trading_allowed` in canonical state;
- no Gate 6 tiny-capital run;
- no production/live soak claim;
- no bypass of Node B.

## Required Self-Certified Evidence

- full unit regression;
- compileall;
- capability scan identifying every real broker order/cancel call site introduced by Gate 5.5;
- tests for double enable/confirmation;
- allowlist and hard-limit tests;
- callback isolation tests;
- idempotency/reservation tests against the live adapter boundary using mocks/fakes only;
- partial fill / cancel / re-query / uncertain-state tests;
- restart/recovery tests;
- NODEB-P0-001 integration test;
- proof that no real order/cancel was invoked while producing the evidence.

## Stop / Handoff — Audit Node B

When implementation is complete:

1. push normally to GitHub `main`;
2. set canonical state to `AUDIT_READY_PRELIVE`;
3. record exact implementation commit(s), test counts and capability call sites;
4. authorize only `AUDIT_NODE_B_BEFORE_FIRST_REAL_ORDER`;
5. STOP.

The first real order is prohibited until:

```text
Audit Node B = PASS
AND
explicit user authorization = YES
```
