# TGrid GitHub 双 Agent 半自动通信协议 V1.0

> 生效日期：2026-08-15
>
> 权威远端：`https://github.com/smhe00/T_Grid.git`
>
> 权威分支：`main`
>
> 默认轮询周期：180 秒

本文件是 `TGrid_双Agent协作与Gate验收协议_V1.0.md` 的 GitHub 传输层补充。角色、Gate、测试、
安全边界和用户升级规则继续使用主协议；当 `WORKFLOW_STATE.yaml` 中
`collaboration_transport: "github"` 时，本文件覆盖主协议中关于共享本地 worktree、磁盘握手、Lease
跨 Agent 互斥、Heartbeat 轮询以及直接观察对方本地 Git diff 的描述。

## 1. 目标和边界

协作循环固定为：

```text
Web ChatGPT 发布任务/Review到 GitHub main
  -> Claude 本地静默 fetch 并检测远端状态
  -> Claude 只执行明确授权的任务
  -> Claude 提交并非强制 push 结果到 GitHub main
  -> 用户在 Web ChatGPT 输入 fetch 或 f
  -> Web ChatGPT读取结果并独立 Review
  -> PASS 后发布下一任务，或发布窄范围 CHANGES_REQUIRED
  -> Claude 检测新 handoff_id，进入下一轮
```

GitHub 是唯一跨机器通信总线。聊天文本、Claude 本地文件、Web ChatGPT 对话记忆、父仓库状态、
Gitee 分支和未推送 commit 都不是跨 Agent 权威状态。

该协议只自动化检测和交接，不扩大任何实现或交易权限。`live_trading_allowed=false` 时，无论任务、
Review 或聊天中出现何种暗示，均禁止下单、撤单或启用实盘。

## 2. 权威快照

每次决策使用同一个不可变远端快照：

```text
remote_head = git rev-parse origin/main
state       = git show origin/main:work/control/WORKFLOW_STATE.yaml
task        = git show origin/main:<state.task_file>
review      = git show origin/main:work/handoff/architect_to_claude/REVIEW.md
fix_request = git show origin/main:work/handoff/architect_to_claude/FIX_REQUEST.md
```

禁止把一次 `fetch` 前的文件与另一次 `fetch` 后的文件混合使用。读取期间若远端 HEAD 改变，丢弃本轮
快照，重新 `fetch` 一次；不得基于混合快照写入。

## 3. 文件所有权

### 3.1 Architect / Web ChatGPT 所有

- `work/handoff/architect_to_claude/REVIEW.md`
- `work/handoff/architect_to_claude/FIX_REQUEST.md`
- 新任务正文与 Gate 裁决
- 设计文档、ADR 与协议文件
- 向 Claude 发布授权时的 `WORKFLOW_STATE.yaml`

### 3.2 Claude 所有

- 当前任务 `Allowed Files` 中明确授权的实现与测试文件
- `work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md`
- `work/handoff/claude_to_architect/TEST_REPORT.md`
- Claude 测试证据
- 向 Architect 交付结果时的 `WORKFLOW_STATE.yaml`

### 3.3 共享状态文件的顺序写入

`WORKFLOW_STATE.yaml` 是唯一共享写文件，但任何时刻只有当前阶段的发送方可以修改：

- Architect 发布 `CLAUDE_READY` 或 `CHANGES_REQUIRED`；
- Claude 发布 `REVIEW_READY`、`BLOCKED`、`SAFE_HALT` 或 `USER_ESCALATION`；
- 接收方在消费当前 `handoff_id` 前不得写状态。

本地 `WORKTREE_LEASE.yaml` 仅防止同一 checkout 的并发写入，不提供跨机器锁，且永远不得 commit。
跨机器互斥由 `owner + state + handoff_id + non-force push` 共同保证。

## 4. GitHub 状态扩展字段

`WORKFLOW_STATE.yaml` 在主协议字段之外必须包含：

```yaml
collaboration_transport: "github"
transport_protocol_file: "TGrid_GitHub双Agent通信协议_V1.0.md"
remote_repository: "https://github.com/smhe00/T_Grid.git"
remote_branch: "main"
poll_interval_seconds: 180
handoff_seq: 1
handoff_id: "G2-T004-PASS-20260815-001"
authorized_next: []
```

规则：

