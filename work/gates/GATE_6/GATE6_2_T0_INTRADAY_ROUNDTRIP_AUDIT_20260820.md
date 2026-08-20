# Gate-6.2 Independent Audit — T+0 Intraday Roundtrip — 2026-08-20

## Verdict

**CHANGES_REQUIRED**

Reviewed GitHub `main`: `032c54815ccc3f20e13761745e24ee4d2549cd94`

Observed broker evidence is materially positive: the WorkBuddy report records one QMT simulation BUY 100 FILLED followed by one SELL 100 FILLED on `513100.SH`, final broker position 0, zero cancels and zero live calls. This audit does **not** dispute that the observed simulation roundtrip occurred.

Gate-6.2 is nevertheless not accepted because repository/protocol scope and runner safety requirements are not satisfied.

`live_trading_allowed=false` remains mandatory. No live order/cancel is authorized.

## Findings

### P0-1 — Allowed-files boundary was violated

From architect result `b6a5c255cba6a1cd11e2f385df2dea8a1962fcf3` to reviewed `main`, the actual diff contains five files, not the four allowed by `CURRENT_TASK.md`.

Unexpected tracked file:

```text
work/reports/gate6-sim/gate6-sim-negative-2026-08-15.json
```

The task explicitly permits local runtime/evidence artifacts only in ignored/local paths and says they must not be committed when machine/account-specific. The implementation report also states that only the four allowed files were committed, which is inconsistent with Git history.

Required fix: remove this file from current HEAD using a normal forward commit. Do not rewrite history or force push.

### P0-2 — Handoff was integrated with a conflict merge instead of the required linear/ff-only protocol

Current `main` is merge commit `032c548...` with parents `db121793...` and `b6a5c255...`; its commit message records conflicts in all four Gate-6.2 handoff files.

The task required `git merge --ff-only origin/main` and the collaboration protocol requires STOP WRITE on remote divergence/conflict rather than automatic merge/rebase/force behavior. A conflict merge after divergent implementation therefore cannot be treated as a clean protocol-compliant handoff.

Required fix: do not rewrite history. Preserve the merge as historical evidence, but from this point forward consume only the new CHANGES_REQUIRED handoff from current GitHub `main`; no further merge/rebase/force. Reports must explicitly acknowledge the protocol deviation.

### P0-3 — Idempotent recovery can sell unrelated pre-existing inventory

Current runner treats `can_use_volume >= 100` as sufficient to skip Leg A and proceed as if the authorized BUY were already FILLED. It does not require the existing `TG_G62_A` intent to be present and FILLED before taking this path.

This violates the task condition that SELL is authorized only after the task BUY is exactly FILLED 100. On a simulation account already holding `513100.SH`, a recovery run could misclassify unrelated inventory as this roundtrip's BUY and sell 100 shares.

Required fix: recovery/skip-BUY is allowed only when authoritative TGrid/Core/broker evidence ties the held quantity to `TG_G62_A` and proves that intent FILLED 100. Otherwise fail closed; never infer task ownership from account position alone.

### P1-1 — Unresolved BUY/SELL path still omits required cancel + reconcile

The runner polls each leg for a bounded period and, if not FILLED, returns `BUY_NOT_RESOLVED` / `SELL_NOT_RESOLVED` immediately.

`CURRENT_TASK.md` requires, for a still-unresolved order after bounded wait:

```text
at most one cancel -> reconcile -> STOP
```

Required fix: implement at most one cancel through the normal TGrid -> Core path for an unresolved leg, reconcile authoritatively, record the post-cancel state, and then stop. No blind retry.

### P1-2 — Quote preflight does not enforce freshness or reasonable spread

`_fresh_quote()` records tick time and spread, but the acceptance gate only tests positive bid/ask and ordering. It does not compute tick age or enforce a spread bound. The SELL-leg gate is even narrower (`bid1 > 0`).

Required fix: validate timestamp freshness and an explicit conservative spread criterion for both BUY and SELL pre-submit quotes. Invalid/stale/wide quotes must fail closed before broker submit.

### P1-3 — Account-specific identifiers are hard-coded in the committed runner

Final Core reconciliation currently embeds hashed account/runtime identifiers directly in `scripts/gate6_t0_roundtrip.py`. Even though hashed, these are account-specific runtime identifiers and should not be committed according to the repository safety boundary.

Required fix: derive the authority/account identity from the already-built simulation runtime/binding or from local ignored configuration; do not commit account-specific constants. Remove the literals by normal forward commit; do not expose them in reports.

### P1-4 — Completion control state is internally inconsistent

The reviewed state is `REVIEW_READY / owner=architect`, but `authorized_next` still contains the implementation task. The task's completion contract requires `authorized_next=[]` on handback to Architect.

This audit handoff corrects the control state to a new `CHANGES_REQUIRED` iteration with exactly the current task authorized.

## Positive evidence retained

The following evidence is accepted as useful but does not self-certify Gate-6.2:

- actual executor identity is WorkBuddy;
- simulation-only roundtrip report: BUY 100 FILLED -> SELL 100 FILLED -> position 0;
- reported counts: simulation BUY=1, simulation SELL=1, cancels=0, live order=0, live cancel=0;
- reported TGrid/Core final resource invariants are clean;
- no production `src/` or public Core source change was reported.

No additional broker roundtrip is required merely to fix the repository/runner defects above. If WorkBuddy chooses to exercise failure paths, broker side effects must remain strictly in the QMT simulation account; live remains prohibited.

## Re-review acceptance

Before returning `REVIEW_READY`, provide evidence that:

1. current diff from this audit handoff touches only the explicitly authorized fix files;
2. the unexpected tracked JSON is removed from HEAD by forward commit;
3. runner recovery cannot use unrelated existing position as proof of `TG_G62_A`;
4. unresolved leg performs at most one cancel through TGrid -> Core, reconciles, then stops;
5. stale/wide quote failure injection blocks before submit for both legs;
6. account-specific constants are absent from committed runner/report content;
7. `compileall`, the existing Gate-6 focused pytest set, and `qmt-execution-core verify` remain green;
8. no live order/cancel calls and `live_trading_allowed=false`.

Gate-6.2 remains **CHANGES_REQUIRED** pending independent re-review.
