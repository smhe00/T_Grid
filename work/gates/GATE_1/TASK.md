# Gate 1 / Current Task

当前任务：`G1-T003 — 离线依赖注入的 MarketData 查询只读 Adapter 边界`

唯一规范正文：

```text
work/control/CURRENT_TASK.md
```

G1-T002 已 PASS（commit `a2f5fa3`）。本任务只用 fake client 实现八个固定查询方法的 MarketData
只读 Adapter；不得 import XtQuant、连接/查询真实 QMT、增加订阅/下载/账号/交易或动态转发入口。
