# Gate 1 / Claude Report — G1-T005

## Status
G1-T005 **Iteration 2 修复完成**（REV-G1T005-001 FIXED），交付 `REVIEW_READY / iteration=2`，等待架构师 Review。

## Iteration 2 修复内容

### REV-G1T005-001（P0）— cleanup BaseException 覆盖普通主失败并泄漏 cleanup secret
- `_cleanup()` 改为**永不传播**：`trader.stop()` 无论抛普通 Exception 还是
  KeyboardInterrupt/SystemExit/GeneratorExit，都作为返回值返回（成功返回 None），由调用方决定优先级。
- 普通主 operation 失败分支：cleanup 任意失败（普通或 BaseException）统一折叠为安全
  `Gate1ProbeExecutionError("<operation> failed; cleanup failed")`（except 块外抛出，
  `__cause__`/`__context__` 均为 None，主/cleanup secret 均不泄漏）。
- 主 BaseException 分支：先 `_cleanup()` 一次（吞掉任何 cleanup 异常），再原样传播主 BaseException。
- 全部主 operation 成功 + 仅 cleanup 普通异常 → `"cleanup failed"`；全部主成功 + 仅 cleanup BaseException
  （无主失败）→ 原样传播该 cleanup BaseException。

## 证据
- 完整输出：`work/reports/tests/G1-T005-test-output.txt`（**402 项全部通过** + compileall exit 0 +
  AST 扫描 PASS + cleanup-priority probe：ordinary+cleanup-KI/SystemExit/GeneratorExit/ordinary 全部
  `"<op> failed; cleanup failed"` cause/context None stop 一次；all-success+cleanup-KI 原样传播）。
- `git diff --check -- :/T_Grid` exit 0；HEAD == 基线 `81e1abc`。

## 范围遵守
未 import xtquant、未连接 QMT、未读真实账号/行情、未安装依赖、未修改 adapters/**、未触碰父目录文件、
未 commit/push、`live_trading_allowed` 保持 `false`。

## Recommendation
REVIEW_READY（等待 Desktop ChatGPT 独立 Review）。
