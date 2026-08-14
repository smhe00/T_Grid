# Worktree Lease

`WORKTREE_LEASE.yaml` 不存在表示未被占用。

写入者开始工作前必须原子创建 Lease；结束交接后必须删除。发现属于另一 Agent 的 Lease 时只能只读检查，不得覆盖或删除。

