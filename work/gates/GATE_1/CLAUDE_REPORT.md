# Gate 1 / Claude Report — G1-T006

## Status
G1-T006 **Iteration 6 最小离线修复完成**（REV-G1T006-019 FIXED），交付 `REVIEW_READY / iteration=6`。本轮为**纯离线**修复，未连接/查询/重跑任何 MiniQMT。

## Iteration 6 修复内容

### REV-G1T006-019（P0）— 删除 runner 复制的 cleanup helper，委托固定 Probe
- **删除**公开 runner 的任意 `probe` 参数（`inspect.signature` 断言无该参数）；真实入口只能调用既有
  `_default_probe` → 已验收 `run_gate1_readonly_probe`，调用者无法替换 Probe 伪造 15 步成功。
- **删除** runner 内自建 cleanup/异常优先级分支；固定 Probe 已负责所有操作后的 at-most-once cleanup、
  普通错误净化与 cleanup BaseException 传播（G1-T005 合同）。runner 只做：单次 config snapshot、
  runtime 构建、调用固定 Probe、严格验证 data-free summary、返回固定 literals。
- `_attempt_stop` 仅保留给“trader 已创建但 Probe 尚未建立”的**构建失败路径**，不再用于正常 Probe 生命周期。
- 测试改为用 fake trader/xtdata 直接运行固定 Probe：成功 → 底层 stop=1；cleanup RuntimeError → 安全
  cleanup failed（无 false PASS）；cleanup 三类 BaseException → 原样传播（无 false PASS）。

## 复用说明
直接复用固定 `run_gate1_readonly_probe` 的完整生命周期与 cleanup 合同，以及既有
`ReadOnlyTraderAdapter`/`ReadOnlyMarketDataAdapter`；未新增平行 QMT helper、runner、生命周期状态机。
复用为代码/模式复用，**不是交易执行授权**；`live_trading_allowed=false` 始终不变。

## 证据
- `work/reports/tests/G1-T006-test-output.txt`（**475 项离线测试** + compileall exit 0 + AST 扫描 PASS +
  敏感值扫描 CLEAN + Iteration 6 Failure Injection 摘要 + 脱敏历史结果）。
- `git diff --check -- :/T_Grid` exit 0；HEAD == 基线 `237d312`；`config/*.local.json` 未入版本控制。

## 范围遵守
未连接/查询/重跑 QMT；未修改任何已通过 Adapter/Probe；`live_trading_allowed=false`；无 order/cancel/
download/quote 订阅；未 commit/push。

## Recommendation
REVIEW_READY（等待架构师离线 Review；最终真实运行与 unsupported capability 裁决为架构师决定）。
