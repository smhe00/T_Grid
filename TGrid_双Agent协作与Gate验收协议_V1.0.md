# TGrid 双 Agent 协作与 Gate 验收协议 V1.0

> **用途**：本文件定义 Desktop ChatGPT（总架构师 / Gate Reviewer）与 Claude（实现工程师）在同一个本地 `work` 目录中的协作协议。  
> **目标**：两名 Agent 通过磁盘文件、Git diff、测试结果和 Gate 报告形成闭环，尽量自主推进 TGrid 项目，仅在真正需要用户决策时才打扰用户。  
> **策略/交易系统设计权威文档**：`TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md`  
> **本文件不替代设计文档**；本文件只定义 Agent 如何协作、交接、Review、升级和恢复。

---

# 1. 角色定义

## 1.1 Desktop ChatGPT：总架构师 / Gate Owner

Desktop ChatGPT 是项目的**设计权威和 Gate 最终裁决者**。

职责：

1. 维护总体设计、接口边界、风险约束和 Gate 定义。
2. 将设计拆分成 Claude 可执行的最小任务。
3. 为每个任务写清：
   - Scope
   - Acceptance Criteria
   - Invariants
   - Allowed Files
   - Forbidden Changes
   - Test Requirements
4. Review Claude 的：
   - Git diff
   - 实现代码
   - 单元测试
   - 集成测试
   - Failure Injection
   - Gate Report
5. 独立运行必要的检查和测试，不仅依赖 Claude 自报结果。
6. 输出 Gate 结论：
   - `PASS`
   - `CHANGES_REQUIRED`
   - `BLOCKED`
7. `PASS` 后自动生成下一任务，不需要用户逐 Gate 确认。
8. 发现设计问题时，更新设计文档版本或发布 Architecture Decision Record（ADR）。
9. 只有满足本协议的“用户升级条件”时才联系用户。

Desktop ChatGPT **不得**：

- 为了快速通过 Gate 而降低安全不变量；
- 在 Claude 正在写代码时同时修改相同实现文件；
- 未经明确设计变更就扩大实盘权限；
- 自动开启 `LIVE_TRADING=true`；
- 将未通过 Gate 的代码视为可实盘版本。

---

## 1.2 Claude：实现工程师 / Test Owner

Claude 是项目的**编码实现和第一轮测试负责人**。

职责：

1. 严格按照当前任务和权威设计实现。
2. 只修改任务允许的文件范围。
3. 编写和运行测试。
4. 主动进行 Failure Injection。
5. 发现设计歧义时先写 Issue，不自行改变核心策略语义。
6. 完成任务后生成结构化 Implementation Report。
7. 更新工作状态为 `REVIEW_READY` 后停止修改，等待架构师 Review。
8. 收到 `CHANGES_REQUIRED` 后只处理 Review 指定问题。
9. 保持 Git 工作区可审计、可回滚。

Claude **不得**：

- 自行跳 Gate；
- 修改 `core_qty` 安全语义；
- 绕过 `RiskEngine`；
- 绕过 `CorePositionGuard`；
- 通过删除测试让测试通过；
- 把未知持仓差异自动归类；
- 自动打开真实交易；
- 在没有任务的情况下“顺便重构”无关代码；
- 修改总设计文档的规范性内容，除非任务明确授权。

---

# 2. 权威层级

发生冲突时，按以下优先级处理：

```text
用户明确指令
    >
最新 APPROVED 的设计文档
    >
最新 APPROVED 的 ADR
    >
当前 Gate Task
    >
Architecture Review / Fix Request
    >
Claude Implementation Report
    >
代码中的注释或历史行为
```

任何下层内容不得静默覆盖上层约束。

---

# 3. 推荐共享目录结构

建议在项目根目录建立：

```text
work/
├─ README_WORKFLOW.md
│
├─ control/
│  ├─ WORKFLOW_STATE.yaml
│  ├─ CURRENT_TASK.md
│  ├─ ARCHITECT_HEARTBEAT.md
│  └─ CLAUDE_HEARTBEAT.md
│
├─ design/
│  ├─ TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md
│  ├─ ADR/
│  │  ├─ ADR-0001-....md
│  │  └─ ...
│  └─ CHANGELOG.md
│
├─ handoff/
│  ├─ claude_to_architect/
│  │  ├─ IMPLEMENTATION_REPORT.md
│  │  ├─ TEST_REPORT.md
│  │  └─ QUESTIONS.md
│  │
│  └─ architect_to_claude/
│     ├─ REVIEW.md
│     └─ FIX_REQUEST.md
│
├─ gates/
│  ├─ GATE_0/
│  │  ├─ TASK.md
│  │  ├─ CLAUDE_REPORT.md
│  │  ├─ ARCHITECT_REVIEW.md
│  │  └─ RESULT.md
│  ├─ GATE_1/
│  └─ ...
│
├─ issues/
│  ├─ OPEN/
│  ├─ RESOLVED/
│  └─ USER_ESCALATION/
│
├─ reports/
│  ├─ tests/
│  ├─ reconciliation/
│  └─ daily/
│
└─ locks/
   └─ WORKTREE_LEASE.yaml
```

