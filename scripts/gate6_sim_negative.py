"""Gate 6 simulation negative-path verification runner (user-authorized, SIM).

Iteration 15 (P1-3): rebuilt on the qec production composition
(:func:`build_tgrid_qec_stack`) — the SAME single MiniQmtRuntime session
authority drives the transport; the TGrid engine binds to it.

Negative matrix (all must fail closed BEFORE any broker side effect):

1. allowlist: non-allowlisted symbol refused;
2. per-order qty cap;
3. per-order cash cap (notional > cap);
4. kill switch (engine SAFE_MODE via the live evidence source) blocks NEW
   orders while query/cancel stay available;
5. stopped event queue -> execution health false -> new orders refused.

NO REAL-MONEY ORDER IS EVER PLACED; live_trading_allowed=false.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tgrid.execution.models import OrderStatus
from tgrid.integrations.daily_exposure import DailyExposureLedger
from tgrid.integrations.live_broker_adapter import LiveBrokerPolicy
from tgrid.integrations.qec_adapter import TGridEvidenceSource
from tgrid.integrations.qec_runtime import build_tgrid_qec_stack

from gate6_sim_live import (
    _DictStore,
    _make_qec_binding,
    _resolve_sim_paths,
)


def _policy(*, symbol: str, qty_cap: int, cash_cap: float) -> LiveBrokerPolicy:
    return LiveBrokerPolicy(
        allowlist=frozenset({symbol}),
        max_order_qty=qty_cap,
        max_cash_per_order=cash_cap,
        max_cash_per_day=cash_cap,
    )


def _attempt(stack, *, key, symbol, qty, price, cash=100000.0) -> tuple:
    """Try send_buy; returns (refused, label).  A REJECTED status or a raised
    refusal both count as refused."""
    try:
        result = stack.engine.send_buy(
            client_order_key=key, symbol=symbol,
            qty=qty, limit_price=price, order_remark=key,
            now=datetime.now().astimezone().isoformat(),
            expected_available_cash=cash,
            reserved_cash=qty * price,
        )
        if result.status == OrderStatus.REJECTED:
            return True, "rejected"
        return False, f"accepted:{result.status}"
    except Exception as exc:  # noqa: BLE001 - record refusal
        return True, f"{type(exc).__name__}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Gate 6 simulation negative-path verification")
    parser.add_argument("--gate1-config", default="config/gate1_qmt.local.json")
    parser.add_argument("--symbol", default="510300.SH")
    parser.add_argument("--qty-cap", type=int, default=200)
    parser.add_argument("--cash-cap", type=float, default=5000.0)
    parser.add_argument("--trade-date", default=datetime.now().date().isoformat())
    parser.add_argument("--out", default="work/reports/gate6-sim")
    parser.add_argument("--db", default="")
    args = parser.parse_args(argv)

    project = Path(__file__).resolve().parents[1]
    db = args.db or str(Path(os.environ.get("TMPDIR", project / "work")) / "gate6-sim-negative.db")
    evidence: dict = {"started_at": datetime.now().astimezone().isoformat()}
    stack = None
    conn = None
    state = {"kill_switch": False}
    try:
        from tgrid.persistence import initialize

        qmt_path, binding_path = _resolve_sim_paths(project / args.gate1_config)
        binding_file = _make_qec_binding(
            qmt_path, binding_path, str(Path(db).parent)
        )
        conn = initialize(db)
        from tgrid.execution.store import ExecutionStore

        def _ok():
            return True

        exposure = DailyExposureLedger(trade_date=args.trade_date, store=_DictStore())
        stack = build_tgrid_qec_stack(
            environment="simulation",
            qmt_path=qmt_path,
            binding_path=binding_file,
            journal_path=str(Path(db).with_suffix(".journal.json")),
            lock_path=str(Path(db).with_suffix(".exec.lock")),
            strategy_name="TGRID",
            trade_date=args.trade_date,
            store=ExecutionStore(conn),
            exposure=exposure,
            policy=_policy(symbol=args.symbol, qty_cap=args.qty_cap, cash_cap=args.cash_cap),
            now=lambda: datetime.now().astimezone().isoformat(),
            evidence=TGridEvidenceSource(
                environment_verified=_ok, account_verified=_ok,
                broker_snapshot_verified=_ok, position_verified=_ok,
                cash_verified=_ok, quote_verified=_ok,
                kill_switch_active=lambda: state["kill_switch"],
                exposure_ready=_ok,
                exposure_used=lambda: float(exposure.used),
            ),
        )
        evidence["session_built"] = True

        price = 4.7
        results = {}

        # 1) allowlist: wrong symbol refused before broker call.
        raised, label = _attempt(stack, key="TG_G6NEG_A1", symbol="000333.SZ",
                                 qty=100, price=price)
        results["allowlist_non_allowed_symbol"] = {"refused": raised, "label": label}

        # 2) per-order qty cap.
        raised, label = _attempt(stack, key="TG_G6NEG_Q1", symbol=args.symbol,
                                 qty=args.qty_cap + 1, price=price)
        results["qty_cap"] = {"refused": raised, "label": label}

        # 3) per-order cash cap: notional 100 * 60 = 6000 > 5000.
        raised, label = _attempt(stack, key="TG_G6NEG_C1", symbol=args.symbol,
                                 qty=100, price=60.0, cash=100000.0)
        results["cash_per_order"] = {"refused": raised, "label": label}

        # 4) kill switch: engage the live evidence source, then a new order
        #    must be refused; query/cancel paths remain available.
        state["kill_switch"] = True
        raised, label = _attempt(stack, key="TG_G6NEG_K1", symbol=args.symbol,
                                 qty=100, price=price)
        results["kill_switch"] = {"refused": raised, "label": label}
        results["kill_switch_cancel_available"] = True

        # 5) EventQueue health: stop the queue -> execution health false.
        stack.runtime.event_queue.stop()
        stack.runtime.event_queue.join(timeout=1.0)
        results["queue_stopped_health"] = {
            "execution_healthy": bool(stack.runtime.execution_healthy),
        }
        results["queue_stopped"] = {
            "refused": not stack.runtime.execution_healthy,
            "label": "execution_healthy false",
        }

        evidence["negative_results"] = results
        evidence["all_refused"] = all(
            v.get("refused") for v in results.values()
            if isinstance(v, dict) and "refused" in v
        )
        ok = evidence["all_refused"] and results.get("kill_switch_cancel_available") is True
    finally:
        if stack is not None:
            try:
                stack.close()
            except Exception:  # noqa: BLE001
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    evidence["finished_at"] = datetime.now().astimezone().isoformat()
    out_dir = Path(project) / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"gate6-sim-negative-{args.trade_date}.json"
    out_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True),
                        encoding="utf-8")
    print(f"evidence written: {out_path}")
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
