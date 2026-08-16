# Architect Audit — Core 0.4.1 Runtime Authority Candidate

Reviewed Core branch:

```text
feature/0.4.1-runtime-authority
d4992543b7aa2496b2ba3fb7cd51b5cc74192a00
```

Result: **CHANGES_REQUIRED**.

The candidate's Runtime Authority, DB UUID binding, cross-process bootstrap lock and 108-test result are retained as the regression baseline. Three P1 production-safety gaps remain:

1. `MiniQmtRuntimeConfig.authority_root` is strategy/runtime configurable, so the same account can select two roots and bootstrap two Authority/DB domains.
2. Normal `MiniQmtRuntime.connect()` calls Authority resolution with `bootstrap=True`; if both an established Authority and its DB are deleted, a normal strategy restart can silently create a new empty coordination domain. Normal runtime must verify only (`bootstrap=False`); initialization must be an explicit operator action.
3. `MiniQmtRuntimeConfig.coordination_path` remains a normal production shared-runtime bypass that directly constructs a legacy coordinator and skips Authority verification. Low-level/test explicit-path support may remain, but not as the production MiniQMT shared-runtime configuration route.

P2:
- recompute account_key from environment/account_type/account_id_sha256 inside Authority resolution and verify equality;
- enforce/validate exactly one Authority identity row in the dedicated DB;
- document fail-closed orphan DB recovery after crash between DB creation and Authority replace.

Authoritative detailed review and revised implementation task are committed on the Core feature branch:

```text
docs/ARCHITECT_AUDIT_V0_4_1_RUNTIME_AUTHORITY.md
docs/IMPLEMENTATION_TASK_V0_4_1_RUNTIME_AUTHORITY.md
```

Do not merge `d4992543...`. No TGrid production adaptation and no Gate-6 simulation order/cancel until a revised Core candidate passes independent audit and is merged with an exact locked SHA.
