# Gate 2 / Claude Report — G2-T003

## Status
G2-T003 Iteration 2 修复完成，交付 `REVIEW_READY`，等待架构师独立 Review。未 commit。

## Iteration 2 修复内容（REV-G2T003-001..002）
- **REV-G2T003-001 — FIXED**：dangling-FK probe 改用 collision-safe `_pick_probe_id` 从 t_lots.id 选择
  已确认不存在的值，不再使用固定字符串 `__tgrid_probe_no_such_lot`；合法用户使用该 id 时健康 initialize
  通过且 t_lots/audit/history/user_version 逐值不变；缺外键伪造 schema 预置同一冲突 id 仍被拒绝。
- **REV-G2T003-002 — FIXED（architect-authorized）**：确认保留 `tests/unit/test_t_lot_schema.py` 的
  精确机械 diff（MAX_SCHEMA_VERSION/MIGRATIONS/history 2→3），未弱化约束断言；不再作为 unresolved
  question。

## 证据
- `work/reports/tests/G2-T003-test-output.txt`（**579 项全部通过** + compileall exit 0 + AST PASS +
  REV-G2T003-001 独立 FI 重放全文）。
- HEAD == 基线 `aa13ef9`；本任务文件 `git diff --check` exit 0。

## 范围遵守
未连接 QMT、未访问账号/行情、未实现 writer/CRUD/Audit 服务/Reconciliation/OrderIntent、未修改
position/integrations/adapters/probes、未触碰 reverse_repo；`live_trading_allowed=false`；未 commit/push。
Iteration 2 只改 dangling-FK probe、回归/扩展测试与报告。

## Recommendation
REVIEW_READY（等待 Desktop ChatGPT 独立 Review）。
