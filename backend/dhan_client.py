"""Dhan (DhanHQ) broker adapter.

Dhan auth is SIMPLE: user pastes `client_id` + `access_token` (access token
expires ~24h, regenerated on web.dhan.co). No OTP flow.

SDK: `dhanhq` (v2+).

Order-placement semantics:
  - `security_id` is required, NOT the ticker. We lazy-load the Dhan scrip
    master CSV once and cache the symbol->security_id mapping in memory.
  - exchange_segment: NSE_EQ, BSE_EQ, NSE_FNO, etc.
  - product_type: CNC | INTRADAY | MARGIN
  - order_type: MARKET | LIMIT | STOP_LOSS | STOP_LOSS_MARKET
"""
from __future__ import annotations
import base64
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

try:
    from dhanhq import dhanhq as DhanSDK, DhanContext  # type: ignore
except Exception as e:  # pragma: no cover
    DhanSDK = None
    DhanContext = None
    logger.warning("dhanhq not importable: %s", e)


class DhanError(Exception):
    pass


_sessions: Dict[str, Any] = {}          # {user_id: dhanhq instance}
_creds: Dict[str, Tuple[str, str]] = {}  # {user_id: (client_id, access_token)}
API_BASE = "https://api.dhan.co/v2"
_symbol_map: Dict[str, str] = {}        # {"NSE:RELIANCE": "2885"}
_map_loaded: bool = False


def _ensure_sdk():
    if DhanSDK is None:
        raise DhanError("dhanhq SDK not installed")


def _load_scrip_master() -> None:
    """Lazy-load Dhan's scrip master to build symbol -> security_id map."""
    global _map_loaded
    if _map_loaded:
        return
    try:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        import pandas as pd
        df = pd.read_csv(io.StringIO(r.text), low_memory=False)
        # Common columns: SEM_EXM_EXCH_ID, SEM_SMST_SECURITY_ID, SEM_TRADING_SYMBOL
        for _, row in df.iterrows():
            exch = str(row.get("SEM_EXM_EXCH_ID", "")).strip()
            sid = str(row.get("SEM_SMST_SECURITY_ID", "")).strip()
            sym = str(row.get("SEM_TRADING_SYMBOL", "")).strip()
            if not exch or not sid or not sym:
                continue
            key = f"{exch}:{sym.upper()}"
            _symbol_map[key] = sid
        _map_loaded = True
        logger.info("Dhan scrip master loaded (%d rows)", len(_symbol_map))
    except Exception as e:
        logger.warning("Dhan scrip master load failed: %s (orders will require manual security_id)", e)


def connect(user_id: str, client_id: str, access_token: str) -> dict:
    _ensure_sdk()
    client_id = (client_id or "").strip()
    access_token = (access_token or "").strip()
    if not client_id or not access_token:
        raise DhanError("client_id and access_token are required")
    try:
        ctx = DhanContext(client_id, access_token)
        client = DhanSDK(ctx)
        # Quick validation: fund_limit is a cheap auth-required call
        try:
            resp = client.get_fund_limits()
            if isinstance(resp, dict) and resp.get("status") == "failure":
                raise DhanError(resp.get("remarks") or "Dhan rejected credentials")
        except DhanError:
            raise
        except Exception as e:
            raise DhanError(f"Dhan credential validation failed: {e}")
    except DhanError:
        raise
    except Exception as e:
        raise DhanError(f"Dhan SDK init failed: {e}")
    _sessions[user_id] = client
    _creds[user_id] = (client_id, access_token)
    return {"ok": True}


def token_expiry(access_token: str) -> Optional[datetime]:
    """Read the `exp` claim of a Dhan JWT access token (UTC). None if unreadable."""
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return datetime.fromtimestamp(int(exp), tz=timezone.utc) if exp else None
    except Exception:
        return None


def renew_token(client_id: str, access_token: str) -> dict:
    """Swap an ACTIVE web-generated token for a fresh 24h token.

    Dhan only renews tokens that have not expired yet, so this must run
    before expiry (the app calls it every morning before market open).
    Returns {"access_token": str, "expiry": str|None}.
    """
    try:
        r = requests.post(
            f"{API_BASE}/RenewToken",
            headers={"access-token": access_token, "dhanClientId": client_id},
            timeout=20,
        )
    except Exception as e:
        raise DhanError(f"Dhan token renew request failed: {e}")
    try:
        body = r.json()
    except Exception:
        body = {}
    new_token = (body or {}).get("accessToken") or (body or {}).get("access_token")
    if r.status_code != 200 or not new_token:
        msg = (body or {}).get("errorMessage") or (body or {}).get("remarks") or r.text[:200]
        raise DhanError(f"Dhan token renew failed ({r.status_code}): {msg}")
    return {"access_token": new_token, "expiry": (body or {}).get("expiryTime")}


