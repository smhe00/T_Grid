# Gate 1 / Current Task

当前任务：`G1-T005 — 离线 Gate 1 只读集成探针编排器`

唯一规范正文：

```text
work/control/CURRENT_TASK.md
```

G1-T004 已 PASS（commit `81e1abc`）。本任务仅组合已批准的 Trader/MarketData Adapter，用 fake client
验证固定只读探针顺序与失败 cleanup；不得 import XtQuant、真实连接/查询/订阅或增加交易能力。
