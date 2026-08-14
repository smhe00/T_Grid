# Fix Request — G2-T005 / Iteration 2

Status: `CHANGES_REQUIRED`

Authorized by Architect at: `2026-08-15T02:50:00+08:00`

## Scope

只修 `REV-G2T005-001..004`。不得扩大 G2-T005 功能面。

### 1. GitHub provenance / reports

- 从本次新的 GitHub Architect handoff fast-forward 后开始工作。
- 交付时 `WORKFLOW_STATE.yaml` 中的 Git provenance 必须来自 `smhe00/T_Grid` 当前 GitHub main，不得写入无共同祖先的本地 monorepo SHA。
- Implementation/Questions/Test reports 必须如实描述实际 GitHub commit/push 状态，不得再写“GitHub push deferred”而同时把结果交付到 GitHub main。
- 不要修改 `CLAUDE_HEARTBEAT.md`；Iteration 1 对它的修改只在报告中记录为已识别 scope drift，不重写历史。

### 2. Add explicit 7×7 status-pair closure test

在 `tests/unit/test_t_lot_transition_policy.py` 增加独立测试：

```text
all 7 from_status × all 7 to_status = 49 pairs
```

验证只有下列五条 directed status edge 可通过某个批准 action 解析得到：

```text
PENDING_BUY  -> OPEN
OPEN         -> PENDING_SELL
PENDING_SELL -> CLOSED
OPEN         -> SUSPENDED
SUSPENDED    -> OPEN
```

其余 44 对不可达；所有 7 个 self-transition 不可达。该测试只验证 closure，不新增/改变生产 edge。

### 3. Add writer write-failed FI

对 accepted request patch G2-T004 writer 抛既有 `TLotWriteFailedError`：

- writer 恰好 1 call；
- policy 不吞异常；
- 不 retry；
- 不二次调用；
- 不改变 action→status/event_type mapping。

### 4. Re-run evidence

重新运行并保存：

```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src tests
AST forbidden capability / raw-SQL scan
git diff --check
Allowed Files diff-check
```

报告中单列：49-pair closure 结果、write-failed FI、GitHub provenance、Iteration 1 heartbeat scope drift。

## Iteration 2 Allowed Files

- `tests/unit/test_t_lot_transition_policy.py`
- `work/reports/tests/G2-T005-test-output.txt`
- `work/gates/GATE_2/CLAUDE_REPORT.md`
- `work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md`
- `work/handoff/claude_to_architect/TEST_REPORT.md`
- `work/handoff/claude_to_architect/QUESTIONS.md`（仅确有问题时）
- `work/control/WORKFLOW_STATE.yaml`

本地 Lease 可按协议使用但不得 commit。

## Explicitly Forbidden in Iteration 2

- `src/tgrid/persistence/t_lot_transition_policy.py`
- `src/tgrid/persistence/__init__.py`
- `src/tgrid/persistence/t_lot_writer.py`
- `migrations.py` / `database.py` / schema / migration
- `work/control/CLAUDE_HEARTBEAT.md`
- Architect-owned `REVIEW.md` / `FIX_REQUEST.md` / `CURRENT_TASK.md`
- QMT / XtQuant / OrderIntent / Reservation / Reconciliation / trading code
- live order/cancel/download/subscribe

`live_trading_allowed=false` remains binding.

## Stop Condition

完成后再次 fetch GitHub `main`；若远端仍是本次 Architect handoff 基线，按协议提交 Iteration 2 的 Allowed Files 与 Claude reports，设置新的唯一 handoff、`handoff_seq + 1`、`state=REVIEW_READY`、`owner=architect`、`iteration=2`、`authorized_next=[]`，普通非强制 push 后停止等待 Review。远端若变化则 STOP WRITE，不 force/rebase/merge/blind retry。
