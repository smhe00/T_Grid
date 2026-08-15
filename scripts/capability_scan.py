"""Capability scan — enumerate and ALLOWLIST real broker order/cancel call sites.

NODEB-001 requirement 5: the ONLY permitted real XtQuant order/cancel call
sites in the repository are the concrete bridge's — exactly
``src/tgrid/integrations/xtquant_bridge.py`` (``place_order`` ->
``order_stock``, ``cancel_order`` -> ``cancel_order_stock``).  Any direct
real-broker invocation ANYWHERE ELSE fails the scan, so a stray real-order
capability cannot be introduced silently.

Adapter-level entry points (``place_order`` / ``cancel_order``) are also
enumerated for the report.

Usage:

    python scripts/capability_scan.py [--root src]
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# The ONLY file allowed to contain real XtQuant order/cancel calls.
ALLOWED_BRIDGE = Path("src/tgrid/integrations/xtquant_bridge.py")

# XtQuant real order/cancel entry points.
REAL_ORDER_CALLS = ("order_stock", "cancel_order_stock", "order_stock_async", "cancel_order_stock_async")
# Adapter-level order/cancel entry points introduced by Gate 5.5.
ADAPTER_ORDER_CALLS = ("place_order", "cancel_order")


def _scan(root: Path) -> dict:
    results = {
        "files": 0,
        "real_order_calls": [],  # (path, lineno, name) — must all be in ALLOWED_BRIDGE
        "bridge_calls": [],  # real calls inside the allowed bridge
        "adapter_calls": [],
    }
    bridge_str = ALLOWED_BRIDGE.as_posix()
    for path in sorted(root.rglob("*.py")):
        results["files"] += 1
        rel = path.as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in REAL_ORDER_CALLS:
                    entry = f"{rel}:{node.lineno}:{node.func.attr}"
                    if rel == bridge_str:
                        results["bridge_calls"].append(entry)
                    else:
                        results["real_order_calls"].append(entry)
                if node.func.attr in ADAPTER_ORDER_CALLS:
                    results["adapter_calls"].append(f"{rel}:{node.lineno}:{node.func.attr}")
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Capability scan")
    parser.add_argument("--root", default="src", help="source root to scan")
    args = parser.parse_args(argv)

    results = _scan(Path(args.root))
    bridge_str = ALLOWED_BRIDGE.as_posix()
    print(f"files scanned: {results['files']}")
    print(f"allowed bridge file: {bridge_str}")
    print(f"REAL XtQuant order/cancel call sites OUTSIDE the bridge: {len(results['real_order_calls'])}")
    for call in results["real_order_calls"]:
        print(f"  {call}")
    print(f"REAL XtQuant order/cancel call sites INSIDE the bridge (allowlisted): {len(results['bridge_calls'])}")
    for call in results["bridge_calls"]:
        print(f"  {call}")
    print(f"Adapter order/cancel entry points: {len(results['adapter_calls'])}")
    for call in results["adapter_calls"]:
        print(f"  {call}")

    if results["real_order_calls"]:
        print("RESULT: FAIL — direct real order/cancel call sites OUTSIDE the bridge")
        return 1
    if not results["bridge_calls"]:
        print("RESULT: FAIL — the allowed bridge contains no real order/cancel call sites")
        return 1
    print("RESULT: PASS — all real XtQuant order/cancel calls are inside the bridge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
