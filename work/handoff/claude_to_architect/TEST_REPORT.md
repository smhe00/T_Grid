# Test Report — Gate-6.2 T+0 Intraday Roundtrip

> Date: 2026-08-20
> actual_executor: dsh (this session), protocol_role: claude

## Protocol checks actually performed

1. **Worktree clean**: dedicated worktree `D:\gitee\miniQMT\.workbuddy-wt`
   detached at `571eb07376ff0362bcae4e4054f10eef8a7928d1`;
   `git status --porcelain` = empty before writing (verified).
2. **Handoff exact match** (from the worktree's
   `work/control/WORKFLOW_STATE.yaml` + `CURRENT_TASK.md`):
   owner=claude, state=CLAUDE_READY,
   task_id=GATE6.2-T0-INTRADAY-ROUNDTRIP-20260820,
   handoff_seq=62,
   handoff_id=TGRID-GATE6-2-T0-ROUNDTRIP-20260820-062,
   authorized_next=[GATE6.2-T0-INTRADAY-ROUNDTRIP-20260820].
3. **Remote-head recheck before any broker side effect**: `git fetch
   tgrid-github main` at 09:31:17 +08:00 confirmed `origin` head still
   `571eb07376ff0362bcae4e4054f10eef8a7928d1` (unchanged).
4. **Pre-broker gates**:
   - `python -m compileall -q src scripts` → exit 0;
   - `python -m pytest -q tests/unit/test_qec_runtime.py
     tests/unit/test_qec_iter16.py` → 23 passed, 17 subtests passed;
   - `qmt-execution-core verify` → `release_formal_verification: PASS`.
5. **Simulation/QMT safety preflight (non-time)**:
   - bound environment `simulation`; `live_trading_allowed=false`;
   - production builder: `runtime_lock_mode=shared`, no coordinator/authority
     override, Authority resolve `bootstrap=False` (verify-only);
   - Core reference `a68572decb799bcbbf1b2892fcf58ac321ce9636` (pyproject
     pin + local editable checkout);
   - account `99028134`, account_type 2, status 0 (healthy sim securities
     account);
   - no unresolved Core claim / TGrid reservation for `513100.SH`;
     active reserved cash 0;
   - QMT trading calendar includes 2026-08-20.
6. **Quote preflight — FAILED (hard requirement not provable)**:
   `get_full_tick(['513100.SH'])` across 09:31:24–09:35:37 +08:00 returned a
   tick frozen at 09:15:01 (call-auction match, last 2.2) with
   bid1=0/ask1=0/volume=0 on every attempt, while 510300.SH / 510050.SH /
   600519.SH showed live bid/ask in the same window. The runner correctly
   stopped with `BLOCKED_PRE_BROKER` before any order.

## Outcome

```text
BLOCKED_PRE_BROKER
reason: 513100.SH has no fresh bid/ask in the QMT simulation data feed
```

## Counts

```text
simulation BUY submits : 0
simulation SELL submits: 0
simulation cancels     : 0
live order calls       : 0
live cancel calls      : 0
product src changes    : 0
```

## Files committed in this handoff

```text
scripts/gate6_t0_roundtrip.py
work/handoff/claude_to_architect/IMPLEMENTATION_REPORT.md
work/handoff/claude_to_architect/TEST_REPORT.md
work/control/WORKFLOW_STATE.yaml
```
