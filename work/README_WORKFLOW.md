# TGrid 协作控制面

本目录只保存 Desktop ChatGPT（总架构师 / Gate Owner）与 Claude Code（实现工程师 / Test Owner）之间的任务、状态、验收和审计资料。

权威文件：

1. 项目根目录 `TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md`
2. 项目根目录 `TGrid_双Agent协作与Gate验收协议_V1.0.md`
3. `control/WORKFLOW_STATE.yaml` 指向的当前任务

开始工作前必须依次读取协议、状态、有效设计、当前任务、最新交接、Lease 和 Git 状态。

`locks/WORKTREE_LEASE.yaml` 不存在表示当前没有写入者；存在时只有其 `holder` 可以修改工作区。

