"""INDmoney (INDstocks) broker adapter.

Auth: Bearer token generated at https://www.indstocks.com/app/api-trading.
Static IP whitelisting required on INDmoney dashboard for API to work.

Endpoints used:
  GET  /user/profile          - validate token + identity
  GET  /portfolio/positions   - open positions
  POST /order/place           - place an order

Symbol convention for orders (per INDstocks docs):
  trading_symbol: "NSE_RELIANCE" or "BSE_RELIANCE" style (exchange_segment + scrip)
"""
from __future__ import annotations
import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.indstocks.com"
_sessions: Dict[str, Dict[str, Any]] = {}  # {user_id: {"token": str, "profile": dict}}


class IndMoneyError(Exception):
    pass


def _headers(token: str) -> dict:
    # Per OpenAlgo + INDstocks docs the Authorization header is just the token
    # (no "Bearer " prefix) for INDmoney.
    return {"Authorization": token, "Content-Type": "application/json"}


def connect(user_id: str, access_token: str) -> dict:
    access_token = (access_token or "").strip()
    if not access_token:
        raise IndMoneyError("access_token is required")
    try:
        r = requests.get(f"{_BASE_URL}/user/profile",
                         headers=_headers(access_token), timeout=15)
    except requests.RequestException as e:
        raise IndMoneyError(f"Network error reaching INDmoney: {e}")
    if r.status_code == 401:
        raise IndMoneyError("INDmoney rejected the token (401). Regenerate at indstocks.com/app/api-trading.")
    if r.status_code == 403:
        raise IndMoneyError("INDmoney returned 403. Most likely your outbound IP is not whitelisted on the INDmoney API dashboard.")
    if not r.ok:
        raise IndMoneyError(f"INDmoney /user/profile failed: HTTP {r.status_code} - {r.text[:200]}")
    try:
        profile = r.json()
    except Exception:
        profile = {}
    _sessions[user_id] = {"token": access_token, "profile": profile}
    return {"ok": True, "profile": profile}


def is_authenticated(user_id: str) -> bool:
    return user_id in _sessions


def disconnect(user_id: str) -> None:
    _sessions.pop(user_id, None)


def _get(user_id: str) -> str:
    sess = _sessions.get(user_id)
    if not sess:
        raise IndMoneyError("INDmoney not connected. Please connect first.")
    return sess["token"]


def get_positions(user_id: str) -> list:
    token = _get(user_id)
    try:
        r = requests.get(f"{_BASE_URL}/portfolio/positions",
                         headers=_headers(token), timeout=15)
    except requests.RequestException as e:
        raise IndMoneyError(f"positions request failed: {e}")
    if r.status_code in (401, 403):
        disconnect(user_id)
        raise IndMoneyError(f"INDmoney session invalid (HTTP {r.status_code}). Reconnect.")
    if not r.ok:
        raise IndMoneyError(f"positions HTTP {r.status_code}: {r.text[:200]}")
    try:
        data = r.json()
    except Exception:
        return []
    positions = data.get("data") if isinstance(data, dict) else data
    if not isinstance(positions, list):
        return []
    out = []
    for p in positions:
        if not isinstance(p, dict):
            continue
        sym = p.get("trading_symbol") or p.get("tradingsymbol") or p.get("symbol")
        try:
            qty = int(p.get("net_qty") or p.get("quantity") or 0)
        except Exception:
            qty = 0
        try:
            avg = float(p.get("avg_price") or p.get("average_price") or p.get("buy_avg") or 0)
        except Exception:
            avg = 0.0
        try:
            ltp = float(p.get("ltp") or p.get("last_price") or 0) or None
        except Exception:
            ltp = None
        exch = (p.get("exchange") or p.get("exchange_segment") or "NSE").upper()
        out.append({
            "broker": "indmoney",
            "symbol": sym,
            "exchange_segment": exch,
            "quantity": qty,
            "avg_price": round(avg, 2),
            "ltp": round(ltp, 2) if ltp else None,
            "pnl": p.get("pnl"),
            "product": p.get("product"),
        })
    return [o for o in out if o["quantity"] != 0]


def place_order(
    user_id: str,
    symbol: str,
    transaction_type: str,        # "B" | "S"
    quantity: int,
    order_type: str = "MKT",
    product: str = "CNC",
    exchange_segment: str = "NSE",
    price: float = 0,
    trigger_price: float = 0,
) -> dict:
    token = _get(user_id)
    txn = "BUY" if transaction_type.upper() in ("B", "BUY") else "SELL"
    ot_map = {"MKT": "MARKET", "MARKET": "MARKET", "L": "LIMIT", "LIMIT": "LIMIT",
              "SL": "SL", "SL-M": "SL-M"}
    pt_map = {"CNC": "CNC", "MIS": "INTRADAY", "INTRADAY": "INTRADAY",
              "NRML": "MARGIN", "MARGIN": "MARGIN"}
    exch = "NSE" if exchange_segment.upper().startswith("NSE") else "BSE"
    trading_symbol = symbol.upper().strip().replace("-EQ", "")

    payload = {
        "exchange": exch,
        "trading_symbol": trading_symbol,
        "transaction_type": txn,
        "quantity": int(quantity),
        "order_type": ot_map.get(order_type.upper(), "MARKET"),
        "product": pt_map.get(product.upper(), "CNC"),
        "validity": "DAY",
        "price": float(price),
        "trigger_price": float(trigger_price),
    }
    try:
        r = requests.post(f"{_BASE_URL}/order/place",
                          headers=_headers(token), json=payload, timeout=15)
    except requests.RequestException as e:
        raise IndMoneyError(f"place_order request failed: {e}")
    if r.status_code in (401, 403):
        disconnect(user_id)
        raise IndMoneyError(f"INDmoney session invalid (HTTP {r.status_code}). Reconnect.")
    try:
        body = r.json()
    except Exception:
        body = r.text
    if not r.ok or (isinstance(body, dict) and body.get("status") in ("failure", "error")):
        msg = body.get("message") or body.get("error") or body.get("remarks") if isinstance(body, dict) else str(body)
        raise IndMoneyError(f"INDmoney order rejected: HTTP {r.status_code} - {msg}")
    order_id = None
    if isinstance(body, dict):
        order_id = body.get("order_id") or (body.get("data") or {}).get("order_id")
    return {"ok": True, "order_id": order_id, "response": body}
