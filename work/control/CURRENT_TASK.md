# Current Task — WorkBuddy GitHub Protocol Handshake

## Status

`AUTHORIZED_PROTOCOL_HANDSHAKE`

This task exists only to verify that **WorkBuddy can replace DSH/Claude as the local execution endpoint while remaining compatible with the existing TGrid GitHub handoff protocol**.

No product implementation, QMT simulation trading, or live trading is authorized by this task.

## Compatibility role

For protocol compatibility, WorkBuddy MUST act as the existing execution-side role:

```text
protocol role = claude
actual executor = workbuddy
```

Do **not** rename protocol states, `owner=claude`, handoff directories, or report paths. `claude` is the protocol role name; WorkBuddy is the concrete local executor.

## Authoritative protocol

Read from the same `origin/main` snapshot:

1. `TGrid_双Agent协作与Gate验收协议_V1.0.md`
2. `TGrid_GitHub双Agent通信协议_V1.0.md`
3. `work/control/WORKFLOW_STATE.yaml`
4. this `work/control/CURRENT_TASK.md`
5. `work/control/WORKBUDDY_GITHUB_LOOP_PROMPT.md`
6. latest `work/handoff/architect_to_claude/REVIEW.md` and `FIX_REQUEST.md` if present
7. latest `work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md` and `TEST_REPORT.md`

## Task

Perform one protocol handshake only:

1. `git fetch origin main`.
2. Record `remote_head = origin/main`.
3. Require a clean worktree; otherwise STOP WRITE.
4. Fast-forward local checkout with `git merge --ff-only origin/main`.
5. Re-read the protocol, `WORKFLOW_STATE.yaml`, and this task from that exact commit.
6. Verify all of the following before writing:
   - `owner=claude`
   - `state=CLAUDE_READY`
   - `task_id=WORKBUDDY-GITHUB-HANDSHAKE-001`
   - `authorized_next` contains exactly this task
   - `handoff_seq=59`
   - `handoff_id=TGRID-WORKBUDDY-HANDSHAKE-20260818-059`
7. Do not modify or execute product implementation.
8. Write a handshake acknowledgement to the two normal execution-side reports.
9. Before push, fetch again and require `origin/main` to equal the implementation baseline observed in step 2. If it changed, STOP WRITE; do not merge/rebase/force/retry.
10. Update `WORKFLOW_STATE.yaml` to `REVIEW_READY`, `owner=architect`, `authorized_next=[]`, increment `handoff_seq` to `60`, and use a unique acknowledgement `handoff_id`.
11. Commit only the allowed files and push normally to `origin/main`.
12. Stop and wait for Architect review.

## Required acknowledgement content

`IMPLEMENTATION_REPORT.md` must contain at least:

```text
executor: workbuddy
protocol_role: claude
result: HANDSHAKE_ACK
observed_remote_head: <sha>
observed_handoff_seq: 59
observed_handoff_id: TGRID-WORKBUDDY-HANDSHAKE-20260818-059
observed_task_id: WORKBUDDY-GITHUB-HANDSHAKE-001
product_code_changes: 0
qmt_order_calls: 0
qmt_cancel_calls: 0
live_calls: 0
```

`TEST_REPORT.md` must record the protocol checks actually performed, including clean worktree, exact handoff match, pre-push remote-head recheck, and the files committed.

## Allowed Files

Only:

```text
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md
work/handoff/claude_to_architect/TEST_REPORT.md
work/control/WORKFLOW_STATE.yaml
```

No other file may be changed.

## Hard prohibitions

- no `src/` changes;
- no test implementation changes;
- no strategy/config changes;
- no Core changes;
- no QMT order or cancel calls, simulation or live;
- no broker-side effects of any kind;
- no force push, rebase, merge commit, reset, stash, cherry-pick, or automatic retry;
- do not treat this handshake as renewed Gate-6.1 broker-side-effect authorization.

`live_trading_allowed=false` remains a hard invariant.

## Acceptance

Handshake PASS requires a new fast-forward commit on `main` that:

- changes only the 3 allowed files;
- identifies `executor=workbuddy` and `protocol_role=claude`;
- acknowledges the exact handoff above;
- reports zero product-code and broker-side effects;
- returns state to `REVIEW_READY / owner=architect / authorized_next=[]`.

Anything else is a protocol handshake failure and must not trigger product work.