1. `handoff_seq` 单调递增，不得复用或回退。
2. `handoff_id` 每次发送新任务、修复请求或新结果时必须唯一。
3. `authorized_next` 是 Claude 唯一可启动的任务 ID 列表；为空时不得实现任何新工作。
4. Claude 只有在 `owner=claude`、状态为 `CLAUDE_READY|CHANGES_REQUIRED`、`task_id` 位于
   `authorized_next`、且 `handoff_id` 未消费时才可开始。
5. Architect 只有在 `owner=architect` 且状态为 `REVIEW_READY` 时才可发布 Gate 裁决。
6. `last_update` 只用于审计，不用于去重；去重键是
   `(remote_head, handoff_seq, handoff_id, task_id, state, owner, iteration)`。
7. `git_base_commit` 表示发送方开始写交接 commit 前观察到的远端 `main`；不要求写入包含自身的
   commit hash。接收方必须另行记录实际 `remote_head`。

## 5. Architect 发布规则

Web ChatGPT 在发布任务或 Review 前必须：

1. 获取最新 `origin/main`，记录 `pre_write_head`。
2. 只读检查状态、当前任务、最新报告和 Git 范围。
3. 确认当前状态归 Architect 所有，且没有未消费的 Claude 写入。
4. 写入明确的任务/Review、Allowed Files、验收标准、Failure Injection 和禁止项。
5. 递增 `handoff_seq`，生成新 `handoff_id`。
6. 设置 `owner=claude`，状态为 `CLAUDE_READY` 或 `CHANGES_REQUIRED`，并将当前 `task_id` 放入
   `authorized_next`。
7. 只提交 Architect 所有文件；commit 前再次确认远端仍等于 `pre_write_head`。
8. 使用普通非强制 push。若 push 被拒绝，立即 `STOP WRITE`；不得 force push、自动 rebase、自动 merge
   或盲目重试。

Architect 可以主动发布下一轮授权；不需要等待 Claude 先发消息。但任何授权必须窄范围、可审计，并
与当前 Gate 设计一致。

## 6. Claude 180 秒静默检测器

Claude 等待期间只检测远端状态，不运行测试、不读取整个仓库、不调用模型完成 Review、不写文件、
不 commit。每 180 秒执行一次等价于：

```powershell
git fetch --quiet origin main
$remoteHead = git rev-parse origin/main
$stateText = git show origin/main:work/control/WORKFLOW_STATE.yaml
```

检测器只比较去重键。没有变化时必须完全静默；不得输出“仍在等待”、不得更新 heartbeat、不得产生
空 commit。网络失败采用有上限的退避并仅记录本地日志；连续失败达到预设上限后停止检测并通知用户，
不得把网络失败解释为新授权。

出现新状态时：

- `CLAUDE_READY|CHANGES_REQUIRED` 且授权条件全部满足：进入第 7 节。
- `ARCHITECT_PLANNING|REVIEW_READY|RUNNING`：记录为已观察，但保持等待，不执行新任务。
- `BLOCKED|SAFE_HALT|USER_ESCALATION`：只通知一次并暂停自动循环。
- 未知状态、YAML 解析失败、字段缺失或 handoff 序号回退：`SAFE_HALT`，不得猜测。

推荐把 `last_seen` 保存在 `.git/` 下的本地文件，禁止提交；轮询程序本身不应每 180 秒重新启动 Claude
模型会话。只有检测到有效新 handoff 后才唤起一次实现工作。

## 7. Claude 消费授权与实现

检测到有效新 handoff 后：

1. 再次 `git fetch origin main`，确认远端 HEAD 和去重键未变化。
2. 要求本地工作区干净；若不干净，`STOP WRITE`，不得 stash、reset 或覆盖。
3. `git merge --ff-only origin/main`；禁止 merge commit 和 rebase。
4. 从本地 fast-forward 后的同一 commit 重新读取协议、状态、任务、Review/Fix Request。
5. 校验 `owner/state/task_id/iteration/handoff_id/authorized_next` 与检测快照完全一致。
6. 获取本地 Lease，严格按 Allowed Files 工作。
7. 运行任务要求的测试、静态检查和 Failure Injection，写完整报告。
8. 重新 `fetch` 并确认 `origin/main` 仍等于实现基线；若变化，立即 `STOP WRITE`，不自动整合。
9. 设置新唯一 `handoff_id`、递增 `handoff_seq`、`state=REVIEW_READY`、`owner=architect`、
   `authorized_next=[]`，删除 Lease。