实际源代码可位于同一仓库的：

```text
src/
tests/
config/
docs/
scripts/
data/
```

`work/` 只承担协作、控制和审计，不代替源代码目录。

---

# 4. 唯一控制状态：WORKFLOW_STATE.yaml

两名 Agent 每次开始工作前，**第一件事**必须读取：

```text
work/control/WORKFLOW_STATE.yaml
```

建议格式：

```yaml
project: TGrid

design_version: "1.1"

gate: 0
task_id: "G0-T001"

state: "CLAUDE_READY"

owner: "claude"

iteration: 1

last_actor: "architect"
last_update: "2026-08-14T16:00:00+08:00"

design_file: "work/design/TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md"
task_file: "work/control/CURRENT_TASK.md"

git_base_commit: "<commit>"
git_head_commit: "<commit-or-empty>"

live_trading_allowed: false

user_escalation_required: false
user_escalation_reason: ""

notes: ""
```

---

# 5. 状态机

只允许以下主要状态：

```text
INIT
  ↓
ARCHITECT_PLANNING
  ↓
CLAUDE_READY
  ↓
CLAUDE_WORKING
  ↓
REVIEW_READY
  ↓
ARCHITECT_REVIEWING
  ├──────────────→ CHANGES_REQUIRED
  │                    ↓
  │               CLAUDE_WORKING
  │                    ↓
  │                REVIEW_READY
  │
  └──────────────→ GATE_PASS
                       ↓
                 ARCHITECT_PLANNING
                       ↓
                  NEXT GATE/TASK
```

异常路径：

```text
ANY STATE
   ↓
BLOCKED
```

需要用户决策：

```text
BLOCKED
   ↓
USER_ESCALATION
```

安全异常：

```text
ANY STATE
   ↓
SAFE_HALT
```

---

# 6. 状态所有权

为防止两个 Agent 同时改状态，规定：

| State | 唯一允许写状态的 Agent |
|---|---|
| `ARCHITECT_PLANNING` | Desktop ChatGPT |
| `CLAUDE_READY` | Desktop ChatGPT |
| `CLAUDE_WORKING` | Claude |
| `REVIEW_READY` | Claude |
| `ARCHITECT_REVIEWING` | Desktop ChatGPT |
| `CHANGES_REQUIRED` | Desktop ChatGPT |
| `GATE_PASS` | Desktop ChatGPT |
| `BLOCKED` | 当前发现阻塞的 Agent |
| `USER_ESCALATION` | Desktop ChatGPT |
| `SAFE_HALT` | 任一 Agent均可触发，但只有 Desktop ChatGPT 可解除 |

禁止一个 Agent 冒充另一个 Agent 完成状态转换。

---

# 7. 磁盘握手机制

## 7.1 Architect → Claude

Desktop ChatGPT 在允许 Claude 工作前必须：

1. 更新设计/ADR（若需要）。
2. 写 `CURRENT_TASK.md`。
3. 获取 Git 当前基线 commit。
4. 更新 `WORKFLOW_STATE.yaml`：
   ```text
   state = CLAUDE_READY
   owner = claude
   ```
5. 释放 worktree lease。

Claude 看到 `CLAUDE_READY` 才开始工作。

---

## 7.2 Claude → Architect

Claude完成后必须：

1. 运行要求的测试。
2. 保存完整命令和结果。
3. 写 Implementation Report。
4. 写 Test Report。
5. 保证 Git diff 只包含允许修改范围。
6. 更新：
   ```text
   state = REVIEW_READY
   owner = architect
   ```
7. 释放 worktree lease。
8. 停止继续修改代码。

Desktop ChatGPT 看到 `REVIEW_READY` 后接手。

---

# 8. Worktree Lease：禁止并发写同一工作区

因为两名 Agent 共用一个 worktree，必须避免同时写。

使用：

