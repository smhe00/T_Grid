# Gate 2 / Claude Report — G2-T004

## Status
G2-T004 Iteration 2 修复完成，交付 `REVIEW_READY`，等待架构师独立 Review。未 commit。

## Iteration 2 修复内容（REV-G2T004-001..003）
- **REV-G2T004-001 — FIXED**：writer 事务边界覆盖 `BaseException`。CAS/audit/COMMIT 任一步主失败先
  `_rollback_or_invalidate` 再传播/转换：KI/SE/GE 保持原对象/类型传播；普通异常/sqlite 错误转固定
  data-free `TLotWriteFailedError`（`__cause__`/`__context__` 干净）；rollback 自身失败时关闭连接使其
  不可 commit，且不覆盖主异常。
- **REV-G2T004-002 — FIXED**：`_require_status` 先 exact non-empty `str` 校验再做 membership，恶意
  对象 `__eq__` 不再被调用。
- **REV-G2T004-003 — FIXED**：两连接 CAS 竞争改为 Event 驱动真实交错（conn1 持 BEGIN IMMEDIATE 未提交
  时 conn2 争锁发起），确定性释放后 conn1 胜、conn2 conflict、恰一条 audit。

## 证据
- `work/reports/tests/G2-T004-test-output.txt`（**597 项全部通过** + compileall exit 0 + AST PASS（24 文件）
  + REV-G2T004-001..003 独立 FI 重放全文）。
- HEAD == 基线 `3fd560c`；本任务文件 `git diff --check` exit 0。

## 范围遵守
未连接 QMT、未访问账号/行情、未新增 writer API/schema/状态矩阵/CRUD/外部依赖；未修改既有 schema/
verifier、position/integrations/adapters/probes、reverse_repo；`live_trading_allowed=false`；未 commit/push。

## Recommendation
REVIEW_READY（等待 Desktop ChatGPT 独立 Review）。
