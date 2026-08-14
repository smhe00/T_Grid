# Gate 1 / Claude Report — G1-T003

## Status
G1-T003 **Iteration 2 修复完成**（REV-G1T003-001 FIXED），交付 `REVIEW_READY / iteration=2`，等待架构师 Review。

## Iteration 2 修复内容

### REV-G1T003-001（P0）— Sequence 被多次观察，可泄漏裸异常并绕过成员验证
- 将 `_require_symbol_sequence`（先 `len` 后迭代）替换为 `_snapshot_symbol_sequence`：每个 sequence
  参数只通过**一次物化**（`[item for item in value]`，列表推导不走 C 级 length hint，`__len__` bomb
  天然免疫）得到私有 list snapshot；成员验证与底层调用使用**同一个 snapshot**，不再读取原对象、
  不再重复迭代、不再二次 `list()`。
- snapshot/iteration 期间的普通 `Exception` 转安全 `MarketDataValidationError`（只含参数名+固定约束）；
  项目异常在 except 块外抛出，`__cause__`/`__context__` 均为 None，不保留原异常对象/message。
- `KeyboardInterrupt`/`SystemExit`/`GeneratorExit` 在 snapshot/iteration 中原样传播，不转换不吞掉。
- 有状态/可变 Sequence 无法在验证与调用之间更换内容：底层只收到已验证的首次 snapshot。

## 证据
- 完整输出：`work/reports/tests/G1-T003-test-output.txt`（**325 项全部通过** + compileall exit 0 +
  AST 扫描 PASS + 单次快照 probe：len_bomb 不受影响、first-pass bomb → 干净 validation error 且底层
  调用 0、changing sequence 仅一次 pass、secret iterator 无泄漏）。
- `git diff --check -- :/T_Grid` exit 0；HEAD == 基线 `a2f5fa3`。

## 范围遵守
未 import xtquant、未连接 QMT、未订阅/下载行情、未读账号/真实数据、未安装依赖、未修改 Gate 0/1
已验收代码、未触碰父目录文件、未 commit/push、`live_trading_allowed` 保持 `false`。

## Recommendation
REVIEW_READY（等待 Desktop ChatGPT 独立 Review）。