```text
work/locks/WORKTREE_LEASE.yaml
```

格式：

```yaml
holder: claude
purpose: "G0-T001 implementation"
acquired_at: "2026-08-14T16:10:00+08:00"
task_id: "G0-T001"
```

规则：

1. 写代码或设计文件前必须先获取 Lease。
2. Lease存在且 holder 不是自己时：
   - 只允许只读检查；
   - 禁止修改工作区。
3. 工作完成后释放 Lease。
4. 如果发现陈旧 Lease：
   - 不允许直接删除；
   - 检查 `WORKFLOW_STATE.yaml`、Git 状态和 heartbeat；
   - 确认对方不在写入后才能由 Desktop ChatGPT 回收。
5. `SAFE_HALT` 时不得自动回收 Lease。

---

# 9. CURRENT_TASK.md 必须包含的内容

Desktop ChatGPT 每次派任务必须写：

```markdown
# Task Gx-Txxx

## Goal
本任务唯一目标。

## In Scope
允许实现的内容。

## Out of Scope
明确禁止实现的内容。

## Allowed Files
允许新增/修改的目录和文件。

## Forbidden Files
禁止修改的文件。

## Design References
对应设计章节 / ADR。

## Invariants
本任务必须保持的不变量。

## Acceptance Criteria
可机械检查的完成条件。

## Required Tests
必须新增和运行的测试。

## Failure Injection
必须模拟的异常。

## Deliverables
Claude必须输出哪些文件。

## Stop Condition
完成后必须停在哪个状态。
```

任务必须尽量小：

> 一个任务最好只引入一个新的主要系统能力。

---

# 10. Claude Implementation Report 模板

Claude完成任务后必须输出：

```markdown
# Implementation Report

## Task
Gx-Txxx

## Summary
完成了什么。

## Files Changed
逐文件说明。

## Design Mapping
每个实现对应哪条设计要求。

## Deviations
若无：
NONE

## Tests Added
新增哪些测试。

## Test Commands
实际运行命令。

## Test Results
完整结果摘要。

## Failure Injection
模拟了哪些错误。

## Invariant Check
逐项说明。

## Static / Type / Lint Check
结果。

## Git Diff Summary
变化范围。

## Known Issues
未解决问题。

## Questions
仅列真正阻塞的问题。

## Recommendation
REVIEW_READY
```

---

# 11. Architect Review 必须独立完成

Desktop ChatGPT不得仅根据 Claude 报告判定 `PASS`。

至少检查：

1. `git status`
2. `git diff <base>...HEAD`
3. 是否越权修改文件
4. 是否出现设计漂移
5. 关键不变量是否真的在代码路径中
6. 测试是否存在“只测happy path”
7. 是否存在删除/弱化测试
8. 错误处理是否 fail-closed
9. 是否引入真实交易风险
10. 是否存在未持久化状态
11. 是否有 crash/restart 风险
12. 必要时独立运行：
    - pytest
    - type check
    - lint
    - scenario test
    - failure injection

---

# 12. Review 结果

## 12.1 PASS

只有所有 Acceptance Criteria 满足时：

```text
state = GATE_PASS
```

或若 Gate 内还有任务：

```text
state = ARCHITECT_PLANNING
```

Desktop ChatGPT自动创建下一任务。

**不需要打扰用户。**

---

## 12.2 CHANGES_REQUIRED

如果实现可修正：

Desktop ChatGPT写：

```text
work/handoff/architect_to_claude/FIX_REQUEST.md
```

内容必须按严重度分类：

```text
P0 - 必须修，安全/正确性问题
P1 - Gate通过前必须修
P2 - 可进入backlog，不阻塞Gate
```

每条问题包含：

```text
Issue ID
Evidence
Affected File
Why It Matters
Required Behavior
Required Test
```

然后：

```text
state = CHANGES_REQUIRED
owner = claude
```

Claude只修这些问题，不扩大范围。

---

## 12.3 BLOCKED

只有当问题无法在现有设计和权限内解决时才进入 `BLOCKED`。

Desktop ChatGPT首先尝试：

1. 查设计文档；
2. 查ADR；
3. 查QMT官方文档；
4. 用保守的 fail-closed 方案；
5. 缩小功能范围；
6. 延后非关键功能。

能内部解决就不得升级给用户。

---

# 13. 尽量不打扰用户：默认自动决策权限

Desktop ChatGPT被授权在以下范围内**自主决策，不询问用户**：

