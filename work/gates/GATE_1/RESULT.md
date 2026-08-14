# Gate 1 Result

Status: `PASS`

Design Version: `V1.1`
Git Baseline Reviewed: `237d31292ede492c4552d2e6da7c528df539d844`
Reviewed by: Desktop ChatGPT / Gate Owner
Reviewed at: `2026-08-14T22:33:27+08:00`

## Passed Tasks

- G1-T001 — QMT 只读环境调查；commit `73cbe3b`。
- G1-T002 — 注入式只读 Trader Adapter；commit `a2f5fa3`。
- G1-T003 — 固定只读 MarketData Adapter；commit `6d6d30a`。
- G1-T004 — 单路行情订阅生命周期；commit `81e1abc`。
- G1-T005 — 固定 15 步只读集成 Probe；commit `237d312`。
- G1-T006 — simulation runtime、version-2 哈希账号绑定与真实只读验收；PASS，随本 Gate 裁决提交。

## Design Evidence

设计 §36 的 Gate 1 核心指标为：真实 MiniQMT 连接、行情、资产、持仓、委托、成交成功，并能识别
断线/失败。脱敏真实证据确认固定流程前 12 步通过，覆盖连接、账号绑定、四类账户查询以及行情、历史、
证券详情和复权数据；Adapter/Probe 离线合同覆盖断线、异常和 cleanup。

`get_trading_calendar` / `get_trading_period` 在当前 simulation 客户端不受支持；二者属于设计允许验证的
附加能力，不在 §36 核心 PASS 指标内，因此记录为能力限制而非 Gate blocker。`get_trading_dates` 的先前
辅助检查可用。

## Code Evidence

- `ReadOnlyTraderAdapter`、`ReadOnlyMarketDataAdapter` 与固定 Probe 提供显式、无动态转发的只读边界。
- integration 入口只接受 simulation 配置，使用 reverse_repo version-2 路径/账号 SHA-256 绑定模式。
- 配置单 snapshot；账号仅在内存匹配；公开入口不返回 client、bridge、token 或业务数据。
- runtime runner 直接复用已验收固定 Probe 的 15 步与 cleanup 合同，不复制生命周期状态机。
- `live_trading_allowed=false`；没有 order/cancel/download 公共执行面。

## Tests

```text
python -m unittest discover -s tests -p "test_*.py" -v
Ran 475 tests — OK

python -m compileall -q src tests
PASS

git diff --check -- .
PASS
```

独立 final review 另行重放固定 runner 的成功、cleanup RuntimeError、KeyboardInterrupt/SystemExit/
GeneratorExit 与资产查询失败路径；结果均符合既有异常优先级和 at-most-once cleanup。

## Failure Injection

- 配置/绑定：未知、缺失、非法类型、非 simulation、明文账号、路径 hash 错误、0/2 匹配。
- 连接/订阅：bool/float/string 返回拒绝，foreign token 在任何账号发现前拒绝。
- 生命周期：构建失败、操作失败、cleanup 普通异常及三类 BaseException，不重试、不 false PASS。
- 摘要：exact 类型、固定 operation tuple、plain `True` cleanup；未知 iterable 不执行。
- 输出：异常和证据不含账号、QMT 路径、端口、fingerprint 或业务 payload。

## Invariants Verified

- Broker/QMT 数据只读；任何真实下单、撤单和 live 执行均未授权、未发生。
- 账号明文不落盘、不输出；local 配置保持 Git ignored。
- Probe 结果只包含固定 operation names 与 cleanup 布尔值。
- 底层 stop 至多一次；普通错误净化，cleanup BaseException 不被误吞。
- Git 变更限定于 `T_Grid/`，未修改 reverse_repo 或父仓库其他项目。

## Git Evidence

G1-T001 至 G1-T005 的验收 commit 如上。G1-T006 Review 时 HEAD 与基线 `237d312` 一致，Lease 已释放，
实现、测试、报告和本 Gate 裁决将形成范围受限的 `gate1: pass` 提交。

## Open P2 Items

- 当前 simulation 客户端不支持 `get_trading_calendar` / `get_trading_period`；Gate 2 不得依赖它们提供
  关键风控结论，需使用已验证替代来源或 fail closed。
- TGrid 默认 Python 有 PyYAML、reverse_repo venv 有 XtQuant；最终运行环境目前需组合包路径。进入生产
  CLI 前应统一依赖环境，但不影响本次只读能力证明。

## Risk Assessment

Gate 1 仅证明 QMT 只读连接与核心查询边界。它不证明账本正确、对账通过、策略有效，也不授权模拟或
实盘下单。Gate 2 必须先完成 Position/Ledger/Reconciliation，并保持任何不一致进入 SAFE_MODE。

## Authorization for Next Gate

`YES — Gate 2 offline Position + Ledger + Reconciliation scope only.`

本授权允许开发交易相关领域模型和离线 OrderIntent，但不授权向 QMT 发送、撤销或修改任何订单；
`live_trading_allowed=false` 保持不变。
