# TGrid Gate 体系状态

> **Independent Audit Node A — 2026-08-15:** Gate 5 Shadow Mode 已独立通过。DSH 的单 Agent 自审仍标记为 `SELF_CERTIFIED`；本次独立验收以 `work/gates/GATE_5/NODE_A_FINAL_REVIEW_20260815.md` 为准。
>
> Gate 5.5 现仅授权实现 Real Broker Adapter / pre-live capability。首次真实 order/cancel 调用前必须停止并通过 Audit Node B。`live_trading_allowed=false` 继续绑定。

| Gate | 内容 | 当前状态 | 说明 / 验收证据 |
|------|------|----------|-----------------|
| G0 | 项目骨架：配置/模型/风险异常/日志/CLI/Event Queue/SQLite | PASS | 历史 Gate 证据 `work/gates/GATE_0/` |
| G1 | QMT 只读接入：Trader/MarketData/QuoteSubscription Adapter + 探针 + Runtime Bridge | PASS | 只读边界 |
| G2 | Position + Ledger + Reconciliation | **PROVISIONAL / SELF_CERTIFIED** | G2-T005 有独立历史验收；其余保留并后续抽审 |
| G3 | 策略算法离线模拟 | **PROVISIONAL / SELF_CERTIFIED** | 保留现有实现与测试；后续周期性独立抽审 |
| G4 | Execution Dry Run：OrderIntent/Reservation、SimBroker、Executor、恢复 | **PROVISIONAL / SELF_CERTIFIED** | 架构方向保留；exact-type hardening 已关闭 AUD-R1-007 |
| G5 | Shadow 模式：REAL market/broker query + WOULD orders | **PASS — INDEPENDENT NODE A** | `work/gates/GATE_5/NODE_A_FINAL_REVIEW_20260815.md`; accepted implementation `5a2e2fd32e21328badd1ceb2c92b973436c4c95a` |
| G5.5 | Real Broker Adapter / pre-live capability | **AUTHORIZED FOR IMPLEMENTATION ONLY** | 可写代码/测试；禁止真实 order/cancel；完成后必须 Node B |
| G6 | 极小真实资金验证 | **BLOCKED** | Node B PASS + 用户显式授权前禁止开始 |
| G7 | V1 正式运行 | **BLOCKED** | Gate 6 完成并独立通过前禁止开始 |

## Gate 5 当前验收证据

当前代码的 REAL_QMT 历史回放证据：

```text
work/reports/shadow/r4-10day-2026-08-14/
```

摘要：

- evidence class: `REAL_QMT_HISTORICAL_REPLAY + REAL_BROKER_SNAPSHOT`;
- 10 个交易日：2026-08-03 ~ 2026-08-14;
- 日线 `front` / ADJUSTED；5m `none` / RAW；
- 逐日 factor registry：10 bindings，`TRUSTED_LOCAL_FACTOR_MAP`；
- settlement: `T1`；
- Core authority: `SymbolConfig.core_qty`；
- 4 条 Shadow Orders（2 BUY + 2 SELL）；
- historical replay realized T PnL: 13.1；
- real reconciliation delta: 0；
- final shadow delta: 0。

旧 `LIVE_VERIFICATION.md` 的 +13.3 结果已标记 `SUPERSEDED`，不作为当前验收证据。

## 当前测试证据

DSH SELF_CERTIFIED：

```text
python -m unittest discover -s tests -p "test_*.py"   # 846 tests OK
python -m compileall -q src tests                      # exit 0
src AST scan (assert / order_stock / cancel_order_stock / xtquant import) # 0 hits for Gate-5 implementation
```

独立审计检查了实际 diff / 关键代码 / committed REAL_QMT evidence。审计运行环境无法联网 clone GitHub，且 implementation commit 没有 GitHub CI checks，因此 846 次测试的执行本身仍按 `SELF_CERTIFIED` 证据处理；这不改变 Gate-5 Shadow 语义的独立 PASS。

## Gate 5 已关闭的关键项

- 显式 RAW / ADJUSTED market-data basis；
- 逐日可信 adjustment factor，无缺日默认；
- 2:1 basis discontinuity 决策不变量测试；
- replay day D 只使用 `bar_date < D` 的 daily history，消除 look-ahead；
- T+1 total vs sellable 分离及跨日 carry-forward；
- real broker reconciliation 与 hypothetical shadow delta 分离；
- `SymbolConfig.core_qty` 作为实际运行时 Core 唯一来源；
- trusted strategy config / explicit settlement / SH-SZ session restriction；
- tracked `_tmp/` 清理与证据脱敏；
- `live_trading_allowed=false`，Gate-5 不包含真实交易能力。

## Gate 5.5 / Audit Node B 必须项

Gate 5.5 可实现 Real Broker Adapter，但不得调用真实 order/cancel。Node B 至少审计：

- live default OFF + 第二次 runtime confirmation；
- symbol allowlist；
- per-order / per-day qty/cash hard limits；
- kill switch；
- callback -> Event Queue isolation；
- OrderIntent + Reservation before send；
- partial fill；
- timeout -> cancel -> re-query，不把 cancel ack 当成 zero fill；
- order/trade reconciliation + restart recovery；
- exact-type fail-closed validation；
- **NODEB-P0-001**：legacy reconciliation `core_qty` mismatch guard 必须真正接入 loader-to-runner 路径。

`NODEB-P0-001` 当前表现：loader 会先丢弃 optional legacy `core_qty`，使后续 `_check_core_authority()` 无法看到 mismatch。该问题不影响 Gate 5 当前 Shadow 运行时使用 `SymbolConfig.core_qty` 的单一 Core，但在任何 live capability 获准前必须修复。

## 下一独立审计节点

**AUDIT NODE B — BEFORE FIRST REAL ORDER**

DSH 完成 Gate 5.5 后必须设置 `AUDIT_READY_PRELIVE` 并停止。Gate 6 只有在：

```text
Audit Node B = PASS
AND
用户显式授权 = YES
```

后才可开始。