def _headers(user_id: str) -> dict:
    cid, tok = _creds.get(user_id, (None, None))
    if not cid:
        raise DhanError("Dhan not connected. Please connect first.")
    return {"access-token": tok, "client-id": cid, "dhanClientId": cid,
            "Content-Type": "application/json", "Accept": "application/json"}


def _rest(user_id: str, method: str, path: str, body: Optional[dict] = None):
    try:
        r = requests.request(method, f"{API_BASE}{path}", headers=_headers(user_id),
                             json=body, timeout=20)
    except DhanError:
        raise
    except Exception as e:
        raise DhanError(f"Dhan request failed: {e}")
    if r.status_code in (401, 403):
        # Session is dead: drop it so callers reconnect or ask for a new one
        disconnect(user_id)
        raise DhanError("Dhan access expired or invalid. Paste a new one.")
    try:
        data = r.json()
    except Exception:
        data = {}
    if r.status_code >= 400:
        msg = (data or {}).get("errorMessage") or (data or {}).get("remarks") or r.text[:200]
        raise DhanError(f"Dhan API {r.status_code}: {msg}")
    return data


_OPEN_STATUSES = {"PENDING", "TRANSIT", "TRIGGER_PENDING"}


def find_open_sl(user_id: str, security_id) -> Optional[dict]:
    """Return today's still-open SELL stop-loss order for `security_id`, if any."""
    orders = _rest(user_id, "GET", "/orders")
    if isinstance(orders, dict):
        orders = orders.get("data") or []
    for o in orders or []:
        if str(o.get("securityId")) != str(security_id):
            continue
        if str(o.get("transactionType", "")).upper() != "SELL":
            continue
        if str(o.get("orderType", "")).upper() not in ("STOP_LOSS", "STOP_LOSS_MARKET"):
            continue
        if str(o.get("orderStatus", "")).upper() not in _OPEN_STATUSES:
            continue
        return o
    return None


def cancel_open_sl_orders(user_id: str) -> list:
    """Cancel every still-open SELL stop-loss order. Returns the cancelled order ids."""
    orders = _rest(user_id, "GET", "/orders")
    if isinstance(orders, dict):
        orders = orders.get("data") or []
    cancelled = []
    for o in orders or []:
        if str(o.get("transactionType", "")).upper() != "SELL":
            continue
        if str(o.get("orderType", "")).upper() not in ("STOP_LOSS", "STOP_LOSS_MARKET"):
            continue
        if str(o.get("orderStatus", "")).upper() not in _OPEN_STATUSES:
            continue
        oid = str(o.get("orderId"))
        _rest(user_id, "DELETE", f"/orders/{oid}")
        cancelled.append(oid)
    return cancelled


def modify_sl(user_id: str, order_id: str, quantity: int, price: float, trigger_price: float) -> dict:
    cid, _ = _creds.get(user_id, (None, None))
    body = {
        "dhanClientId": cid,
        "orderId": str(order_id),
        "orderType": "STOP_LOSS",
        "legName": "",
        "quantity": int(quantity),
        "price": float(price),
        "disclosedQuantity": 0,
        "triggerPrice": float(trigger_price),
        "validity": "DAY",
    }
    data = _rest(user_id, "PUT", f"/orders/{order_id}", body)
    return {"ok": True, "order_id": str(order_id), "response": _clean(data)}


def is_authenticated(user_id: str) -> bool:
    return user_id in _sessions


def disconnect(user_id: str) -> None:
    _sessions.pop(user_id, None)
    _creds.pop(user_id, None)


def _get(user_id: str):
    c = _sessions.get(user_id)
    if not c:
        raise DhanError("Dhan not connected. Please connect first.")
    return c


def _security_id_for(symbol: str, exchange_segment: str = "NSE_EQ") -> Optional[str]:
    _load_scrip_master()
    exch = "NSE" if exchange_segment.startswith("NSE") else "BSE"
    sym = symbol.upper().strip()
    # Dhan master often stores base symbol - try a few variants
    for candidate in (sym, sym.replace("-EQ", ""), f"{sym}-EQ"):
        key = f"{exch}:{candidate}"
        if key in _symbol_map:
            return _symbol_map[key]
    return None


