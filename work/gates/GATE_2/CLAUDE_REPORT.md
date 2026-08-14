# Gate 2 / Claude Report — G2-T002

## Status
G2-T002 Iteration 2 修复完成，交付 `REVIEW_READY`，等待架构师独立 Review。未 commit。

## Iteration 2 修复内容（REV-G2T002-001..005）
- **REV-G2T002-001 — FIXED**：`id` 显式 `NOT NULL` 且非空；`qty` 数据库级 `typeof='integer' AND qty > 0`
  （拒绝 1.5/0/负/文本）；price 字段非 NULL 时 `typeof IN ('integer','real')` 且为正（文本不能绕过 `> 0`）。
- **REV-G2T002-002 — FIXED**：probe 使用与现有行确认不冲突的唯一 ID（`_pick_probe_id`），不依赖保留
  ID namespace；PK 冲突不再拒绝健康库、也不再让弱化约束假通过；合法预置三个旧 probe ID 后
  initialize 通过且行内容/history/user_version 逐值不变；弱化 qty/status + 冲突 ID 仍被识别。
- **REV-G2T002-003 — FIXED**：`realized_pnl` 允许负/零/正（仅要求 numeric storage type）；
  `fees` 允许零、拒绝负数/文本。
- **REV-G2T002-004 — FIXED**：verifier 行为探测补齐 NULL/空 id、空必需文本、fractional qty、文本价格、
  非法 review_status；review_status 允许集合与 NULL 行为验证；probe 前后零残留逐值验证。
- **REV-G2T002-005 — FIXED**：`tests/unit/test_cli.py` 仅保留三条精确断言更新（一条 user_version、
  两条 migration history count 1→2），无其他改动。

## 证据
- `work/reports/tests/G2-T002-test-output.txt`：**555 项全部通过**（545 基线 + 10 新增/拆分）+
  compileall exit 0 + AST 扫描 PASS（23 文件，forbidden=0）+ `git diff --check` exit 0 +
  独立 Review SQLite FI 重放全文。
- HEAD == 基线 `7270485`；未 commit/push。

## 范围遵守
未连接 QMT、未访问账号/行情、未实现 Ledger CRUD/Audit/Reconciliation/OrderIntent、未修改
position/integrations/adapters/probes、未触碰 reverse_repo；`live_trading_allowed=false`。
Iteration 2 只改 migration/schema/verifier/测试/报告；test_cli.py 的三条断言由 REV-G2T002-005 明确授权。

## Recommendation
REVIEW_READY（等待 Desktop ChatGPT 独立 Review）。
