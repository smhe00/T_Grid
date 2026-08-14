# G2-T005 Task Pointer

任务名称：T-Lot Business Transition Policy Guard

Canonical Task: `work/control/CURRENT_TASK.md`

Architect authorization state: `CLAUDE_READY / owner=claude / iteration=1`

Baseline remote head before authorization commit: `439bbd96bece598f1aed7471db72c6267ee257a7`

Scope: closed offline T-Lot business transition policy over the already-PASS G2-T004 atomic writer; no raw SQL duplication,
no schema change, no QMT/OrderIntent/Reconciliation/manual trading execution.

Safety: `live_trading_allowed=false`.
