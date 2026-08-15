"""Gate 6 simulation-trading verification runner (user-authorized, SIMULATION ONLY).

The user explicitly authorized Gate 6 to run against the QMT **simulation**
trading client (which is already started).  This runner is the FIRST real
XtQuant order/cancel invocation of the project — against a SIMULATION account,
never real money.

Flow (matches the reference lifecycle oracle + Gate-5.5 safety boundary):

1. build_live_session(simulation) — connect/discover/subscribe via the
   validated account binding;
2. activate() — mandatory startup recovery + runtime confirmation;
3. fetch a fresh quote for the allowlisted symbol (get_full_tick);
4. place ONE tiny BUY (1 t_unit = 100 shares) with hard caps:
   allowlist, max_order_qty, max_cash_per_order/day, exposure gate,
   EventQueue health, kill switch available;
5. poll/query the order, reconcile broker vs local intent;
6. cancel (if not terminal) -> re-query (never assume zero fill);
7. emit evidence JSON (sanitized: no account ids / balances / paths).

Exit codes: 0 = full loop completed (fill OR cancel+reconcile observed);
non-zero = a safety boundary or unexpected state aborted the run.
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

from tgrid.events import EventQueue
from tgrid.integrations.live_broker_adapter import LiveBrokerPolicy
from tgrid.integrations.live_session import build_live_session
from tgrid.models import GlobalConfig, RootConfig


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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Gate 6 simulation verification")
    parser.add_argument("--gate1-config", default="config/gate1_qmt.local.json")
    parser.add_argument("--symbol", default="510300.SH")
    parser.add_argument("--qty", type=int, default=100, help="one t_unit (100)")
    parser.add_argument("--qty-cap", type=int, default=200)
    parser.add_argument("--cash-cap", type=float, default=5000.0)
    parser.add_argument("--token", default="gate6-sim-token")
    parser.add_argument("--trade-date", default=datetime.now().date().isoformat())
    parser.add_argument("--out", default="work/reports/gate6-sim")
    parser.add_argument("--db", default="")
    args = parser.parse_args(argv)

    project = Path(__file__).resolve().parents[1]
    db = args.db or str(Path(os.environ.get("TMPDIR", project / "work")) / "gate6-sim.db")
    root = RootConfig(
        global_config=GlobalConfig(
            live_trading=True, database=db, log_dir="logs", bar_period="5m",
            order_timeout_seconds=120, skip_open_minutes=15, skip_close_minutes=15,
            volatility_halt_atr=2.5, minimum_cash_buffer=50000.0,
        ),
        symbols={},
    )
    queue = EventQueue(lambda e: None, maxsize=100)
    evidence: dict = {"started_at": datetime.now().astimezone().isoformat()}
    stack = None
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

        stack = build_live_session(
            root_config=root,
            gate1_config_path=str(project / args.gate1_config),
            environment="simulation",
            event_queue=queue,
            policy=_policy(symbol=args.symbol, qty_cap=args.qty_cap, cash_cap=args.cash_cap),
            runtime_confirmation_token=args.token,
            trade_date=args.trade_date,
        )
        evidence["session_built"] = True
        evidence["bridge_constants"] = {
            "security_account_type": stack.bridge._security_account_type,
            "account_status_ok": stack.bridge._account_status_ok,
        }
        # Mandatory startup recovery + runtime confirmation.
        stack.activate(token=args.token)
        evidence["activated"] = True

        # Fresh quote -> tiny BUY.
        from tgrid.integrations.qmt_gate1_runtime import _real_xtdata

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

        # Broker-side reconciliation (authoritative query).
        try:
            broker_view = stack.bridge.query_order(order_id)
            evidence["broker_reconcile"] = {
                "status": broker_view.status,
                "filled_qty": broker_view.filled_qty,
            }
        except Exception as exc:  # noqa: BLE001 - record query outcome
            evidence["broker_reconcile_error"] = f"{type(exc).__name__}: {exc}"

        evidence["terminal_state"] = terminal_seen
        evidence["exposure_used"] = stack.adapter.daily_cash_used
        ok = terminal_seen in ("FILLED", "CANCELED", "REJECTED")
    finally:
        queue.stop()
        queue.join(timeout=1.0)
        if stack is not None:
            try:
                stack._db_conn.close()
            except Exception:  # noqa: BLE001
                pass

    evidence["finished_at"] = datetime.now().astimezone().isoformat()
    return _write_evidence(project, args, evidence, ok=ok)


if __name__ == "__main__":
    sys.exit(main())
