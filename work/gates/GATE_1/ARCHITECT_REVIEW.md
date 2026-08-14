# Gate 1 Architect Review

## G1-T005 / Iteration 2

Result: `G1-T005 PASS`

独立 402 项回归、compileall、AST 与主失败/cleanup 异常优先级矩阵通过。REV-G1T005-001 已关闭：
普通主失败不会被 cleanup 普通或 BaseException 覆盖，异常图无双方 secret；主 BaseException 始终优先。
固定 15 步、数据零观察和至多一次 cleanup 均成立，无真实 QMT/账号/行情访问。

本裁决仅通过离线集成探针；Gate 1 的真实 MiniQMT 验收仍需用户明确提供环境与只读授权。

## G1-T005 / Iteration 1

Result: `CHANGES_REQUIRED`

396 项回归和基础安全检查通过；额外组合 Failure Injection 证明普通主失败 + cleanup BaseException 时，
cleanup 会遮蔽固定主 operation，且 KeyboardInterrupt message 可泄漏。进入聚焦 Iteration 2，只修异常
优先级/净化矩阵。不得真实访问 QMT/账号/行情或增加交易能力。

## G1-T004 / Iteration 2

Result: `G1-T004 PASS`

独立 371 项回归、compileall、AST 与 lifecycle Failure Injection 通过。REV-G1T004-001 已关闭：
subscribe 未获得有效 sequence 的三类 FAILED 不再调用 unsubscribe；有效 id 0/正整数精确清理一次。
未导入/连接 XtQuant，未真实订阅或接收行情，未增加下载、查询、账号或交易能力。

本裁决仅通过离线单路订阅生命周期；Gate 1 尚未通过，`live_trading_allowed=false`。

## G1-T004 / Iteration 1

Result: `CHANGES_REQUIRED`

366 项回归和基础安全检查通过，但额外 lifecycle Failure Injection 证明 subscribe 未成功、sequence 为
None 时，FAILED 后 stop 仍调用 `unsubscribe_quote(None)`；测试因只匹配 id 42 而漏检。进入聚焦
Iteration 2，只修 cleanup 资格和对应测试。不得真实订阅/连接 QMT 或增加交易能力。

## G1-T003 / Iteration 2

Result: `G1-T003 PASS`

独立 325 项回归、compileall、AST 和 Sequence Failure Injection 通过。REV-G1T003-001 已关闭：
Sequence 仅物化一次，验证与底层调用使用同一 snapshot；len/iterator 异常不泄漏，changing sequence
不能在验证后替换内容。未导入/连接/查询 XtQuant，未增加订阅、下载、账号或交易能力。

本裁决仅通过离线 MarketData 查询边界；Gate 1 尚未通过，`live_trading_allowed=false`。

## G1-T003 / Iteration 1

Result: `CHANGES_REQUIRED`

320 项回归、compileall、AST 与常规异常图通过；额外 Sequence Failure Injection 证明参数被多次观察，
可泄漏 `__len__`/第二次迭代的裸异常 secret，或在验证后把空代码传给底层。进入聚焦 Iteration 2，
只修单次 snapshot 和验证异常边界。不得连接/查询真实 QMT 或增加订阅、下载、账号、交易能力。

## G1-T002 / Iteration 2

Result: `G1-T002 PASS`

独立 287 项回归、compileall、AST、异常图与 descriptor/frozen-callable Failure Injection 全部通过。
REV-G1T002-001/-002 已关闭；八个固定只读方法无动态逃逸，未导入或连接 XtQuant，未访问真实账号/行情，
危险 order/cancel 路径不可达，`live_trading_allowed=false`。

本裁决仅通过离线 Trader 只读 Adapter；Gate 1 尚未通过，下一任务仍限离线 MarketData 只读边界。

## G1-T002 / Iteration 1

Result: `CHANGES_REQUIRED`

280 项回归和只读 API 主路径通过，但 `from None` 后 `__context__` 仍持有带 secret 的原始异常；
constructor descriptor 也可泄漏裸异常，且 bound methods 未冻结。进入聚焦 Iteration 2。

不得连接 QMT、读取真实账号/行情或增加交易面；Gate 1 未通过。

## G1-T001 / Iteration 1

Result: `G1-T001 PASS`

默认解释器缺失 XtQuant 与父仓库 `.venv` 静态存在 XtQuant 的结论已独立复核；候选 trader、callback、
xtdata 只读 API 均可由源码 AST 确认。范围无生产代码/测试变更，无连接、导入、实例化、查询或敏感值
读取，Lease 已释放，`live_trading_allowed=false`。

artifact 实际 112 行；Claude 两份 handoff 报告中的 105 行笔误已由架构师校正。Gate 1 尚未通过，
下一任务只允许离线构建严格的依赖注入只读 Adapter，仍不得真实连接 QMT。
