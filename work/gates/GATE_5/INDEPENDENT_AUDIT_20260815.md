# Independent Stage Audit — 2026-08-15

## Verdict

`GATE 5 = CHANGES_REQUIRED`  
`GATE 6 / GATE 7 = BLOCKED`

This is an independent audit of GitHub `main` snapshot `2f4957b215beec9f6b6e40054cc6a0375198c29d` after the repository switched to a single programming Agent (`DSH`, architect+implementer combined).

The Gate 2–4 implementation is **not rolled back**. Gate 2/3/4 are treated as provisional/self-certified pending periodic independent audit. Gate 5 is not accepted because the following correctness/control issues are material before any real-order capability is introduced.

## Findings to Fix

### AUD-R1-001 — Deterministic RAW / ADJUSTED market-data basis

`gate5_shadow_live.py` labels daily bars `ADJUSTED` and 5m bars `RAW`, but the XtQuant market-data request does not explicitly bind the adjustment mode.

Required:
- every market-data acquisition used by strategy indicators must explicitly request the intended adjustment mode; no dependence on terminal/client default state;
- daily indicator history and intraday execution-price data must keep separate, auditable basis metadata;
- fail closed on unknown/unsupported basis;
- add tests proving the exact XtQuant arguments and preventing RAW/ADJUSTED mixing.

### AUD-R1-002 — Settlement-aware sellable quantity / T+1

Current live-shadow runner derives `effective_can_use` from total shadow position after a shadow BUY. This can make same-day purchases immediately sellable.

Required:
- separate total position from sellable/can-use position;
- introduce an explicit per-symbol settlement/sellability policy; unknown policy fails closed;
- for instruments that are not same-day sellable, a shadow BUY increases total/effective position but **must not** increase same-day sellable quantity;
- release sellability only when the policy permits (for example next trading day for T+1 products);
- do not hard-code only `510300.SH`; the policy must be explicit and testable for A-share/HK/other configured symbols;
- tests: same-day rebound after BUY cannot create a SELL using newly bought non-sellable quantity; next eligible session can sell; existing broker `can_use` remains usable.

### AUD-R1-003 — Correct Shadow Reconciliation semantics

Current Shadow reconciliation compares shadow delta-like position directly with broker total position. These are different quantities.

Required model:
- `RealBrokerPosition` is reconciled against the local **real expected decomposition** (`Core + Strategic + persisted/open real T`);
- shadow activity is tracked separately as `ShadowDelta` / hypothetical T lots;
- hypothetical/effective strategy position may be `RealBrokerPosition + ShadowDelta`, but this must never be reported as real broker reconciliation;
- expose both real reconciliation and shadow/hypothetical reconciliation explicitly; no silent reclassification;
- test both a zero-base symbol and a symbol with non-zero existing Core/real broker position.

### AUD-R1-004 — Evidence semantics: historical replay != continuous live soak

The 10-day Gate-5 run uses real MiniQMT data/broker connectivity but replays historical 5m bars in one run. Do not describe that as ten wall-clock days of continuous live shadow operation.

Required:
- label evidence precisely, e.g. `REAL_QMT_HISTORICAL_REPLAY + REAL_BROKER_SNAPSHOT`;
- keep real-time/live-soak evidence as a distinct milestone if/when it is executed;
- Gate reports must state exactly which evidence class was used.

### AUD-R1-005 — Repository hygiene / local runtime data

The current HEAD contains many `_tmp/**` local config/log artifacts and Gate-5 reports disclose local QMT paths, endpoint/port and account/position runtime details.

Required:
- remove `_tmp/` artifacts from current HEAD and add `_tmp/` to `.gitignore`;
- ensure `*.local.json`/local runtime files are excluded wherever they are generated, not only under `config/`;
- sanitize committed verification reports: no absolute local userdata path, endpoint/port, account cash, account holdings, account identifiers/fingerprints, secrets or other unnecessary environment details;
- do **not** rewrite Git history or force-push as part of this task. Historical cleanup, if desired, is a separate user decision.

### AUD-R1-006 — Control-plane consistency

Current `WORKFLOW_STATE.yaml`, `CURRENT_TASK.md`, `docs/GATES.md`, Gate-5 review and live-verification semantics disagree.

Required:
- single-agent DSH may self-review, but its verdict must be labelled `SELF_CERTIFIED`, not `independent review`;
- independent ChatGPT audits are recorded separately;
- canonical state must agree on current gate/task/status/test evidence;
- Gate 6/7 must remain blocked until independent audit releases them.

### AUD-R1-007 — Pre-live hardening item for Gate 4 execution inputs

Before a real broker adapter reuses `ExecutionEngine`, remove unsafe coercion patterns on untrusted capacity/quantity inputs (`int(...)`, `float(...)` before exact validation). Preserve the existing fail-closed/malicious-dunder discipline established in Gate 2.

This item may be fixed in this remediation or explicitly carried into the later Gate-5.5 task, but it **must be closed before any real order path is invoked**.

## Gate-5 Remediation Acceptance

DSH must provide:

1. code + tests for AUD-R1-001..003;
2. precise evidence classification for AUD-R1-004;
3. repository/runtime-data cleanup for AUD-R1-005;
4. consistent control/state/report files for AUD-R1-006;
5. status of AUD-R1-007, with tests if fixed now;
6. full unit regression + `compileall` + relevant AST/capability scans;
7. `live_trading_allowed=false` remains binding;
8. no new real `order_stock` / real cancel execution path in this remediation;
9. re-run Gate-5 shadow evidence after fixes, including:
   - one zero-real-position scenario;
   - one non-zero real/Core-position scenario (runtime details must not be committed);
   - explicit settlement-policy evidence;
   - explicit market-data basis evidence.

## Independent Audit Nodes

### AUDIT NODE A — Mandatory next audit

After completing all Gate-5 remediation, DSH must:

- push the remediation to GitHub `main` normally;
- set canonical state to `AUDIT_READY` (or equivalent unambiguous state);
- record the remediation baseline/head, exact tests and evidence;
- **STOP before Gate 5.5 / any live-order adapter work**.

The next independent audit will review the actual diff, new tests, sanitized evidence, RAW/ADJUSTED semantics, settlement/T+1 model, and reconciliation semantics.

### AUDIT NODE B — Mandatory pre-live audit

Only after Node A receives independent PASS may a later task implement a real broker execution adapter / Gate 5.5. Once code contains or is about to introduce real broker order/cancel capability, but **before any real order is invoked**, it must stop for another independent audit covering:

- explicit double live enable/confirmation;
- symbol/qty/cash allowlists and hard limits;
- callback -> Event Queue isolation;
- OrderIntent/Reservation before send;
- partial fills, cancel/re-query, idempotency and crash recovery;
- kill switch;
- exact-type/fail-closed inputs;
- default `live_trading=false`.

Gate 6 cannot start until Node B is independently PASSed and the user explicitly authorizes the tiny-real-money test.