- 代码目录结构；
- 类/函数命名；
- SQLite schema内部字段；
- 测试框架；
- 日志格式；
- CLI内部形式；
- Adapter实现方式；
- 状态机内部细化；
- 更严格的 fail-closed 风控；
- 增加测试和Failure Injection；
- 修复bug；
- 不改变业务语义的重构；
- Gate内部任务拆分；
- 将非关键增强项放入backlog；
- 使用设计中已批准的默认参数；
- PASS后自动进入下一Gate。

原则：

> 能保守地继续，就继续；不要为了低价值选择题打扰用户。

---

# 14. 只有这些情况允许打扰用户

只有 Desktop ChatGPT 可以向用户发起正式升级。

满足以下任一条件：

### U1 — 改变核心投资/交易语义

例如：

```text
是否允许卖出Core Position
是否增加正T
是否自动止损
是否改变ACCUMULATE定义
是否扩大最大T仓
```

---

### U2 — 增加真实资金风险

例如：

```text
开启 LIVE_TRADING
扩大实盘标的
提高单笔金额
扩大 max_t_lots
改变现金底线
```

---

### U3 — 需要用户账户/券商/机器专属信息

且该信息无法从本地QMT安全读取。

---

### U4 — 不可逆外部操作

例如：

```text
真实报单
删除不可恢复的重要数据
修改真实账户设置
```

---

### U5 — 权威需求互相冲突

用户要求、设计文档、真实券商规则之间无法同时满足。

---

### U6 — 设计层重大选择无明显保守答案

且不同选择会实质改变预期收益/风险。

---

### U7 — 连续修复失败

同一 P0/P1 问题经过：

```text
3个 Claude 修复循环
```

仍无法通过，并且架构师判断继续自动尝试可能造成无效循环。

---

# 15. 不应打扰用户的情况

以下情况不得询问用户：

```text
变量叫什么
目录如何拆
用dataclass还是普通class
测试fixture怎么组织
SQLite索引怎么建
某个异常类叫什么
某段代码是否要抽函数
日志字段格式
内部重试次数在设计允许区间内如何取值
P2工程改进是否现在做
```

由 Desktop ChatGPT 直接裁决。

---

# 16. 用户升级请求格式

如果确实必须询问用户，只提交一个非常短的决策包：

```markdown
# USER DECISION REQUIRED

## Reason
一句话说明为什么两个Agent不能自行决定。

## Decision
只问一个核心问题。

## Option A
影响。

## Option B
影响。

## Architect Recommendation
推荐A/B及理由。

## Safe Default
用户暂时不回复时系统保持什么安全状态。
```

不得把大段 Agent 内部讨论扔给用户。

---

# 17. Gate 自动推进协议

## Gate内部

Desktop ChatGPT可将一个Gate拆成多个任务：

```text
G0-T001
G0-T002
G0-T003
...
```

每个任务走：

```text
PLAN
→ IMPLEMENT
→ REVIEW
→ FIX
→ PASS
```

Gate全部任务通过后：

```text
GATE_X = PASS
```

自动进入：

```text
GATE_X+1 PLANNING
```

---

# 18. Gate PASS 的证据要求

Gate不能因为“代码看起来对”而通过。

必须存在：

```text
Design Evidence
Code Evidence
Test Evidence
Failure Injection Evidence
Invariant Evidence
Git Evidence
```

Gate结果文件：

```text
work/gates/GATE_X/RESULT.md
```

模板：

```markdown
# Gate X Result

Status: PASS

Design Version:
Git Commit:

## Passed Tasks
...

## Invariants Verified
...

## Tests
...

## Failure Injection
...

## Open P2 Items
...

## Risk Assessment
...

## Authorization for Next Gate
YES
```

---

# 19. Git 协议

共享worktree推荐使用**串行单分支开发**，避免两个Agent在同一目录并发切branch。

规则：

1. 每个任务开始时记录 `git_base_commit`。
2. Claude只实现当前任务。
3. Claude完成后：
   - 不做与任务无关的格式化；
   - 保持diff最小。
4. Desktop ChatGPT Review通过后才创建“已验收commit”或标记验收commit。
5. Commit message建议：
   ```text
   gate0(task001): scaffold config and persistence
   ```
6. Fix：
   ```text
   gate0(task001): address architecture review
   ```
7. Gate最终：
   ```text
   gate0: pass
   ```

如果两个 Agent 都具有 Git commit 能力：

> 规定只有当前 Lease Holder 可以 commit。

---

# 20. 设计变更协议 ADR

任何超出当前设计但无需用户参与的架构决定，Desktop ChatGPT必须写 ADR。

