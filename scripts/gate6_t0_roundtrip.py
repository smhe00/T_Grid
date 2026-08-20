"""Gate-6.2 T+0 intraday roundtrip runner — QMT SIMULATION ONLY.

Validates one complete TGrid + Core execution roundtrip on 513100.SH
(SSE 纳指ETF, T+0 eligible) within the exact Gate-6.2 authorization:

    BUY exactly 100 -> FILLED -> SELL the same 100 -> FILLED
    max BUY notional 2000 CNY
    max 2 broker submits (1 BUY + 1 SELL), max 2 cancels
    no third order, no live calls, no production src/Core changes

Outcome codes: ROUNDTRIP_PASS | BLOCKED_PRE_BROKER | BUY_NOT_RESOLVED |
T0_SELL_BLOCKED_BY_TGRID | SELL_NOT_RESOLVED | INVARIANT_FAIL
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT / "src"))
sys.path.insert(0, str(_PROJECT / "scripts"))

from gate6_sim_live import (  # noqa: E402
    _DictStore,
    _evidence,
    _policy,
    _resolve_sim_paths,
    _make_qec_binding,
)
from tgrid.integrations.daily_exposure import DailyExposureLedger  # noqa: E402
from tgrid.integrations.qec_runtime import (  # noqa: E402
    build_tgrid_qec_stack,
    default_cash_requirement_estimator,
)
from tgrid.persistence import initialize  # noqa: E402
from tgrid.execution.store import ExecutionStore  # noqa: E402

SYMBOL = "513100.SH"
QTY = 100
MAX_BUY_NOTIONAL = 2000.0
OUTCOME = {"code": "BLOCKED_PRE_BROKER", "reason": "not started"}
COUNTS = {
    "sim_buy_submits": 0, "sim_sell_submits": 0, "sim_cancels": 0,
    "live_order_calls": 0, "live_cancel_calls": 0, "product_src_changes": 0,
}
EVIDENCE = {"preflight": {}, "legA": {}, "legB": {}, "final": {}}


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _in_window() -> bool:
    now = datetime.now().astimezone()
    t = now.hour * 60 + now.minute
    return (9 * 60 + 30) <= t <= (11 * 60 + 30) or (13 * 60) <= t <= (15 * 60)


def _fresh_quote(xtdata, symbol):
    payload = xtdata.get_full_tick([symbol])
    tick = payload.get(symbol) if isinstance(payload, dict) else None
    if not tick:
        raise RuntimeError("no tick for symbol")
    bid1 = float(tick.get("bidPrice")[0] or 0) if tick.get("bidPrice") else 0.0
    ask1 = float(tick.get("askPrice")[0] or 0) if tick.get("askPrice") else 0.0
    last = float(tick.get("lastPrice") or 0)
    ts = tick.get("time") or tick.get("lastTime") or 0
    return {
        "bid1": bid1, "ask1": ask1, "last": last, "time": ts,
        "spread": ask1 - bid1,
    }


def main() -> int:
    global OUTCOME
    evidence = EVIDENCE
    # ---- Preflight: window + quote + account/claim safety ----
    evidence["preflight"]["now"] = _now()
    evidence["preflight"]["in_window"] = _in_window()
    if not _in_window():
        OUTCOME = {"code": "BLOCKED_PRE_BROKER", "reason": "outside continuous auction window"}
        _dump(evidence)
        return 0

    from tgrid.integrations.qmt_gate1_runtime import _real_xtdata

    xtdata = _real_xtdata()
    xtdata.enable_hello = False
    try:
        quote = _fresh_quote(xtdata, SYMBOL)
    except Exception as exc:  # noqa: BLE001
        OUTCOME = {"code": "BLOCKED_PRE_BROKER", "reason": f"quote unavailable: {exc}"}
        _dump(evidence)
        return 0
    evidence["preflight"]["quote"] = quote
    if quote["ask1"] <= 0 or quote["bid1"] <= 0 or quote["ask1"] < quote["bid1"]:
        OUTCOME = {"code": "BLOCKED_PRE_BROKER", "reason": "quote invalid (bid/ask)"}
        _dump(evidence)
        return 0
    if QTY * quote["ask1"] > MAX_BUY_NOTIONAL:
        OUTCOME = {"code": "BLOCKED_PRE_BROKER", "reason": "BUY notional exceeds 2000 CNY"}
        _dump(evidence)
        return 0

    qmt_path, _ = _resolve_sim_paths(_PROJECT / "config" / "gate1_qmt.local.json")
    binding_file = _make_qec_binding(qmt_path, str(_PROJECT / "config" / "gate1_qmt.local.json"), str(_PROJECT / "work"))
    db = str(_PROJECT / "work" / "gate62-t0.db")
    conn = initialize(db)
    store = ExecutionStore(conn)
    exposure = DailyExposureLedger(trade_date="2026-08-20", store=_DictStore())
    stack = build_tgrid_qec_stack(
        environment="simulation", qmt_path=qmt_path, binding_path=binding_file,
        journal_path=str(_PROJECT / "work" / "gate62-t0.journal.json"),
        lock_path=str(_PROJECT / "work" / "gate62-t0.exec.lock"),
        strategy_name="G62-T0", trade_date="2026-08-20",
        store=store, exposure=exposure,
        policy=_policy(symbol=SYMBOL, qty_cap=QTY, cash_cap=MAX_BUY_NOTIONAL),
        now=lambda: datetime.now().astimezone().isoformat(),
        evidence=_evidence(), cash_estimator=default_cash_requirement_estimator(),
    )
    evidence["preflight"]["session_built"] = True
    try:
        # ---- Leg A: BUY 100 ----
        buy_price = round(quote["ask1"] * 1.001, 3)
        buy_notional = QTY * buy_price
        evidence["legA"]["buy_price"] = buy_price
        evidence["legA"]["buy_notional"] = buy_notional
        if buy_notional > MAX_BUY_NOTIONAL:
            OUTCOME = {"code": "BLOCKED_PRE_BROKER", "reason": "BUY notional would exceed 2000"}
            _dump(evidence)
            return 0
        COUNTS["sim_buy_submits"] += 1
        r = stack.engine.send_buy(
            client_order_key="TG_G62_A", symbol=SYMBOL, qty=QTY,
            limit_price=buy_price, order_remark="TG_G62_A", now=_now(),
            expected_available_cash=MAX_BUY_NOTIONAL, reserved_cash=buy_notional,
        )
        evidence["legA"]["submit"] = {
            "status": r.status, "broker_order_id": r.broker_order_id,
            "filled_qty": r.filled_qty,
        }
        state = r.status
        for _ in range(10):
            if state in ("FILLED", "CANCELED", "REJECTED"):
                break
            time.sleep(1.5)
            state = stack.engine.poll_order("TG_G62_A", now=_now()).status
        evidence["legA"]["final_state"] = state
        if state != "FILLED" or store.get_intent("TG_G62_A").filled_qty != QTY:
            OUTCOME = {"code": "BUY_NOT_RESOLVED", "reason": f"BUY final state {state}"}
            _dump(evidence)
            return 0
        # position check (same-day sellable)
        positions = stack.runtime.session.broker.query_positions()
        pos = next((p for p in positions if p.symbol == SYMBOL), None)
        evidence["legA"]["position"] = {
            "volume": int(pos.volume) if pos else None,
            "can_use": int(pos.can_use_volume) if pos else None,
        }
        if pos is None or int(pos.can_use_volume) < QTY:
            OUTCOME = {"code": "T0_SELL_BLOCKED_BY_TGRID",
                       "reason": "same-day sell quantity not available via normal stack"}
            _dump(evidence)
            return 0

        # ---- Leg B: SELL the same 100 ----
        fresh = _fresh_quote(xtdata, SYMBOL)
        evidence["legB"]["quote"] = fresh
        if fresh["bid1"] <= 0:
            OUTCOME = {"code": "SELL_NOT_RESOLVED", "reason": "no fresh bid"}
            _dump(evidence)
            return 0
        sell_price = round(fresh["bid1"] * 0.999, 3)
        evidence["legB"]["sell_price"] = sell_price
        COUNTS["sim_sell_submits"] += 1
        r = stack.engine.send_sell(
            client_order_key="TG_G62_B", symbol=SYMBOL, qty=QTY,
            limit_price=sell_price, order_remark="TG_G62_B", now=_now(),
            expected_available_qty=QTY,
        )
        evidence["legB"]["submit"] = {
            "status": r.status, "broker_order_id": r.broker_order_id,
            "filled_qty": r.filled_qty,
        }
        state = r.status
        for _ in range(10):
            if state in ("FILLED", "CANCELED", "REJECTED"):
                break
            time.sleep(1.5)
            state = stack.engine.poll_order("TG_G62_B", now=_now()).status
        evidence["legB"]["final_state"] = state
        if state != "FILLED" or store.get_intent("TG_G62_B").filled_qty != QTY:
            OUTCOME = {"code": "SELL_NOT_RESOLVED", "reason": f"SELL final state {state}"}
            _dump(evidence)
            return 0

        # ---- Final reconciliation ----
        evidence["final"]["position"] = {
            "volume": int(pos.volume) if (pos := next((p for p in stack.runtime.session.broker.query_positions() if p.symbol == SYMBOL), None)) else None,
            "can_use": int(pos.can_use_volume) if (pos := next((p for p in stack.runtime.session.broker.query_positions() if p.symbol == SYMBOL), None)) else None,
        }
        evidence["final"]["intents"] = [
            {"key": i.client_order_key, "status": i.status, "filled": i.filled_qty,
             "broker_order_id": i.broker_order_id}
            for i in store.list_intents()
        ]
        evidence["final"]["active_reservations"] = [
            r.client_order_key for r in store.list_active_reservations()
        ]
        import sqlite3
        from qmt_execution_core import AccountRuntimeAuthority, default_authority_root
        auth = AccountRuntimeAuthority(default_authority_root()).resolve(
            account_key="79b2c89de3530efb179a84368ecaec3d551e6f39e4f34d02bc2dc722834fdae3",
            environment="simulation", account_type=2,
            account_id_sha256="7424e0cd66f135606bf4036df6414a412c8f0d4dc0a0ccd9d082cf705537e030",
            coordination_db_path=None, bootstrap=False,
        )
        c = sqlite3.connect(auth.coordination_db_path)
        claims = c.execute("SELECT symbol, finality FROM symbol_claim WHERE symbol=? AND finality!='resolved'", (SYMBOL,)).fetchall()
        active_cash = c.execute("SELECT COALESCE(SUM(required_cash),0) FROM cash_reservation WHERE active=1").fetchone()[0]
        c.close()
        evidence["final"]["core_claims_513100"] = [tuple(r) for r in claims]
        evidence["final"]["core_active_cash"] = active_cash
        ok = (not claims) and active_cash == 0 and not evidence["final"]["active_reservations"]
        OUTCOME = {"code": "ROUNDTRIP_PASS" if ok else "INVARIANT_FAIL",
                   "reason": "" if ok else "resource invariant not met"}
    finally:
        try:
            stack.close()
        except Exception:  # noqa: BLE001
            pass
        conn.close()
    _dump(evidence)
    return 0


def _dump(evidence):
    evidence["counts"] = COUNTS
    evidence["outcome"] = OUTCOME
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
