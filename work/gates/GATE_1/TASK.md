# Gate 1 / Current Task

当前任务：`G1-T002 — 离线依赖注入的 QMT Trader 只读 Adapter 边界`

唯一规范正文：

```text
work/control/CURRENT_TASK.md
```

G1-T001 已 PASS（commit `73cbe3b`）。本任务只用 fake client 实现固定方法的 Trader 只读 Adapter；
不得 import XtQuant、连接 QMT、读取账号或行情，也不得提供下单/撤单或动态转发入口。
