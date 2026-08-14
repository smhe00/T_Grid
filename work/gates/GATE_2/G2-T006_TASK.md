# G2-T006 Task Pointer

任务名称：Offline Position Reconciliation Decision Engine

Canonical Task: `work/control/CURRENT_TASK.md`

Architect authorization state: `CLAUDE_READY / owner=claude / iteration=1`

Baseline remote head before authorization commit: `e9572d67feab498ce421f8c9220366470c208a61`

Scope: pure offline fail-closed comparison of externally supplied Broker Position against `CoreQty + StrategicExtra + OpenTLotPosition`; exact match -> RECONCILED, any unexplained mismatch -> SAFE_MODE. Core comes only from `SymbolConfig.core_qty`.

No SQLite/QMT/startup orchestration/SAFE_MODE persistence/OrderIntent/trading. `live_trading_allowed=false`.