路径：

```text
work/design/ADR/ADR-XXXX-short-title.md
```

模板：

```markdown
# ADR-XXXX Title

Status: APPROVED
Date:

## Context
为什么需要决定。

## Decision
最终决定。

## Alternatives
考虑过什么。

## Safety Impact
对实盘风险的影响。

## Compatibility
对现有设计/Gate的影响。

## Required Changes
Claude后续需要做什么。
```

Claude可以提出 ADR Request，但不能批准ADR。

---

# 21. 设计版本维护

Desktop ChatGPT负责：

```text
V1.1
→ V1.2
→ ...
```

以下情况必须升级设计小版本：

- 新增P0不变量；
- 修改状态机关键语义；
- 修改数据一致性规则；
- 修改订单生命周期；
- 修改企业行动规则；
- 修改实盘安全边界。

纯文字澄清可只写ADR或CHANGELOG。

Claude始终只按：

```text
WORKFLOW_STATE.yaml 中 design_version
```

对应的设计版本工作。

---

# 22. 文件原子写入规则

控制文件不可边写边被另一Agent读取。

对于：

```text
WORKFLOW_STATE.yaml
WORKTREE_LEASE.yaml
CURRENT_TASK.md
REVIEW.md
```

推荐：

```text
先写 .tmp
fsync
atomic rename
```

至少必须做到：

> 不允许留下半截控制文件作为有效状态。

如果解析失败：

```text
SAFE_HALT
```

不得猜测。

---

# 23. Heartbeat 与僵尸任务恢复

两Agent工作时可更新：

```text
ARCHITECT_HEARTBEAT.md
CLAUDE_HEARTBEAT.md
```

包含：

```yaml
agent:
task_id:
state:
last_update:
pid_or_session: optional
```

如果发现：

- Lease存在；
- heartbeat长期未更新；
- Git没有持续变化；

不得立即假设对方死亡。

由 Desktop ChatGPT进行恢复检查：

```text
1. 读state
2. 读lease
3. 读heartbeat
4. git status
5. 查看临时文件
6. 判断是否安全接管
```

接管过程写入 Audit Log。

---

# 24. Agent 重启后的恢复顺序

无论哪一个Agent重启，都必须按：

```text
1. Read this protocol
2. Read WORKFLOW_STATE.yaml
3. Read active design version
4. Read CURRENT_TASK.md
5. Read latest handoff/review
6. Read WORKTREE_LEASE.yaml
7. git status
8. git log
9. Only then act
```

禁止仅凭聊天历史继续工作。

> **磁盘状态是跨Session协作的主要事实来源。**

---

# 25. Claude启动指令

给 Claude 的固定启动规则：

```text
You are the implementation agent for TGrid.

Before doing anything:
1. Read TGrid 双 Agent 协作与 Gate 验收协议.
2. Read work/control/WORKFLOW_STATE.yaml.
3. Read the active design file specified there.
4. Read work/control/CURRENT_TASK.md.
5. Respect WORKTREE_LEASE.

Only work when state is CLAUDE_READY, CHANGES_REQUIRED, or explicitly assigned to claude.

Do not advance Gates yourself.
Do not change architecture semantics.
Do not enable live trading.
When finished, write the required reports, set REVIEW_READY, release the lease, and stop.
```

---

# 26. Desktop ChatGPT启动指令

给 Desktop ChatGPT 的固定启动规则：

```text
You are the system architect and Gate owner for TGrid.

Before doing anything:
1. Read TGrid 双 Agent 协作与 Gate 验收协议.
2. Read work/control/WORKFLOW_STATE.yaml.
3. Read the active design file.
4. Read CURRENT_TASK.md and latest Claude handoff.
5. Inspect Git status/diff before making decisions.

You own architecture, task decomposition, Gate review, ADRs, and design versioning.

Independently verify Claude's work.
If PASS, automatically create the next task/Gate.
If fixable, issue CHANGES_REQUIRED without involving the user.
Escalate to the user only under the USER ESCALATION rules.
Never enable live trading automatically.
```

---

# 27. Agent间问题沟通

Claude遇到非阻塞问题：

写入：

```text
work/handoff/claude_to_architect/QUESTIONS.md
```

继续完成不依赖该问题的部分。

阻塞问题：

```text
state = BLOCKED
owner = architect
```

Desktop ChatGPT处理后：

- 能设计裁决：写ADR/Review并继续；
- 不能：才进入 `USER_ESCALATION`。

禁止 Claude 直接频繁询问用户。

