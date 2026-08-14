# Current Task — G1-T006

## Task Name

真实 MiniQMT Gate 1 只读验收：测试版哈希账号绑定

## Authorization

用户已于 2026-08-14 明确授权：`授权 G1-T006 真实 MiniQMT 只读验收；禁止任何下单和撤单。`

本轮只授权 **simulation MiniQMT**。`live_trading_allowed=false` 始终不变；实盘账号、下单、撤单、
改单、行情下载和 quote callback 订阅均不在范围内。

## Iteration 6 State

`CHANGES_REQUIRED / owner=claude / iteration=6`。本轮仅做一个最小离线修复，**禁止再次连接或
查询任何 MiniQMT**。真实环境第二次运行必须等待架构师完成离线 Review 后另行显式授权。

Iteration 5 已关闭配置 snapshot 与 summary 迭代问题，但 runner 复制的 cleanup helper 会吞掉 stop 异常并
错误返回成功。Iteration 6 只修复 REV-G1T006-019：删除任意 probe 注入和重复 cleanup，完全复用已验收
的固定 Probe 生命周期；不得把历史真实结果改写为 PASS。

用户最新架构指令：**尽量复用 `D:/gitee/miniQMT/reverse_repo` 及 TGrid 已有实现**。本轮不得新增平行的
QMT 配置、账号绑定、生命周期或 probe 抽象；优先复用已有 Adapter/Probe 的 cleanup 和异常优先级语义。
复用交易相关代码不等于授权执行交易；当前仍禁止任何下单、撤单和 live 操作。

QMT 接口、哈希绑定和生命周期模式优先从 `D:/gitee/miniQMT/reverse_repo` 学习，特别是
`scripts/repo_execution_core.py::select_bound_account` 及其测试；不得导入父目录
`miniqmt_reverse_repo` 交易模块，不得访问或回退到未在本地配置中声明的 allowlist。

## Objective

使用 `D:/gitee/miniQMT/reverse_repo` 已有的本地 runtime 配置和 SHA-256 账号绑定，在不保存、打印或
传递明文账号 ID 的前提下：

1. 新增一个最小、显式、无动态转发的 XtQuant runtime bridge；
2. 在内存中把唯一正常证券账户与既有 fingerprint 匹配；
3. 将 bridge 注入已通过的 `ReadOnlyTraderAdapter` / `ReadOnlyMarketDataAdapter`；
4. 只通过 `run_gate1_readonly_probe` 执行固定只读验收；
5. 保存完全脱敏的 PASS/FAIL 与测试证据，不保存任何账号、资产、持仓、委托、成交或行情原值。

## Local Inputs

本地忽略文件：`config/gate1_qmt.local.json`。该文件只包含 simulation 环境、reverse_repo 本地配置
路径、哈希绑定路径、公开标的与交易所，不含账号 ID。已通过架构师 preflight：

- runtime 与 binding 文件存在且均被 reverse_repo Git 忽略；
- simulation `userdata_mini` 路径存在；
- 路径 SHA-256 与绑定一致；
- 绑定恰好包含一个 `SECURITY_ACCOUNT`，且不保存明文账号；
- `XtMiniQmt` 正在运行；TGrid HEAD 为 `237d312...`；Lease 空闲。

## Required Implementation

新增 `tgrid.integrations.qmt_gate1_runtime`，要求：

- 仅在该 integration 模块中延迟导入 XtQuant；不得改变核心模块的离线导入性质。
- 严格解析本地 JSON、reverse_repo runtime JSON 与 version-2 hashed binding；拒绝未知/缺失字段、
  非 simulation 环境、非 `SECURITY_ACCOUNT`、明文 `account_id`、路径不存在、路径 fingerprint 不符、
  绑定数量不是 1。
- Trader bridge 的公开 surface 只能包含已批准 Adapter 所需的八个 callable：`start`、`connect`、
  `subscribe`、四个 `query_stock_*`、`stop`。禁止通用代理和底层 client 暴露。
- `subscribe` 阶段可在已连接后精确调用一次 `query_account_infos` 与一次 `query_account_status`，只在
  内存中选择 fingerprint 匹配且状态正常的唯一证券账户；0 个或多个匹配均 fail closed。
- 传给 Probe 的 account 必须是不含账号数据的 opaque token；bridge 内部将 token 映射为内存中的
  `StockAccount`，不得记录、返回或持久化账号 ID。
- MarketData 仅暴露 Adapter 规定的八个查询 callable；禁止 subscribe/download。
- 真实执行必须调用现有 `run_gate1_readonly_probe`，首次运行仅一次且不自动重试。
- stdout、stderr、报告与 evidence 只能出现固定 operation name、PASS/FAIL、异常类型和结构性布尔值；
  禁止对象 repr、返回数量、业务值、本地 QMT 路径和账号 fingerprint。
- 无论成功失败都必须至多一次 `stop()`；任何异常立即停止，不切换 live、不尝试第二个账号/终端。

## Allowed Files

- `.gitignore`（架构师已增加 `config/*.local.json`；Claude 不再修改）
- `src/tgrid/integrations/__init__.py`
- `src/tgrid/integrations/qmt_gate1_runtime.py`
- `tests/unit/test_gate1_qmt_runtime.py`
- `scripts/gate1_simulation_readonly_probe.py`（仅允许删除，不得继续作为实现）
- `README.md`
- `docs/GATE_1_REPORT.md`
- `work/reports/tests/G1-T006-test-output.txt`
- `work/reports/tests/G1-T006-offline-regression.txt`（仅允许替换为统一证据或删除）
- `work/reports/tests/G1-T006-simulation-probe.txt`（仅允许脱敏改写，不得重新运行 QMT）
- `work/gates/GATE_1/G1-T006_RESULT.md`
- `work/gates/GATE_1/CLAUDE_REPORT.md`
- `work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md`
- `work/handoff/claude_to_architect/TEST_REPORT.md`
- `work/handoff/claude_to_architect/QUESTIONS.md`
- `work/control/WORKFLOW_STATE.yaml`
- `work/control/CLAUDE_HEARTBEAT.md`
- `work/locks/WORKTREE_LEASE.yaml`（仅持有期间）

不得修改既有 Adapter/Probe、设计文档、协议、其他仓库或 reverse_repo 文件。

## Verification

1. 默认 Python：完整 `unittest discover`、`compileall`、AST 禁止交易 API/生产 assert 扫描。
2. 离线 Failure Injection：未知字段、明文账号、路径 hash 不符、0/2 个账号匹配、异常净化、opaque
   token 误用、connect/subscribe/query/stop 失败、cleanup 至多一次、输出零敏感数据。
3. Iteration 6 不得运行任何真实 QMT 命令；只允许 fake-client / fake-XtQuant 离线测试。
4. 证据保存完整离线测试输出和已发生真实结果的脱敏摘要，不保存 raw payload、vendor banner、路径、
   端口、账号 ID 或 fingerprint。

## Completion

完成后不提交 commit；释放 Lease，设置 `REVIEW_READY / owner=architect / iteration=6`，使用真实本机时间，
然后停止并等待独立 Review。
