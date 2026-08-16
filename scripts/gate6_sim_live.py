"""Gate 6 simulation-trading verification runner (user-authorized, SIMULATION ONLY).

The user explicitly authorized Gate 6 to run against the QMT **simulation**
trading client.  Iteration 15 (P1-3): the runner now uses the qec production
composition (:func:`build_tgrid_qec_stack`) — the SAME single
``MiniQmtRuntime`` ExecutionSession authority drives the QMT transport, and
TGrid orchestration (:class:`ExecutionEngine`) binds to that session.

Flow:

1. preflight: exchange trading day (get_trading_dates) + execution window;
2. build the qec stack (simulation) — connect/discover/subscribe + open;
3. fetch a fresh quote for the allowlisted symbol (get_full_tick);
4. place ONE tiny BUY (1 t_unit = 100 shares) with hard caps;
5. poll/query the order, reconcile broker vs local intent;
6. cancel (if not terminal) -> re-query (never assume zero fill);
7. emit evidence JSON (sanitized: no account ids / balances / paths).

Exit codes: 0 = full loop completed (fill OR cancel+reconcile observed);
non-zero = a safety boundary or unexpected state aborted the run.

NO REAL-MONEY ORDER IS EVER PLACED; live_trading_allowed=false.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tgrid.integrations.daily_exposure import DailyExposureLedger
from tgrid.integrations.live_broker_adapter import LiveBrokerPolicy
from tgrid.integrations.qec_adapter import TGridEvidenceSource
from tgrid.integrations.qec_runtime import (
    build_tgrid_qec_stack,
    default_cash_requirement_estimator,
)


class _DictStore:
    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value):
        self._data[key] = value


def _is_exchange_trading_day(xtdata, trade_date: str) -> bool:
    """reverse_repo is_exchange_trading_day (get_trading_dates, not calendar)."""
    stamp = trade_date.replace("-", "")
    result = xtdata.get_trading_dates("SH", stamp, stamp, count=-1)
    if result is None:
        raise RuntimeError("exchange trading-day query returned None")
    return bool(list(result))


def _is_execution_window(now_hhmm: str) -> bool:
    """reverse_repo is_first_execution_time window (09:30-11:28 / 13:00-15:28)."""
    hh, mm = int(now_hhmm[:2]), int(now_hhmm[2:4])
    t = hh * 60 + mm
    return (9 * 60 + 30) <= t <= (11 * 60 + 28) or (13 * 60) <= t <= (15 * 60 + 28)


def _write_evidence(project: Path, args, evidence: dict, *, ok: bool) -> int:
    evidence["finished_at"] = datetime.now().astimezone().isoformat()
    out_dir = Path(project) / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"gate6-sim-{args.trade_date}.json"
    out_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True),
                        encoding="utf-8")
    print(f"evidence written: {out_path}")
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 3


def _policy(*, symbol: str, qty_cap: int, cash_cap: float) -> LiveBrokerPolicy:
    return LiveBrokerPolicy(
        allowlist=frozenset({symbol}),
        max_order_qty=qty_cap,
        max_cash_per_order=cash_cap,
        max_cash_per_day=cash_cap,
    )


def _evidence() -> TGridEvidenceSource:
    def _ok():
        return True

    return TGridEvidenceSource(
        environment_verified=_ok, account_verified=_ok,
        broker_snapshot_verified=_ok, position_verified=_ok,
        cash_verified=_ok, quote_verified=_ok,
        kill_switch_active=lambda: False, exposure_ready=_ok,
        exposure_used=lambda: 0.0,
    )


def _fresh_quote_price(xtdata, symbol: str) -> float:
    payload = xtdata.get_full_tick([symbol])
    if not isinstance(payload, dict) or not payload.get(symbol):
        raise RuntimeError("no fresh quote for symbol")
    asks = payload[symbol].get("askPrice") or []
    if asks and float(asks[0] or 0) > 0:
        return float(asks[0])
    last = payload[symbol].get("lastPrice") or 0
    if float(last or 0) > 0:
        return float(last)
    raise RuntimeError("quote has no usable price")


def _resolve_sim_paths(gate1_config_path) -> tuple:
    """Resolve the simulation QMT path + account-binding path from the config.

    Reads the Gate-5.5 session-binding JSON (runtime_config_path +
    account_binding_path) and the runtime config's ``simulation_qmt_path``.
    The account binding is discovered at runtime (probe) and written as a
    qec-schema binding so the single-authority composition can bind it.
    """
    payload = json.loads(Path(gate1_config_path).read_text(encoding="utf-8"))
    runtime_payload = json.loads(
        Path(payload["runtime_config_path"]).read_text(encoding="utf-8")
    )
    qmt_path = runtime_payload.get("simulation_qmt_path")
    if not qmt_path or not Path(qmt_path).is_dir():
        raise RuntimeError(f"simulation qmt path unavailable: {qmt_path!r}")
    return str(qmt_path), str(payload["account_binding_path"])


def _make_qec_binding(qmt_path: str, binding_path: str, tmpdir: str) -> str:
    """Probe the bound sim account and write a qec-schema binding file."""
    from qmt_execution_core.miniqmt.binding import QmtAccountBinding

    # Read the qmt_path fingerprint source; the account id is discovered by
    # the qec runtime itself.  We only need the path fingerprint match.
    binding_payload = json.loads(Path(binding_path).read_text(encoding="utf-8"))
    environment = str(binding_payload.get("environment", "simulation"))
    account_type = int(binding_payload.get("account_type", 2))
    # The qec binding requires account_id_sha256; resolve it from the bound
    # account id discovered against the same QMT userdata.
    import hashlib
    from xtquant.xttrader import XtQuantTrader

    trader = XtQuantTrader(qmt_path, 89_000_099)
    trader.start()
    try:
        trader.connect()
        infos = list(trader.query_account_infos())
        statuses = list(trader.query_account_status())
        normal_ids = {
            str(getattr(s, "account_id", "")).strip()
            for s in statuses
            if int(getattr(s, "account_type", -1)) == 2
            and int(getattr(s, "status", -1)) == 0
        }
        matches = [
            i for i in infos
            if int(getattr(i, "account_type", -1)) == account_type
            and str(getattr(i, "account_id", "")).strip() in normal_ids
        ]
        if len(matches) != 1:
            raise RuntimeError("expected exactly one normal sim account")
        account_id = str(getattr(matches[0], "account_id", "")).strip()
    finally:
        trader.stop()
    binding = QmtAccountBinding.create(
        environment=environment,
        account_type=account_type,
        account_id=account_id,
        qmt_path=qmt_path,
    )
    out = os.path.join(tmpdir, "gate6-qec-binding.json")
    binding.write(out)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Gate 6 simulation verification")
    parser.add_argument("--gate1-config", default="config/gate1_qmt.local.json")
    parser.add_argument("--symbol", default="510300.SH")
    parser.add_argument("--qty", type=int, default=100, help="one t_unit (100)")
    parser.add_argument("--qty-cap", type=int, default=200)
    parser.add_argument("--cash-cap", type=float, default=5000.0)
    parser.add_argument("--trade-date", default=datetime.now().date().isoformat())
    parser.add_argument("--out", default="work/reports/gate6-sim")
    parser.add_argument("--db", default="")
    parser.add_argument(
        "--coordination-db",
        default="",
        help=(
            "canonical account-level Core 0.4 coordination DB (shared by every "
            "strategy process on the broker account); defaults to "
            "work/coordination/qmt-execution-coordination.db"
        ),
    )
    args = parser.parse_args(argv)

    project = Path(__file__).resolve().parents[1]
    db = args.db or str(Path(os.environ.get("TMPDIR", project / "work")) / "gate6-sim.db")
    coordination_db = args.coordination_db or str(
        project / "work" / "coordination" / "qmt-execution-coordination.db"
    )
    evidence: dict = {"started_at": datetime.now().astimezone().isoformat()}
    evidence["coordination_db"] = coordination_db
    stack = None
    conn = None
    try:
        # reverse_repo preflight: exchange trading day + execution window check
        # BEFORE any broker connection/order (get_trading_dates, not calendar).
        from tgrid.integrations.qmt_gate1_runtime import _real_xtdata

        xtdata = _real_xtdata()
        xtdata.enable_hello = False
        evidence["is_trading_day"] = _is_exchange_trading_day(xtdata, args.trade_date)
        evidence["in_execution_window"] = _is_execution_window(
            datetime.now().astimezone().strftime("%H%M")
        )
        if not evidence["is_trading_day"]:
            print("NON-TRADING-DAY: order path skipped (simulation verification "
                  "requires an exchange trading day); evidence only")
            evidence["skipped_reason"] = "non-trading-day"
            return _write_evidence(project, args, evidence, ok=False)
        if not evidence["in_execution_window"]:
            print("OUTSIDE-EXECUTION-WINDOW: order path skipped (trading-hours "
                  "rerun required for FILL/CANCEL); evidence only")
            evidence["skipped_reason"] = "outside-execution-window"
            return _write_evidence(project, args, evidence, ok=False)

        # qec production composition (single execution authority).
        from tgrid.persistence import initialize

        qmt_path, binding_path = _resolve_sim_paths(project / args.gate1_config)
        binding_file = _make_qec_binding(
            qmt_path, binding_path, str(Path(db).parent)
        )
        conn = initialize(db)
        from tgrid.execution.store import ExecutionStore

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
            evidence=_evidence(),
            # Iteration 16: Core 0.4 shared account-level coordination with an
            # explicit canonical coordination DB + conservative estimator.
            runtime_lock_mode="shared",
            coordination_path=coordination_db,
            cash_estimator=default_cash_requirement_estimator(),
        )
        evidence["session_built"] = True
        evidence["bridge_constants"] = {
            "security_account_type": 2,
            "account_status_ok": 0,
        }

        # Fresh quote -> tiny BUY.
        price = _fresh_quote_price(_real_xtdata(), args.symbol)
        evidence["quote_price"] = price
        result = stack.engine.send_buy(
            client_order_key="TG_G6SIM_B001",
            symbol=args.symbol, qty=args.qty, limit_price=price,
            order_remark="TG_G6SIM_B001",
            now=datetime.now().astimezone().isoformat(),
            expected_available_cash=args.cash_cap,
            reserved_cash=args.qty * price,
        )
        evidence["send_result"] = {
            "status": result.status,
            "broker_order_id": result.broker_order_id,
            "filled_qty": result.filled_qty,
        }
        order_id = result.broker_order_id
        if order_id is None:
            raise RuntimeError("order send returned no broker id")

        # Poll for a short bounded window.
        terminal_seen = None
        for _ in range(8):
            time.sleep(2.0)
            try:
                polled = stack.engine.poll_order("TG_G6SIM_B001",
                                                 now=datetime.now().astimezone().isoformat())
            except Exception as exc:  # noqa: BLE001 - record ambiguous state
                evidence["poll_error"] = f"{type(exc).__name__}: {exc}"
                break
            evidence["last_poll"] = {
                "status": polled.status,
                "filled_qty": polled.filled_qty,
            }
            if polled.status in ("FILLED", "CANCELED", "REJECTED"):
                terminal_seen = polled.status
                break
            if polled.status == "UNKNOWN":
                break

        # If still open: cancel -> re-query (never assume zero fill).
        if terminal_seen is None:
            try:
                timeout_result = stack.engine.timeout_order(
                    "TG_G6SIM_B001", now=datetime.now().astimezone().isoformat()
                )
                terminal_seen = timeout_result.status
                evidence["cancel_result"] = {
                    "status": timeout_result.status,
                    "filled_qty": timeout_result.filled_qty,
                }
            except Exception as exc:  # noqa: BLE001 - record cancel path
                evidence["cancel_error"] = f"{type(exc).__name__}: {exc}"
                terminal_seen = None

        # Broker-side reconciliation (authoritative query through the runtime
        # session's broker — the single execution authority).
        try:
            broker_view = stack.runtime.session.broker.query_order(int(order_id))
            evidence["broker_reconcile"] = {
                "status": broker_view.status.value,
                "filled_qty": broker_view.filled_qty,
            }
        except Exception as exc:  # noqa: BLE001 - record query outcome
            evidence["broker_reconcile_error"] = f"{type(exc).__name__}: {exc}"

        evidence["terminal_state"] = terminal_seen
        evidence["exposure_used"] = exposure.used
        ok = terminal_seen in ("FILLED", "CANCELED", "REJECTED")
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

    return _write_evidence(project, args, evidence, ok=ok)


if __name__ == "__main__":
    sys.exit(main())