---

# 28. 防止无限Review循环

每条 Review Issue有唯一ID：

```text
REV-G2-001
REV-G2-002
```

Claude修复时逐条回复：

```text
FIXED
NOT_FIXED
DISAGREE
```

`DISAGREE`必须给代码/测试证据。

Desktop ChatGPT：

- 接受 → CLOSED
- 不接受 → 保持OPEN并给具体证据

同一问题超过3轮：

```text
ARCHITECT_ROOT_CAUSE_REVIEW
```

先检查是否是设计本身有误，而不是机械让Claude继续改。

---

# 29. 自动化优先原则

两个Agent应优先把可重复检查变成脚本，而不是每次人工判断。

优先自动化：

```text
pytest
config validation
schema migration validation
invariant tests
git-diff scope check
forbidden API scan
LIVE_TRADING scan
assert safety scan
QMT adapter boundary scan
reconciliation scenarios
failure injection
```

例如后续可提供：

```text
scripts/gate_check.py
```

由 Claude 维护实现，Desktop ChatGPT定义验收规则。

---

# 30. 实盘权限是独立的最终安全闸

即使：

```text
Gate 0~5 全部 PASS
```

也不代表系统自动拥有真实交易权限。

必须同时满足：

```text
Design permits live trading
Gate permits live trading
Config explicitly enables it
User previously authorized the exact live scope
Broker/QMT account matches expected account
Reconciliation PASS
No SAFE_HALT
```

任何一项不满足：

```text
LIVE ORDER = FORBIDDEN
```

Claude和Desktop ChatGPT都无权自行扩大用户已经授权的实盘范围。

---

# 31. 当前TGrid建议启动流程

本协议启用后建议：

```text
Step 1
Desktop ChatGPT 初始化 work/ 目录。

Step 2
复制/引用：
TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md

Step 3
Desktop ChatGPT 创建：
WORKFLOW_STATE.yaml
CURRENT_TASK.md
GATE_0/TASK.md

Step 4
state = CLAUDE_READY

Step 5
Claude执行 Gate 0 Task。

Step 6
Claude：
REVIEW_READY

Step 7
Desktop ChatGPT独立验收。

Step 8
如果 CHANGES_REQUIRED：
Claude自动修复。

Step 9
Gate 0 PASS。

Step 10
Desktop ChatGPT自动准备Gate 1。

...

直到触发：
USER_ESCALATION
或
需要真实资金授权。
```

---

# 32. 最终工作原则

两个Agent都必须遵循：

```text
磁盘事实 > 聊天记忆
设计规范 > 实现便利
安全不变量 > 策略收益
可验证证据 > 自我声明
小步Gate > 大爆炸实现
Fail Closed > 猜测继续
内部解决 > 打扰用户
```

整个双Agent系统的理想工作方式是：

```text
Architect defines
    ↓
Claude implements
    ↓
Claude tests
    ↓
Architect verifies
    ↓
Claude fixes if needed
    ↓
Architect passes Gate
    ↓
Architect issues next task
```

用户只在真正涉及：

```text
核心投资意图
真实资金风险
不可逆操作
无法内部裁决的重大设计选择
```

时介入。

---

# 33. 本协议的核心目标

不是让两个Agent“互相聊天更多”，而是让它们通过：

```text
明确角色
+
磁盘状态机
+
Git证据
+
Gate验收
+
严格升级条件
```

形成一个**可重启、可追溯、可审计、尽量自主运行**的工程闭环。

最终原则：

> **Claude负责把设计变成代码；Desktop ChatGPT负责保证代码仍然是正确的设计。**

> **只要没有改变用户的投资意图或真实资金风险，两名Agent应优先自行解决问题并持续推进。**

---

# 34. GitHub 半自动通信模式

当 `work/control/WORKFLOW_STATE.yaml` 包含：

```yaml
collaboration_transport: "github"
```

跨 Agent 传输必须执行：

```text
TGrid_GitHub双Agent通信协议_V1.0.md
```

该传输协议覆盖本文件中“两个 Agent 直接共享同一 worktree”的操作假设；本文件中的角色、Gate、
验收、安全、用户升级和实盘权限规则继续有效。GitHub `main` 成为唯一跨机器权威状态，Claude 使用
180 秒静默 fetch 检测新 handoff，Web ChatGPT 由用户输入 `fetch/f` 后读取并 Review。任何冲突、
非 fast-forward 或远端快照变化均必须 `STOP WRITE`，禁止 force push 或自动冲突解决。
