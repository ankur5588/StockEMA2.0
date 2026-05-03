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
import io
import logging
from typing import Any, Dict, Optional

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
    return {"ok": True}


def is_authenticated(user_id: str) -> bool:
    return user_id in _sessions


def disconnect(user_id: str) -> None:
    _sessions.pop(user_id, None)


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
            "symbol": p.get("tradingSymbol") or p.get("trading_symbol"),
            "exchange_segment": p.get("exchangeSegment") or p.get("exchange_segment") or "NSE_EQ",
            "security_id": p.get("securityId") or p.get("security_id"),
            "quantity": qty,
            "avg_price": float(p.get("buyAvg") or p.get("costPrice") or p.get("netAvgPrice") or 0),
            "ltp": float(p.get("lastTradedPrice") or p.get("ltp") or 0) or None,
            "pnl": float(p.get("realizedProfit") or 0) + float(p.get("unrealizedProfit") or 0) or None,
            "product": p.get("productType") or p.get("product"),
        })
    return [o for o in out if o["quantity"] != 0]


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

    try:
        resp = client.place_order(
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
