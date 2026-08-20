"""Gate-6.2 T+0 intraday roundtrip runner — QMT SIMULATION ONLY.

Validates one complete TGrid + Core execution roundtrip on 513100.SH
(SSE 纳指ETF, T+0 eligible) within the exact Gate-6.2 authorization:

    BUY exactly 100 -> FILLED -> SELL the same 100 -> FILLED
    max BUY notional 2000 CNY
    max 2 broker submits (1 BUY + 1 SELL), max 2 cancels
    no third order, no live calls, no production src/Core changes

Outcome codes: ROUNDTRIP_PASS | BLOCKED_PRE_BROKER | BUY_NOT_RESOLVED |
T0_SELL_BLOCKED_BY_TGRID | SELL_NOT_RESOLVED | INVARIANT_FAIL

Safety model (iteration 2, post-audit):
- Recovery/skip-BUY is allowed ONLY when the task's own TGrid intent
  TG_G62_A is authoritatively FILLED and the broker still reflects the same
  held quantity. Account position alone never proves task ownership
  (would sell unrelated pre-existing inventory — P0-3).
- An unresolved leg performs at most ONE cancel through the normal TGrid ->
  Core path, reconciles authoritatively, then stops. No blind retry (P1-1).
- Every submit is gated by a fail-closed quote check enforcing positive
  bid/ask ordering, tick freshness, and a conservative spread bound (P1-2).
- Account identity is derived from the local, ignored qec binding file; no
  account-specific literals are committed (P1-3).
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
from qmt_execution_core import (  # noqa: E402
    AccountRuntimeAuthority,
    default_authority_root,
    account_key_from_binding_identity,
)

SYMBOL = "513100.SH"
QTY = 100
MAX_BUY_NOTIONAL = 2000.0

# ---- Quote fail-closed bounds (P1-2) ----
# Tick age is measured against the exchange tick timestamp (epoch ms). A frozen
# or stale feed must fail closed before any broker submit.
QUOTE_MAX_AGE_MS = 5000
# Spread must not exceed 1% of ask1 — a liquid T+0 ETF trades at a 1-tick spread.
QUOTE_MAX_SPREAD_RATIO = 0.01

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


def _quote_ok(quote, *, is_sell: bool):
    """Fail-closed quote gate applied immediately before each submit (P1-2).

    Returns (ok, reason). Rejects when bid/ask are not positive & ordered,
    when the tick is stale, or when the spread is wider than the conservative
    bound. A rejected quote must never reach a broker submit.
    """
    if quote["ask1"] <= 0 or quote["bid1"] <= 0 or quote["ask1"] < quote["bid1"]:
        return False, "quote invalid (bid/ask not positive/ordered)"
    age_ms = int(time.time() * 1000) - int(quote.get("time") or 0)
    if age_ms < 0 or age_ms > QUOTE_MAX_AGE_MS:
        return False, f"quote stale (age_ms={age_ms} > {QUOTE_MAX_AGE_MS})"
    spread = quote["spread"]
    if spread < 0:
        return False, "negative spread"
    cap = quote["ask1"] * QUOTE_MAX_SPREAD_RATIO
    if spread > cap:
        return False, f"quote spread too wide ({spread:.4f} > cap {cap:.4f})"
    return True, ""


def _get_intent(store, key):
    """Return the intent or None (fresh run / never created)."""
    try:
        return store.get_intent(key)
    except Exception:  # noqa: BLE001 - IntentNotFoundError on missing
        return None


def _should_skip_buy(intent_a, held_can_use) -> bool:
    """P0-3: skip BUY only when the TASK's own intent TG_G62_A is authoritatively
    FILLED AND the broker still reflects that held quantity. Account position
    alone never proves task ownership (would sell unrelated inventory)."""
    if intent_a is None:
        return False
    if getattr(intent_a, "status", None) != "FILLED":
        return False
    if not (isinstance(held_can_use, int) and held_can_use >= QTY):
        return False
    return True


def _wait_and_resolve_leg(engine, key, *, now_fn, evidence):
    """Poll a submitted leg. If it does not reach FILLED, perform exactly ONE
    cancel through the normal TGrid -> Core path, reconcile authoritatively,
    record the post-cancel state, then stop. Never blind-retries (P1-1).

    Returns the final status string.
    """
    status = None
    for _ in range(10):
        status = engine.poll_order(key, now=now_fn()).status
        if status in ("FILLED", "CANCELED", "REJECTED"):
            break
        time.sleep(1.5)
    evidence["final_state"] = status
    if status == "FILLED":
        return status
    if status in ("CANCELED", "REJECTED"):
        return status  # already terminal — no cancel
    # Unresolved (NEW/SUBMITTED/ACCEPTED/PARTIAL/UNKNOWN): at most one cancel.
    COUNTS["sim_cancels"] += 1
    try:
        cr = engine.cancel_order(key, now=now_fn())
        evidence["cancel"] = {
            "status": cr.status, "filled_qty": cr.filled_qty,
            "broker_order_id": cr.broker_order_id,
        }
    except Exception as exc:  # noqa: BLE001 - record ambiguous cancel path
        evidence["cancel_error"] = f"{type(exc).__name__}: {exc}"
    # Authoritative reconcile (fold snapshot); never assume zero fill.
    try:
        rc = engine.poll_order(key, now=now_fn())
        evidence["reconcile"] = {
            "status": rc.status, "filled_qty": rc.filled_qty,
        }
        status = rc.status
    except Exception as exc:  # noqa: BLE001 - record reconcile outcome
        evidence["reconcile_error"] = f"{type(exc).__name__}: {exc}"
    return status


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
    ok, why = _quote_ok(quote, is_sell=False)
    if not ok:
        OUTCOME = {"code": "BLOCKED_PRE_BROKER", "reason": f"preflight quote rejected: {why}"}
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
        # ---- Idempotency: if the roundtrip is already fully closed, PASS
        # without placing any new orders. A re-run must NOT re-BUY/re-SELL and
        # violate the Gate-6.2 "exactly 100 / max 1 BUY + 1 SELL" limits. ----
        _a = _get_intent(store, "TG_G62_A")
        _b = _get_intent(store, "TG_G62_B")
        _pos0 = next((p for p in stack.runtime.session.broker.query_positions()
                      if p.symbol == SYMBOL), None)
        _closed = (
            _a is not None and _a.status == "FILLED"
            and _b is not None and _b.status == "FILLED"
            and (_pos0 is None or int(_pos0.volume) == 0)
        )
        if _closed:
            evidence["preflight"]["already_closed"] = True
            evidence["final"] = {
                "position": {
                    "volume": int(_pos0.volume) if _pos0 else 0,
                    "can_use": int(_pos0.can_use_volume) if _pos0 else 0,
                },
                "intents": [
                    {"key": i.client_order_key, "side": i.side, "status": i.status,
                     "broker_order_id": i.broker_order_id}
                    for i in store.list_intents()
                ],
                "active_reservations": [
                    r.client_order_key for r in store.list_active_reservations()
                ],
            }
            OUTCOME = {"code": "ROUNDTRIP_PASS",
                       "reason": "roundtrip already closed (idempotent short-circuit, no orders placed)"}
            _dump(evidence)
            return 0

        # ---- Leg A: BUY 100 ----
        # Re-fetch a fresh quote immediately before submit and gate on freshness
        # + spread (P1-2). Skip BUY only when the TASK intent TG_G62_A is
        # authoritatively FILLED and the broker reflects the held qty (P0-3).
        _positions = stack.runtime.session.broker.query_positions()
        _held = next((p for p in _positions if p.symbol == SYMBOL), None)
        if _should_skip_buy(_a, int(_held.can_use_volume) if _held else 0):
            evidence["legA"]["skipped"] = True
            evidence["legA"]["already_held_volume"] = int(_held.volume)
            evidence["legA"]["already_held_can_use"] = int(_held.can_use_volume)
            evidence["legA"]["final_state"] = "FILLED"
            state = "FILLED"
        else:
            buy_quote = _fresh_quote(xtdata, SYMBOL)
            evidence["legA"]["quote"] = buy_quote
            ok, why = _quote_ok(buy_quote, is_sell=False)
            if not ok:
                OUTCOME = {"code": "BLOCKED_PRE_BROKER", "reason": f"BUY quote rejected: {why}"}
                _dump(evidence)
                return 0
            buy_price = round(buy_quote["ask1"] * 1.001, 3)
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
            state = _wait_and_resolve_leg(
                stack.engine, "TG_G62_A", now_fn=_now, evidence=evidence["legA"])
        if state != "FILLED":
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
        ok, why = _quote_ok(fresh, is_sell=True)
        if not ok:
            OUTCOME = {"code": "SELL_NOT_RESOLVED", "reason": f"SELL quote rejected: {why}"}
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
        state = _wait_and_resolve_leg(
            stack.engine, "TG_G62_B", now_fn=_now, evidence=evidence["legB"])
        if state != "FILLED":
            OUTCOME = {"code": "SELL_NOT_RESOLVED", "reason": f"SELL final state {state}"}
            _dump(evidence)
            return 0

        # ---- Final reconciliation ----
        # P1-3: derive account identity from the local, ignored qec binding file
        # instead of committing account-specific literals.
        _bnd = json.loads(Path(binding_file).read_text(encoding="utf-8"))
        _account_key = account_key_from_binding_identity(
            environment=_bnd["environment"],
            account_type=int(_bnd["account_type"]),
            account_id_sha256=_bnd["account_id_sha256"],
        )
        auth = AccountRuntimeAuthority(default_authority_root()).resolve(
            account_key=_account_key,
            environment=_bnd["environment"],
            account_type=int(_bnd["account_type"]),
            account_id_sha256=_bnd["account_id_sha256"],
            coordination_db_path=None, bootstrap=False,
        )
        import sqlite3
        c = sqlite3.connect(auth.coordination_db_path)
        claims = c.execute(
            "SELECT symbol, finality FROM symbol_claim WHERE symbol=? AND finality!='resolved'",
            (SYMBOL,),
        ).fetchall()
        active_cash = c.execute(
            "SELECT COALESCE(SUM(required_cash),0) FROM cash_reservation WHERE active=1"
        ).fetchone()[0]
        c.close()
        _pos_f = next((p for p in stack.runtime.session.broker.query_positions()
                       if p.symbol == SYMBOL), None)
        evidence["final"]["position"] = {
            "volume": int(_pos_f.volume) if _pos_f else 0,
            "can_use": int(_pos_f.can_use_volume) if _pos_f else 0,
        }
        evidence["final"]["intents"] = [
            {"key": i.client_order_key, "status": i.status, "filled": i.filled_qty,
             "broker_order_id": i.broker_order_id}
            for i in store.list_intents()
        ]
        evidence["final"]["active_reservations"] = [
            r.client_order_key for r in store.list_active_reservations()
        ]
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
