# Gate 1 / Current Task

当前任务：`G1-T004 — 离线依赖注入的单路 Quote Subscription 只读生命周期边界`

唯一规范正文：

```text
work/control/CURRENT_TASK.md
```

G1-T003 已 PASS（commit `6d6d30a`）。本任务只用 fake client 实现单路 quote subscribe/unsubscribe
生命周期；不得 import XtQuant、真实订阅/查询、增加下载/账号/连接/交易或动态转发入口。
