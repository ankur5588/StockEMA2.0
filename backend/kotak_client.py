"""Thin wrapper around the neo_api_client SDK with per-user session caching.

The Kotak Neo login is a 2-step flow:
  1. client.login(mobilenumber, password)  -> triggers OTP/MPIN challenge
  2. client.session_2fa(OTP=<otp or mpin>)  -> returns session data
After successful 2fa, the `client` carries the authenticated session and can
place orders, fetch positions, holdings, quotes etc.

We hold NeoAPI instances in-memory keyed by user_id. This is fine for a single
backend worker; for multi-worker deployments the login flow must be redone on
a different worker (acceptable trade-off for MVP).
"""
from __future__ import annotations
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

try:
    from neo_api_client import NeoAPI  # type: ignore
except Exception as e:  # pragma: no cover
    NeoAPI = None
    logger.warning("neo_api_client not importable: %s", e)


# in-memory session cache { user_id: {"client": NeoAPI, "ucc": str} }
_sessions: Dict[str, Dict[str, Any]] = {}


class KotakError(Exception):
    pass


def _ensure_sdk():
    if NeoAPI is None:
        raise KotakError("Kotak Neo SDK not available in this environment")


def _strip_creds(creds: dict) -> dict:
    """Remove whitespace noise that users often paste along with credentials."""
    out = {}
    for k, v in creds.items():
        if isinstance(v, str):
            out[k] = v.strip()
        else:
            out[k] = v
    return out


def start_login(user_id: str, creds: dict) -> dict:
    """Step 1: construct NeoAPI client (OAuth token exchange) and call login().

    Failure modes we handle explicitly:
      - consumer_key/consumer_secret rejected by Kotak OAuth -> bearer_token is
        None after construction -> we raise a clear error (SDK otherwise crashes
        with 'can only concatenate str (not NoneType) to str' when calling login).
      - login() returns an error payload -> we inspect the status code and
        surface Kotak's message.
    """
    _ensure_sdk()
    creds = _strip_creds(creds)
    for field in ("consumer_key", "consumer_secret", "mobile", "password"):
        if not creds.get(field):
            raise KotakError(f"Missing field: {field}")
    if not creds["mobile"].startswith("+"):
        raise KotakError(
            "Mobile number must start with country code (e.g. +91XXXXXXXXXX)"
        )

    try:
        client = NeoAPI(
            consumer_key=creds["consumer_key"],
            consumer_secret=creds["consumer_secret"],
            environment=creds.get("environment") or "prod",
            access_token=None,
            neo_fin_key=None,
        )
    except Exception as e:
        raise KotakError(f"Kotak SDK initialisation error: {e}")

    # Verify OAuth token was actually issued. If None, consumer key/secret was
    # rejected by Kotak (they return 200 with a misleading body, SDK doesn't raise).
    bearer = None
    try:
        bearer = client.api_client.configuration.bearer_token
    except Exception:
        pass
    if not bearer:
        raise KotakError(
            "Kotak Neo rejected your consumer key/secret. "
            "Verify on Kotak Neo app → Profile → Trade API → API Dashboard that: "
            "(1) the app is ACTIVATED (new apps can take up to 24h), "
            "(2) the key/secret pair has not been regenerated since you copied them, "
            "(3) you are using the TRADE API keys (not Data API), "
            "(4) there are no trailing spaces."
        )

    try:
        resp = client.login(mobilenumber=creds["mobile"], password=creds["password"])
    except Exception as e:
        raise KotakError(f"Kotak login() failed: {e}")

    # Inspect response for embedded errors Kotak returns as 4xx wrapped bodies.
    err_msg = _extract_error_message(resp)
    if err_msg:
        raise KotakError(f"Kotak Neo: {err_msg}")

    _sessions[user_id] = {"client": client, "ucc": None, "pending_2fa": True}
    return {"ok": True, "response": _clean(resp)}


