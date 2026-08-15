# Audit Node A Independent Review — 2026-08-15

## Verdict

`CHANGES_REQUIRED` — Gate 5 is **not** independently accepted yet.

Review target: GitHub `main` snapshot `910a727d3ef66c262abfd9dea45b092106f6d4a6`, based on remediation baseline `1e1457f27d2d4b01aed12813d8ffedb03ce61969`.

Good remediation work is retained. Gate 5.5 / Gate 6 / Gate 7 remain blocked and `live_trading_allowed=false` remains binding.

## Findings

### NODEA-001 — P0: ADJUSTED indicator basis is still compared directly with RAW execution prices

The remediation correctly makes XtQuant acquisition explicit (`front` daily -> ADJUSTED, `none` 5m -> RAW), but the strategy still freezes `DailyBasis.anchor` / `previous_close` from ADJUSTED daily bars and directly compares them with RAW 5m `bar.close` for buy levels, daily-move halt and gap halt.

This is dimensionally wrong around any corporate action / ex-date even though the basis metadata is now explicit. A test where ADJUSTED and RAW happen to have the same numerical scale does not cover this.

Required:
- introduce an explicit, auditable transform from ADJUSTED indicator price domain to the RAW trading-price domain for the active trading day, or otherwise guarantee all values entering a price comparison are on one common basis;
- price-like values (`anchor`, `previous_close`, absolute ATR where used as price) must be transformed consistently; dimensionless values such as ATR% / grid% must remain dimensionless;
- fail closed if a valid same-day basis transform cannot be established;
- add a corporate-action discontinuity test where RAW and ADJUSTED scales differ materially (e.g. 2:1) and prove buy/halt decisions are economically invariant after normalization;
- `BasisBinding` must reject inconsistent metadata such as `dividend_type=front` with `price_basis=RAW`.

### NODEA-002 — P1: released settlement quantity does not carry forward across later trading days

`SettlementTracker` stores released sellable shadow quantity under one trade-date key. If T1 shares bought on Day 1 are released on Day 2 but not sold, Day 3 `sellable_from_released(Day3)` becomes zero because the Day-2 released balance is not carried forward. The same problem exists for unsold T0 released quantity across sessions.

Required:
- model released/sellable shadow quantity as a persistent balance, or explicitly carry it forward across every later eligible session;
- quantities may only decrease by a modeled sell or other explicit lifecycle event;
- tests: Day1 BUY -> Day2 release/no sell -> Day3 SELL remains possible; multiple buys on multiple days; partial sell then later-day remainder; T0 unsold carry-forward.

### NODEA-003 — P1: settlement policy and symbol configuration still guess instead of fail closed

`_settlement_rule_for()` returns T1 for every non-HK symbol. That is not an explicit per-symbol policy and can misclassify T+0 ETFs or unknown markets. In addition, `_load_symbol_and_global()` creates a permissive fallback `SymbolConfig` when the requested symbol is absent from config.

Required:
- real-QMT Gate-5 runner must require an explicit settlement rule from trusted per-symbol configuration or an explicit CLI argument; no suffix/default guess for unknown symbols;
- unknown/missing symbol configuration must fail closed; do not create a synthetic permissive trading config in the real-QMT runner;
- add tests for unknown symbol/policy -> zero QMT strategy execution and explicit failure.

### NODEA-004 — P1: non-zero reconciliation evidence silently reclassifies unexplained holdings

`generate_remediation_evidence.py` computes `strategic_extra = max(0, held - core_qty)`. That automatically labels every broker excess as Strategic, which is exactly the silent reclassification prohibited by INV-006 / AUD-R1-003.

The real-QMT runner takes the opposite shortcut and hard-codes `strategic_extras=0` and `open_t_positions=0`; therefore it does not yet demonstrate reconciliation against a known local real decomposition when Strategic or persisted/open T exists.

Required:
- never infer Strategic/OpenT from broker residual quantity;
- real expected decomposition must come from explicit trusted local state: Core from symbol config plus separately known Strategic and persisted/open real T quantities;
- if any component is unavailable, reconciliation must be UNKNOWN/SAFE_MODE input rather than guessed;
- regenerate the non-zero evidence using a known decomposition supplied independently of broker total;
- commit a sanitized non-zero REAL_QMT evidence summary that proves: evidence class, nonzero broker/local-expected flags, reconciled result, basis, settlement rule, run-days, order/signal counts and artifact hashes, without committing actual holdings/cash/account/path/port values.

### NODEA-005 — P1: `_tmp/` is still tracked in the current GitHub HEAD

`.gitignore` now excludes `_tmp/`, but the existing tracked `_tmp/**` files remain present in snapshot `910a727...`, including old local config/log artifacts. Ignore rules do not remove already-tracked files.

Required:
- remove the entire tracked `_tmp/` tree from the current HEAD using a normal forward commit;
- do not rewrite Git history / force push;
- verify GitHub `contents/_tmp` returns not found after the fix.

### NODEA-006 — P1: canonical control/evidence metadata is still inconsistent

Current canonical state says `git_head_commit: PENDING_PUSH` and reports `818 tests`, while latest remediation commit `910a727...` states `820 tests OK`. `CURRENT_TASK.md` and `docs/GATES.md` also still state 818. `LIVE_VERIFICATION.md` continues to use status text `LIVE VERIFIED` even though the evidence is correctly classified as a historical replay + broker snapshot.

Required:
- choose one exact self-certified regression count and make state/task/docs/report agree;
- record a concrete implementation/evidence commit SHA in the handoff state (no `PENDING_PUSH`);
- use an unambiguous evidence status such as `REAL_QMT_REPLAY_VERIFIED`; reserve `LIVE_SOAK_VERIFIED` for wall-clock continuous evidence;
- final DSH handoff must be `AUDIT_READY`, with no authorization for Gate 5.5.

## Items Independently Accepted in This Iteration

- Explicit XtQuant `dividend_type` binding itself is correct in direction: `front` is requested for adjusted history and `none` for raw prices.
- Evidence-class wording now distinguishes historical replay from continuous live soak.
- Real broker reconciliation and shadow delta are structurally separated in `ShadowEngine`.
- AUD-R1-007 `ExecutionEngine` capacity exact-type hardening is acceptable for this Gate-5 scope.
- No real order/cancel capability was introduced by this remediation; `live_trading_allowed=false` remains intact.
- Gate 6/7 remain blocked.

## Required Verification for Iteration 3

DSH must provide self-certified evidence for:

1. full unit regression + compileall + capability AST scan;
2. basis-domain normalization with a material RAW/ADJUSTED scale discontinuity FI;
3. settlement carry-forward over >=3 trading sessions;
4. explicit settlement policy + unknown symbol/policy fail-closed;
5. non-zero reconciliation with independently supplied Core/Strategic/OpenT components (no residual inference);
6. sanitized REAL_QMT non-zero evidence summary or, if MiniQMT is unavailable, explicitly mark that acceptance item BLOCKED rather than substituting synthetic evidence;
7. GitHub `_tmp/` absent from current HEAD;
8. consistent canonical state/test count/evidence classification.

## Stop Condition — Audit Node A Iteration 3

After these fixes, DSH must push normally, set `state=AUDIT_READY`, record the exact remediation implementation/evidence SHA, and STOP. Do not implement Gate 5.5 and do not introduce real order/cancel capability before independent Node-A PASS.