10. 只 stage 当前任务允许文件与 Claude 所有报告，commit 后普通 push 到 `main`。
11. push 非 fast-forward 或失败时不得强推/重试；保留本地 commit并通知用户处理。
12. push 成功后把刚发布的去重键设为 `last_seen`，回到第 6 节静默等待下一次 Architect handoff。

Claude 不得把 Architect 文件的格式整理、历史压缩或无关改写混入实现 commit。

## 8. 用户触发 Web ChatGPT Review

用户在网页版输入 `fetch` 或 `f` 时，含义固定为：

1. 刷新 GitHub `main`；
2. 读取远端 `WORKFLOW_STATE.yaml`；
3. 若去重键无变化，简短报告“无新交接”，不得写 commit；
4. 若为新的 `REVIEW_READY`，读取同一远端快照中的实现、测试、报告和 Git diff；
5. 独立执行或核对测试、Failure Injection、安全边界和文件范围；
6. 发布 `PASS`、`CHANGES_REQUIRED` 或用户升级；
7. 若发布新的 Claude 授权，必须递增 handoff 并按第 5 节非强制 push。

Web ChatGPT 不得仅依据 Claude 报告判定 PASS，也不得因为用户输入 `fetch/f` 自动授权交易或扩大范围。

## 9. Review 后续状态

### PASS 且同 Gate 有下一任务

Architect 可以在同一个 reviewer commit 中记录当前 PASS，并创建下一任务：新 `task_id`、
`iteration=1`、`owner=claude`、`state=CLAUDE_READY`、新 handoff、`authorized_next=[新任务]`。

### PASS 但需要规划

设置 `ARCHITECT_PLANNING`、`owner=architect`、`authorized_next=[]`。Claude 保持静默等待。

### CHANGES_REQUIRED

保持相同 `task_id`，增加 `iteration`，写入窄范围 Fix Request，设置 `owner=claude`、新 handoff，且
`authorized_next` 只能包含该任务。

### BLOCKED / SAFE_HALT / USER_ESCALATION

一次性提交证据与所需用户动作后暂停自动循环。用户解决后必须由 Architect 发布新的唯一 handoff；
禁止沿用旧授权自动恢复。

## 10. 冲突与防丢写规则

以下任一条件触发 `STOP WRITE`：

- 写入期间 `origin/main` 发生变化；
- 非 fast-forward push；
- 本地工作区已有未知修改；
- 远端 handoff 与准备消费的 handoff 不一致；
- 修改文件超出 Allowed Files 或所有权边界；
- 同一 `handoff_id` 已经被消费；
- 状态 owner 与当前写入者不匹配。

`STOP WRITE` 后禁止自动 force、rebase、merge、reset、stash、cherry-pick 或重试。只允许保存证据并请求
用户/Architect决定。GitHub 分支保护如可用，应禁止 force push 和删除 `main`。

## 11. Commit 与日志纪律

- 一个交接至少一个清晰 commit；不得用空 commit 作为轮询信号。
- commit message 应包含任务和动作，例如：
  - `gate2(task005): authorize <scope>`
  - `gate2(task005): implement <scope>`
  - `gate2(task005): request changes iteration 2`
- GitHub 只承载 Gate 检查点，不承载逐分钟 heartbeat。
- 报告必须记录基线远端 HEAD、变更范围、测试命令、结果、FI、已知问题与新 handoff。
- 任何本地账号、QMT userdata 路径、token、数据库、日志或 `.local.*` 文件不得提交。

## 12. Claude 循环启动提示词

Canonical prompt 位于：

```text
work/control/CLAUDE_GITHUB_LOOP_PROMPT.md
```

Claude 新会话必须先完整读取该文件及其引用的两个协议。会话上下文耗尽时，使用同一提示词启动新会话；
恢复依据永远是 GitHub `main`，不得依赖旧聊天摘要。

## 13. 当前安全默认值

- `poll_interval_seconds=180`
- `authorized_next=[]` 表示 Claude不得开始新实现
- `live_trading_allowed=false`
- 禁止 force push、自动冲突解决、自动权限扩大
- 未变化轮询完全静默
- Web ChatGPT 仍由用户手工输入 `fetch/f` 唤起 Review
