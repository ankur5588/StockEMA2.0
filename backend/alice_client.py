"""Alice Blue (ANT API) broker adapter via `pya3` SDK.

Auth flow: user provides `user_id` + `api_key` from the Alice Blue dashboard.
The `Aliceblue(user_id, api_key)` constructor + `get_session_id()` performs the
SHA256 handshake and returns a session id. Session is then cached per-user.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from pya3 import Aliceblue  # type: ignore
except Exception as e:  # pragma: no cover
    Aliceblue = None
    logger.warning("pya3 not importable: %s", e)


class AliceError(Exception):
    pass


_sessions: Dict[str, Any] = {}  # {user_id: Aliceblue instance}


def _ensure_sdk():
    if Aliceblue is None:
        raise AliceError("pya3 SDK not installed")


def connect(user_id: str, alice_user_id: str, api_key: str) -> dict:
    _ensure_sdk()
    alice_user_id = (alice_user_id or "").strip()
    api_key = (api_key or "").strip()
    if not alice_user_id or not api_key:
        raise AliceError("user_id and api_key are required")
    try:
        alice = Aliceblue(user_id=alice_user_id, api_key=api_key)
        sess = alice.get_session_id()
    except Exception as e:
        raise AliceError(f"Alice Blue init failed: {e}")

    # get_session_id returns dict. Even bad creds yield stat="Ok" but login=False.
    if isinstance(sess, dict):
        if sess.get("login") is False or sess.get("encKey") is None:
            emsg = sess.get("emsg") or sess.get("message") or "Alice Blue rejected credentials"
            raise AliceError(str(emsg))
        if str(sess.get("stat", "")).lower() not in ("ok", ""):
            emsg = sess.get("emsg") or sess.get("message") or "Alice Blue rejected credentials"
            raise AliceError(str(emsg))

    _sessions[user_id] = alice
    return {"ok": True}


def is_authenticated(user_id: str) -> bool:
    return user_id in _sessions


def disconnect(user_id: str) -> None:
    _sessions.pop(user_id, None)


def _get(user_id: str):
    c = _sessions.get(user_id)
    if not c:
        raise AliceError("Alice Blue not connected. Please connect first.")
    return c


def get_positions(user_id: str) -> list:
    alice = _get(user_id)
    try:
        resp = alice.get_netwise_positions()
    except Exception as e:
        raise AliceError(f"get_netwise_positions failed: {e}")
    positions = resp if isinstance(resp, list) else (resp.get("data") if isinstance(resp, dict) else [])
    out = []
    for p in positions or []:
        if not isinstance(p, dict):
            continue
        try:
            qty = int(float(p.get("netqty") or p.get("Netqty") or p.get("Nqty") or 0))
        except Exception:
            qty = 0
        sym = p.get("Tsym") or p.get("tsym") or p.get("Trsym") or p.get("symbol")
        try:
            avg = float(p.get("NetAvgPrc") or p.get("avgnetprice") or p.get("BuyAvgPrc") or 0)
        except Exception:
            avg = 0.0
        try:
            ltp = float(p.get("LTP") or p.get("Ltp") or 0) or None
        except Exception:
            ltp = None
        out.append({
            "broker": "alice_blue",
            "symbol": sym,
            "exchange_segment": (p.get("Exchange") or "NSE").upper(),
            "quantity": qty,
            "avg_price": round(avg, 2) if avg else 0.0,
            "ltp": round(ltp, 2) if ltp else None,
            "pnl": None,
            "product": p.get("Pcode") or p.get("pcode"),
        })
    return [o for o in out if o["quantity"] != 0]


def place_order(
    user_id: str,
    symbol: str,
    transaction_type: str,  # "B" | "S"
    quantity: int,
    order_type: str = "MKT",
    product: str = "CNC",
    exchange: str = "NSE",
    price: float = 0,
    trigger_price: float = 0,
) -> dict:
    alice = _get(user_id)
    try:
        instrument = alice.get_instrument_by_symbol(exchange, symbol.upper())
    except Exception as e:
        raise AliceError(f"instrument lookup failed for {symbol}: {e}")
    if not instrument:
        raise AliceError(f"Alice Blue instrument not found: {symbol}")

    txn = "BUY" if transaction_type.upper() in ("B", "BUY") else "SELL"
    ot_map = {"MKT": "MARKET", "L": "LIMIT", "SL": "SL", "SL-M": "SL-M",
              "MARKET": "MARKET", "LIMIT": "LIMIT"}
    pt_map = {"CNC": "CNC", "MIS": "MIS", "NRML": "NRML", "INTRADAY": "MIS", "MARGIN": "NRML"}

    try:
        resp = alice.place_order(
            transaction_type=txn,
            instrument=instrument,
            quantity=int(quantity),
            order_type=ot_map.get(order_type.upper(), "MARKET"),
            product_type=pt_map.get(product.upper(), "CNC"),
            price=float(price),
            trigger_price=float(trigger_price),
            stop_loss=None,
            square_off=None,
            trailing_sl=None,
            is_amo=False,
            order_tag="chartink-trade",
        )
    except Exception as e:
        raise AliceError(f"place_order failed: {e}")

    if isinstance(resp, dict) and str(resp.get("stat", "")).lower() == "not_ok":
        raise AliceError(resp.get("emsg") or "Alice Blue order rejected")

    order_id = None
    if isinstance(resp, dict):
        order_id = resp.get("NOrdNo") or resp.get("orderNo") or resp.get("nestordernumber")
    return {"ok": True, "order_id": order_id, "response": _clean(resp)}


def _clean(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(x) for x in obj]
    return str(obj)
