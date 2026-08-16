# Architect Audit — Core 0.4.1 Runtime Authority Rev2

## Candidate

```text
qmt-execution-core
feature/0.4.1-runtime-authority
54b2cbea09a3d5707a12861bb65964141e1cf0fd
```

## Verdict

**CHANGES_REQUIRED**

Rev2 correctly removed the production `coordination_path` / `authority_root` fields and changed normal runtime to verify-only (`bootstrap=False`). It also added explicit bootstrap, identity-tuple recomputation and exactly-one DB identity-row enforcement.

One P1 uniqueness blocker remains.

### P1 — Windows canonical Authority root is still process-overridable

`default_authority_root()` still reads `os.environ["LOCALAPPDATA"]`. Two processes under the same Windows user can therefore carry different `LOCALAPPDATA` values and resolve different Authority roots for the same `account_key`, reopening split-brain.

Required Core Rev3:

- Windows root from OS Known Folder API (`FOLDERID_LocalAppData` / equivalent), never process environment;
- no env/home fallback; root lookup failure fails closed;
- POSIX user-home from OS user database; failure fails closed;
- remove `--authority-root` from production `bootstrap-authority` CLI so bootstrap and runtime use exactly the same canonical resolver;
- add Windows mutable-`LOCALAPPDATA` and cross-process regressions;
- open PR and run Python 3.9/3.11/3.12 + Windows CI + existing formal release gate.

Authoritative Core audit/task:

```text
docs/ARCHITECT_AUDIT_V0_4_1_RUNTIME_AUTHORITY_REV2.md
docs/IMPLEMENTATION_TASK_V0_4_1_RUNTIME_AUTHORITY_REV3.md
```

TGrid remains pinned to reviewed Core 0.4.0 `acf20d9...`. Do not adapt TGrid or run Gate-6 simulation orders until Core Rev3 passes independent audit, is merged, and its exact merge SHA is locked.

`live_trading_allowed=false`.