def _extract_error_message(resp) -> Optional[str]:
    """Detect error codes inside Kotak's inconsistent response envelopes."""
    if not isinstance(resp, dict):
        return None
    # Pattern A: {"data": {"Code": 401, "Message": "..."}}
    data = resp.get("data")
    if isinstance(data, dict):
        code = data.get("Code") or data.get("code")
        message = data.get("Message") or data.get("message")
        if code and isinstance(code, int) and not (200 <= code < 300) and message:
            return f"[{code}] {message}"
    # Pattern B: top-level Status / ErrorMessage
    if resp.get("Status") in ("Error", "error") or resp.get("error"):
        return str(resp.get("Message") or resp.get("error") or "Unknown error")
    # Pattern C: fault.message
    fault = resp.get("fault")
    if isinstance(fault, dict):
        return str(fault.get("message") or fault.get("faultstring") or "Kotak API fault")
    return None


def complete_2fa(user_id: str, otp: str) -> dict:
    """Step 2: call session_2fa(OTP=<mpin or otp>)."""
    sess = _sessions.get(user_id)
    if not sess or not sess.get("client"):
        raise KotakError("No active login in progress. Call start_login first.")
    client: NeoAPI = sess["client"]
    try:
        resp = client.session_2fa(OTP=(otp or "").strip())
    except Exception as e:
        raise KotakError(f"2FA verification failed: {e}")

    err_msg = _extract_error_message(resp)
    if err_msg:
        raise KotakError(f"Kotak Neo 2FA: {err_msg}")

    # Extract ucc if present
    ucc = None
    try:
        data = resp.get("data", {}) if isinstance(resp, dict) else {}
        ucc = data.get("ucc") or data.get("userId") or data.get("user_id")
    except Exception:
        pass
    sess["ucc"] = ucc
    sess["pending_2fa"] = False
    return {"ok": True, "ucc": ucc, "response": _clean(resp)}


def is_authenticated(user_id: str) -> bool:
    sess = _sessions.get(user_id)
    return bool(sess and sess.get("client") and not sess.get("pending_2fa", True))


def get_client(user_id: str) -> "NeoAPI":
    sess = _sessions.get(user_id)
    if not sess or not sess.get("client") or sess.get("pending_2fa"):
        raise KotakError("Not authenticated with Kotak Neo. Please log in.")
    return sess["client"]


def logout(user_id: str):
    sess = _sessions.pop(user_id, None)
    if sess and sess.get("client"):
        try:
            sess["client"].logout()
        except Exception:
            pass


def get_positions(user_id: str) -> list:
    client = get_client(user_id)
    try:
        resp = client.positions()
    except Exception as e:
        raise KotakError(f"positions() failed: {e}")
    return _extract_list(resp)


def get_holdings(user_id: str) -> list:
    client = get_client(user_id)
    try:
        resp = client.holdings()
    except Exception as e:
        raise KotakError(f"holdings() failed: {e}")
    return _extract_list(resp)


def place_order(
    user_id: str,
    trading_symbol: str,
    transaction_type: str,  # "B" | "S"
    quantity: int,
    order_type: str = "MKT",  # MKT | L | SL | SL-M
    product: str = "CNC",
    exchange_segment: str = "nse_cm",
    price: str = "0",
    trigger_price: str = "0",
    validity: str = "DAY",
) -> dict:
    client = get_client(user_id)
    try:
        resp = client.place_order(
            exchange_segment=exchange_segment,
            product=product,
            price=str(price),
            order_type=order_type,
            quantity=str(quantity),
            validity=validity,
            trading_symbol=trading_symbol,
            transaction_type=transaction_type,
            amo="NO",
            disclosed_quantity="0",
            market_protection="0",
            pf="N",
            trigger_price=str(trigger_price),
            tag=None,
        )
    except Exception as e:
        raise KotakError(f"place_order failed: {e}")
    return _clean(resp) or {}


def _extract_list(resp) -> list:
    if resp is None:
        return []
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for key in ("data", "Data", "result", "positions", "holdings"):
            val = resp.get(key)
            if isinstance(val, list):
                return val
    return []


def _clean(obj):
    """Ensure JSON-serialisable."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(x) for x in obj]
    return str(obj)