def get_positions(user_id: str) -> list:
    client = _get(user_id)
    try:
        resp = client.get_positions()
    except Exception as e:
        raise DhanError(f"get_positions failed: {e}")
    data = resp.get("data") if isinstance(resp, dict) else resp
    positions = data if isinstance(data, list) else []
    out = []
    for p in positions:
        qty = int(p.get("netQty") or p.get("quantity") or 0)
        out.append({
            "broker": "dhan",
            "symbol": (p.get("tradingSymbol") or p.get("trading_symbol") or "UNKNOWN").upper(),
            "exchange_segment": p.get("exchangeSegment") or p.get("exchange_segment") or "NSE_EQ",
            "security_id": p.get("securityId") or p.get("security_id"),
            "quantity": qty,
            "avg_price": float(p.get("buyAvg") or p.get("costPrice") or p.get("netAvgPrice") or 0),
            "ltp": float(p.get("lastTradedPrice") or p.get("ltp") or 0) or None,
            "pnl": float(p.get("realizedProfit") or 0) + float(p.get("unrealizedProfit") or 0) or None,
            "product": p.get("productType") or p.get("product"),
        })
    out = [o for o in out if o["quantity"] != 0]

    # Delivery shares bought on earlier days live in Holdings, not Positions.
    seen = {str(o.get("security_id")) for o in out if o.get("security_id")}
    try:
        for h in get_holdings(user_id):
            if str(h.get("security_id")) not in seen:
                out.append(h)
    except DhanError as e:
        logger.warning("Dhan holdings fetch failed: %s", e)
    return out


def get_holdings(user_id: str) -> list:
    """Delivery holdings as position-shaped rows (sellable quantity only)."""
    data = _rest(user_id, "GET", "/holdings")
    if isinstance(data, dict):
        data = data.get("data") or []
    rows = []
    for h in data or []:
        qty = int(h.get("availableQty") or 0)
        if qty <= 0:
            continue
        exch = str(h.get("exchange") or "NSE").upper()
        rows.append({
            "broker": "dhan",
            "symbol": (h.get("tradingSymbol") or "UNKNOWN").upper(),
            "exchange_segment": "BSE_EQ" if exch.startswith("BSE") else "NSE_EQ",
            "security_id": h.get("securityId"),
            "quantity": qty,
            "avg_price": float(h.get("avgCostPrice") or 0),
            "ltp": None,
            "pnl": None,
            "product": "CNC",
        })
    return rows


def place_order(
    user_id: str,
    symbol: str,
    transaction_type: str,   # "B" | "S" (our internal convention)
    quantity: int,
    order_type: str = "MKT",  # MKT | L | SL | SL-M (internal)
    product: str = "CNC",     # internal
    exchange_segment: str = "NSE_EQ",
    price: float = 0,
    trigger_price: float = 0,
    security_id: Optional[str] = None,
    amo: bool = False,
) -> dict:
    client = _get(user_id)

    sid = security_id or _security_id_for(symbol, exchange_segment)
    if not sid:
        raise DhanError(f"Could not resolve Dhan security_id for '{symbol}' on {exchange_segment}")

    dhan_txn = "BUY" if transaction_type.upper() in ("B", "BUY") else "SELL"
    ot_map = {
        "MKT": "MARKET", "MARKET": "MARKET",
        "L": "LIMIT", "LIMIT": "LIMIT",
        "SL": "STOP_LOSS", "SL-M": "STOP_LOSS_MARKET",
    }
    pt_map = {
        "CNC": "CNC", "MIS": "INTRADAY", "NRML": "MARGIN",
        "INTRADAY": "INTRADAY", "MARGIN": "MARGIN",
    }
    dhan_ot = ot_map.get(order_type.upper(), "MARKET")
    dhan_pt = pt_map.get(product.upper(), "CNC")

    place_kwargs = dict(
        security_id=str(sid),
        exchange_segment=exchange_segment,
        transaction_type=dhan_txn,
        quantity=int(quantity),
        order_type=dhan_ot,
        product_type=dhan_pt,
        price=float(price),
        trigger_price=float(trigger_price),
        validity="DAY",
        disclosed_quantity=0,
    )
    if amo:
        # dhanhq exposes after_market_order=True; pass leniently in case
        # older versions don't accept it
        place_kwargs["after_market_order"] = True

    try:
        resp = client.place_order(**place_kwargs)
    except TypeError:
        # dhanhq SDK without AMO support → retry without the AMO flag
        place_kwargs.pop("after_market_order", None)
        try:
            resp = client.place_order(**place_kwargs)
        except Exception as e:
            raise DhanError(f"place_order failed: {e}")
    except Exception as e:
        raise DhanError(f"place_order failed: {e}")

    if isinstance(resp, dict) and resp.get("status") == "failure":
        raise DhanError(resp.get("remarks") or "Dhan order rejected")

    order_id = None
    if isinstance(resp, dict):
        order_id = resp.get("orderId") or (resp.get("data") or {}).get("orderId")
    return {"ok": True, "order_id": order_id, "response": _clean(resp)}


def _clean(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(x) for x in obj]
    return str(obj)
