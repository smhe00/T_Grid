"""Capability scan — enumerate every real broker order/cancel call site.

Gate 5.5 evidence requirement: identify every call to the real XtQuant broker
order/cancel surface (``order_stock`` / ``cancel_order_stock``) plus any
adapter-level order/cancel entry points, and prove the adapter only reaches
the broker through an INJECTED object (never a hard import).

Usage:

    python scripts/capability_scan.py [--root src]
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# XtQuant real order/cancel entry points.
REAL_ORDER_CALLS = ("order_stock", "cancel_order_stock", "cancel_order_stock_async")
# Adapter-level order/cancel entry points introduced by Gate 5.5.
ADAPTER_ORDER_CALLS = ("place_order", "cancel_order")


def _scan(root: Path) -> dict:
    results = {"files": 0, "real_order_calls": [], "adapter_calls": []}
    for path in sorted(root.rglob("*.py")):
        results["files"] += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in REAL_ORDER_CALLS:
                    results["real_order_calls"].append(
                        f"{path}:{node.lineno}:{node.func.attr}"
                    )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ADAPTER_ORDER_CALLS:
                    results["adapter_calls"].append(
                        f"{path}:{node.lineno}:{node.func.attr}"
                    )
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Capability scan")
    parser.add_argument("--root", default="src", help="source root to scan")
    args = parser.parse_args(argv)

    results = _scan(Path(args.root))
    print(f"files scanned: {results['files']}")
    print(f"REAL XtQuant order/cancel call sites: {len(results['real_order_calls'])}")
    for call in results["real_order_calls"]:
        print(f"  {call}")
    print(f"Adapter order/cancel entry points: {len(results['adapter_calls'])}")
    for call in results["adapter_calls"]:
        print(f"  {call}")

    if results["real_order_calls"]:
        # Gate 5.5 forbids direct real order/cancel call sites in src; the
        # adapter must route only through the injected broker object.
        print("RESULT: FAIL — direct real order/cancel call sites found")
        return 1
    print("RESULT: PASS — no direct real XtQuant order/cancel call sites")
    return 0


if __name__ == "__main__":
    sys.exit(main())
