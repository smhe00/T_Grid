# Gate 1 / Claude Report — G1-T004

## Status
G1-T004 **Iteration 2 修复完成**（REV-G1T004-001 FIXED），交付 `REVIEW_READY / iteration=2`，等待架构师 Review。

## Iteration 2 修复内容

### REV-G1T004-001（P0）— FAILED 不等于已获得 sequence，stop 会用 None 调 unsubscribe
- `stop()` 的 cleanup 资格改为由**已验证并保存的有效 sequence id** 决定，不再仅由 FAILED 状态推断：
  在状态检查后、调用 `unsubscribe_quote` 前，若 `self._sequence_id is None` 则直接 return（不标记
  `_stop_attempted`），并只在持有有效 id 时用该 id 调用。
- 因此 subscribe 返回负数/错误类型、普通异常、BaseException 之后（sequence_id 均为 None），`stop()`
  不再调用 `unsubscribe_quote(None)`；重复 stop 仍不调用，状态保持 FAILED。
- 有效 sequence id（含 0 与正整数）的 ACTIVE stop 仍把精确 id 传入恰好一次；unsubscribe 失败或
  BaseException 后仍不重试。

## 证据
- 完整输出：`work/reports/tests/G1-T004-test-output.txt`（**371 项全部通过** + compileall exit 0 +
  AST 扫描 PASS + cleanup-eligibility probe：negative_return/subscribe_exception/keyboard_interrupt 均
  0 次 unsubscribe；valid_seq_0/7 各精确一次）。
- `git diff --check -- :/T_Grid` exit 0；HEAD == 基线 `6d6d30a`。

## 范围遵守
未 import xtquant、未连接 QMT、未真实订阅/接收行情、未读账号、未安装依赖、未修改 Gate 0/1 已验收代码、
未触碰父目录文件、未 commit/push、`live_trading_allowed` 保持 `false`。

## Recommendation
REVIEW_READY（等待 Desktop ChatGPT 独立 Review）。
