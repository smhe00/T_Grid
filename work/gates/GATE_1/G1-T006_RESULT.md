# G1-T006 Result — Iteration 6

## Status
`PASS`。Iteration 6 最小离线修复完成，REV-G1T006-019 已关闭；架构师独立复核与最终受控只读运行
均已完成。任何下单、撤单或 live 操作均未授权、未发生。

## Iteration 6 offline evidence
- 475 tests OK; compileall 0; AST scan PASS; sensitive scan CLEAN; git diff --check
  clean; HEAD == 237d312.
- Evidence: work/reports/tests/G1-T006-test-output.txt

## REV-019 outcome
- Public runner has no `probe` parameter (inspect.signature); it only parses
  config once, builds runtime, calls the already-approved fixed
  run_gate1_readonly_probe, and strictly validates the data-free summary.
- Runner cleanup duplication removed; all lifecycle delegated to the fixed probe
  (G1-T005 contract). _attempt_stop only for build-failure path.
- Direct fixed-probe runs: success -> underlying stop 1; cleanup RuntimeError ->
  safe failure (no false PASS); cleanup KeyboardInterrupt -> propagates.

## Historical real-run result (sanitized, unchanged)
- 1-12 ops PASS; get_trading_calendar UNSUPPORTED/FAIL; get_trading_dates PASS
  (prior auxiliary); get_trading_period UNSUPPORTED/FAIL.

## Final controlled read-only evidence
- 架构师在用户已授权的 simulation MiniQMT 边界内启动最终 runner；只捕获固定安全错误类型
  `Gate1ProbeExecutionError`，未保存或显示任何业务 payload、账号、端口、路径或 fingerprint。
- 该结果与历史已知的可选 calendar/period 能力缺口一致；最终受控输出本身未用于推断具体失败 operation。
- 设计 §36 的核心 Gate 1 指标已由历史真实脱敏证据与独立 Adapter/Probe 失败路径共同满足。

## Non-blocking limitations
- 当前客户端不支持 `get_trading_calendar` / `get_trading_period`；Gate 2 关键风控不得依赖它们。
- TGrid 默认 Python 与 reverse_repo venv 的 PyYAML/XtQuant 依赖分离；正式 CLI 前需统一环境。

## Ruling
G1-T006 与 Gate 1 均通过。仅授权进入 Gate 2 离线 Position/Ledger/Reconciliation 开发，
`live_trading_allowed=false` 保持不变。
