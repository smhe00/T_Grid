# TGrid 协作控制面

本目录只保存 Web/Desktop ChatGPT（总架构师 / Gate Owner）与 Claude Code（实现工程师 / Test Owner）之间的任务、状态、验收和审计资料。

权威文件：

1. 项目根目录 `TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md`
2. 项目根目录 `TGrid_双Agent协作与Gate验收协议_V1.0.md`
3. 当 `collaboration_transport=github` 时，项目根目录 `TGrid_GitHub双Agent通信协议_V1.0.md`
4. `control/WORKFLOW_STATE.yaml` 指向的当前任务

开始工作前必须依次读取协议、状态、有效设计、当前任务、最新交接、Lease 和 Git 状态。

GitHub 模式下，`https://github.com/smhe00/T_Grid.git` 的 `main` 是唯一跨机器权威状态。Claude 默认每
180 秒静默 `fetch` 并只读取远端 `WORKFLOW_STATE.yaml`；无新 handoff 时不得写文件、输出等待消息或
生成 heartbeat commit。Claude 的 canonical 启动提示词见 `control/CLAUDE_GITHUB_LOOP_PROMPT.md`。

`locks/WORKTREE_LEASE.yaml` 不存在表示当前没有写入者；存在时只有其 `holder` 可以修改工作区。
Lease 只约束同一 checkout；跨机器互斥依赖状态所有权、唯一 handoff 和 non-force push。
