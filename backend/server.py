"""FastAPI backend for the Kotak Neo + Chartink trading automation app."""
from __future__ import annotations

import asyncio
import logging
import math
import os
import secrets
import uuid
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List

import requests
from dotenv import load_dotenv
from fastapi import APIRouter, Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

import csv
import io

import kotak_client
import dhan_client
import alice_client
import indmoney_client
import delta_client
import auth_service
from ema_service import compute_ema10
from backtest_service import run_backtest, run_signal_backtest, NIFTY_100
from models import (
    AlertConfig,
    AlertConfigInput,
    AliceCredentialsInput,
    CategoryAmountInput,
    CategoryAmount,
    CATEGORIES,
    DeltaCredentialsInput,
    DhanCredentialsInput,
    EmaSchedule,
    EmaScheduleInput,
    EmaSlRun,
    IndMoneyCredentialsInput,
    KotakCredentialsInput,
    KotakOtpInput,
    KotakStatus,
    ManualOrderInput,
    SymbolMapping,
    SymbolMappingInput,
    TradeLog,
    User,
    WebhookLog,
)
from security import decrypt_dict, encrypt_dict

# Default tick size for Indian equity exchanges (NSE/BSE cash = ₹0.05)
TICK_SIZE = 0.05


def round_to_tick(price: float, tick: float = TICK_SIZE) -> float:
    """Round `price` down to the nearest multiple of `tick`.

    Exchanges reject orders where the price is not a multiple of the
    tick size (e.g. ₹100.07 when tick = ₹0.05).  We round DOWN so the
    SL limit price is always strictly below the trigger price and the
    order does not get rejected with EXCH:16283.

    Uses Decimal arithmetic to avoid floating-point precision issues
    (e.g. 100.1 / 0.05 must yield exactly 2002, not 2001.999...).
    """
    if price is None or tick <= 0:
        return price
    d_price = Decimal(str(price))
    d_tick = Decimal(str(tick))
    steps = int(d_price / d_tick)
    return float((Decimal(steps) * d_tick).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
mongo_url = os.environ["MONGO_URL"]
mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[os.environ["DB_NAME"]]

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="ChartinkTrade")
api = APIRouter(prefix="/api")


# =============================================================================
# AUTH -- Emergent Google social login
# REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS,
# THIS BREAKS THE AUTH
# =============================================================================

EMERGENT_SESSION_URL = (
    "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
)
SESSION_TTL = timedelta(days=7)


async def _get_session_token_from_request(
    session_token: Optional[str], authorization: Optional[str]
) -> Optional[str]:
    if session_token:
        return session_token
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


async def require_user(
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
) -> User:
    tok = await _get_session_token_from_request(session_token, authorization)
    if not tok:
        raise HTTPException(status_code=401, detail="Not authenticated")
    sess = await db.user_sessions.find_one({"session_token": tok}, {"_id": 0})
    if not sess:
        raise HTTPException(status_code=401, detail="Invalid session")
    expires_at = sess.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")
    user_doc = await db.users.find_one({"user_id": sess["user_id"]}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    if isinstance(user_doc.get("created_at"), str):
        user_doc["created_at"] = datetime.fromisoformat(user_doc["created_at"])
    return User(**user_doc)


class SessionExchangeInput(BaseModel):
    session_id: str


@api.post("/auth/session")
async def auth_session(payload: SessionExchangeInput, response: Response):
    """Exchange Emergent `session_id` for our own `session_token` cookie."""
    try:
        r = requests.get(
            EMERGENT_SESSION_URL,
            headers={"X-Session-ID": payload.session_id},
            timeout=10,
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Emergent auth error: {e}")
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session id")
    data = r.json()
    email = data.get("email")
    name = data.get("name")
    picture = data.get("picture")
    emergent_session_token = data.get("session_token")
    if not email or not emergent_session_token:
        raise HTTPException(status_code=400, detail="Incomplete session data")

    # Upsert user
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    now = datetime.now(timezone.utc)
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": name, "picture": picture}},
        )
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one(
            {
                "user_id": user_id,
                "email": email,
                "name": name,
                "picture": picture,
                "created_at": now.isoformat(),
            }
        )

    # Store session. We store the emergent session_token as our session_token.
    expires_at = now + SESSION_TTL
    await db.user_sessions.insert_one(
        {
            "user_id": user_id,
            "session_token": emergent_session_token,
            "expires_at": expires_at.isoformat(),
            "created_at": now.isoformat(),
        }
    )

    # httpOnly cookie
    response.set_cookie(
        key="session_token",
        value=emergent_session_token,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
        httponly=True,
        secure=True,
        samesite="none",
    )

    return {
        "user": {
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
        },
        "session_token": emergent_session_token,
    }


@api.get("/auth/me")
async def auth_me(user: User = Depends(require_user)):
    return user


@api.post("/auth/logout")
async def auth_logout(
    response: Response,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    tok = await _get_session_token_from_request(session_token, authorization)
    if tok:
        await db.user_sessions.delete_one({"session_token": tok})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


# =============================================================================
# KOTAK NEO
# =============================================================================

def _base_url_from_request(request: Request) -> str:
    # Prefer forwarded host/proto if present (behind ingress)
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    return f"{proto}://{host}"


async def _get_creds_doc(user_id: str) -> Optional[dict]:
    return await db.kotak_credentials.find_one({"user_id": user_id}, {"_id": 0})


@api.post("/kotak/credentials")
async def save_kotak_credentials(
    payload: KotakCredentialsInput, user: User = Depends(require_user)
):
    # Strip whitespace - users commonly paste with trailing spaces/newlines
    cleaned = {k: (v.strip() if isinstance(v, str) else v) for k, v in payload.model_dump().items()}
    encrypted = encrypt_dict(cleaned)
    existing = await _get_creds_doc(user.user_id)
    webhook_token = existing.get("webhook_token") if existing else secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc).isoformat()
    await db.kotak_credentials.update_one(
        {"user_id": user.user_id},
        {
            "$set": {
                "user_id": user.user_id,
                "encrypted": encrypted,
                "webhook_token": webhook_token,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    return {"ok": True, "webhook_token": webhook_token}


@api.delete("/kotak/credentials")
async def delete_kotak_credentials(user: User = Depends(require_user)):
    await db.kotak_credentials.delete_one({"user_id": user.user_id})
    kotak_client.logout(user.user_id)
    return {"ok": True}


@api.get("/kotak/status", response_model=KotakStatus)
async def kotak_status(request: Request, user: User = Depends(require_user)):
    doc = await _get_creds_doc(user.user_id)
    if not doc:
        return KotakStatus(has_credentials=False, is_authenticated=False)
    webhook_token = doc.get("webhook_token")
    base = _base_url_from_request(request)
    return KotakStatus(
        has_credentials=True,
        is_authenticated=kotak_client.is_authenticated(user.user_id),
        webhook_token=webhook_token,
        webhook_url=f"{base}/api/webhooks/chartink/{webhook_token}" if webhook_token else None,
    )


@api.post("/kotak/test-oauth")
async def kotak_test_oauth(payload: dict, user: User = Depends(require_user)):
    """Validate JUST the consumer_key + consumer_secret pair against Kotak's
    OAuth endpoint without triggering a full login + OTP flow. Returns the
    exact Kotak response so users can debug app activation / wrong key issues.
    """
    ck = (payload.get("consumer_key") or "").strip()
    cs = (payload.get("consumer_secret") or "").strip()
    env = (payload.get("environment") or "prod").lower()
    if not ck or not cs:
        # Fall back to saved credentials
        doc = await _get_creds_doc(user.user_id)
        if not doc:
            raise HTTPException(status_code=400, detail="Provide consumer_key + consumer_secret or save credentials first")
        saved = decrypt_dict(doc["encrypted"])
        ck = ck or saved["consumer_key"]
        cs = cs or saved["consumer_secret"]
        env = env or (saved.get("environment") or "prod")
    return kotak_client.test_oauth(ck, cs, env)


@api.post("/kotak/login")
async def kotak_login(user: User = Depends(require_user)):
    doc = await _get_creds_doc(user.user_id)
    if not doc:
        raise HTTPException(status_code=400, detail="Save Kotak credentials first")
    creds = decrypt_dict(doc["encrypted"])
    try:
        res = kotak_client.start_login(user.user_id, creds)
    except kotak_client.KotakError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "otp_required": True, "response": res.get("response")}


@api.post("/kotak/verify-otp")
async def kotak_verify_otp(payload: KotakOtpInput, user: User = Depends(require_user)):
    try:
        res = kotak_client.complete_2fa(user.user_id, payload.otp)
    except kotak_client.KotakError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.kotak_credentials.update_one(
        {"user_id": user.user_id},
        {"$set": {"last_login_at": datetime.now(timezone.utc).isoformat(), "ucc": res.get("ucc")}},
    )
    return {"ok": True, "ucc": res.get("ucc")}


@api.post("/kotak/logout")
async def kotak_logout(user: User = Depends(require_user)):
    kotak_client.logout(user.user_id)
    return {"ok": True}


@api.get("/kotak/positions")
async def kotak_positions(user: User = Depends(require_user)):
    try:
        raw = kotak_client.get_positions(user.user_id)
    except kotak_client.KotakError as e:
        raise HTTPException(status_code=400, detail=str(e))
    positions = _normalise_positions(raw)
    return {"positions": positions, "raw_count": len(raw)}


@api.get("/kotak/holdings")
async def kotak_holdings(user: User = Depends(require_user)):
    try:
        raw = kotak_client.get_holdings(user.user_id)
    except kotak_client.KotakError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"holdings": raw}


def _normalise_positions(raw: list) -> List[dict]:
    """Kotak Neo positions come in various keys - extract a clean shape."""
    out = []
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        sym = (
            p.get("trdSym")
            or p.get("sym")
            or p.get("tradingSymbol")
            or p.get("trading_symbol")
            or p.get("symbol")
            or "UNKNOWN"
        ).upper()
        # Quantities
        def _f(*keys, default=0.0):
            for k in keys:
                v = p.get(k)
                if v not in (None, "", "0"):
                    try:
                        return float(v)
                    except Exception:
                        pass
            return default

        qty = int(_f("netTrdQtyLot", "flBuyQty", "flSellQty", "quantity", "qty", default=0))
        # Net qty = buyQty - sellQty
        buy_qty = _f("flBuyQty", "cfBuyQty", "buyQty", default=0)
        sell_qty = _f("flSellQty", "cfSellQty", "sellQty", default=0)
        net_qty = int(buy_qty - sell_qty) if (buy_qty or sell_qty) else qty
        avg = _f("buyAmt", "avgPrc", "avg_price", default=0.0)
        # Avg price: if buyAmt was total then divide
        if buy_qty and p.get("buyAmt"):
            try:
                avg = round(float(p["buyAmt"]) / buy_qty, 2)
            except Exception:
                pass
        ltp = _f("ltp", "lastPrice", "last_price", default=None) or None
        pnl = _f("urMtoM", "rlzdPnL", "mtom", default=None) or None
        out.append(
            {
                "broker": "kotak_neo",
                "symbol": sym,
                "exchange_segment": p.get("exSeg") or p.get("exchange_segment") or "nse_cm",
                "quantity": net_qty,
                "avg_price": round(avg, 2) if avg else 0.0,
                "ltp": round(ltp, 2) if ltp else None,
                "pnl": round(pnl, 2) if pnl else None,
                "product": p.get("prod") or p.get("product"),
            }
        )
    # Only open positions
    return [o for o in out if o["quantity"] != 0]


# =============================================================================
# DHAN
# =============================================================================

@api.post("/dhan/credentials")
async def dhan_save_credentials(payload: DhanCredentialsInput, user: User = Depends(require_user)):
    creds = {k: v.strip() for k, v in payload.model_dump().items()}
    encrypted = encrypt_dict(creds)
    await db.dhan_credentials.update_one(
        {"user_id": user.user_id},
        {"$set": {"user_id": user.user_id, "encrypted": encrypted,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"ok": True}


@api.delete("/dhan/credentials")
async def dhan_delete_credentials(user: User = Depends(require_user)):
    await db.dhan_credentials.delete_one({"user_id": user.user_id})
    dhan_client.disconnect(user.user_id)
    return {"ok": True}


@api.get("/dhan/status")
async def dhan_status(user: User = Depends(require_user)):
    doc = await db.dhan_credentials.find_one({"user_id": user.user_id}, {"_id": 0})
    return {
        "has_credentials": bool(doc),
        "is_authenticated": dhan_client.is_authenticated(user.user_id),
        "last_login_at": (doc or {}).get("last_login_at"),
    }


@api.post("/dhan/connect")
async def dhan_connect(user: User = Depends(require_user)):
    doc = await db.dhan_credentials.find_one({"user_id": user.user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=400, detail="Save Dhan credentials first")
    creds = decrypt_dict(doc["encrypted"])
    try:
        dhan_client.connect(user.user_id, creds["client_id"], creds["access_token"])
    except dhan_client.DhanError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.dhan_credentials.update_one(
        {"user_id": user.user_id},
        {"$set": {"last_login_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True}


@api.post("/dhan/disconnect")
async def dhan_disconnect(user: User = Depends(require_user)):
    dhan_client.disconnect(user.user_id)
    return {"ok": True}


@api.get("/dhan/positions")
async def dhan_positions(user: User = Depends(require_user)):
    try:
        return {"positions": dhan_client.get_positions(user.user_id)}
    except dhan_client.DhanError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# ALICE BLUE
# =============================================================================

@api.post("/alice/credentials")
async def alice_save_credentials(payload: AliceCredentialsInput, user: User = Depends(require_user)):
    creds = {k: v.strip() for k, v in payload.model_dump().items()}
    encrypted = encrypt_dict(creds)
    await db.alice_credentials.update_one(
        {"user_id": user.user_id},
        {"$set": {"user_id": user.user_id, "encrypted": encrypted,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"ok": True}


@api.delete("/alice/credentials")
async def alice_delete_credentials(user: User = Depends(require_user)):
    await db.alice_credentials.delete_one({"user_id": user.user_id})
    alice_client.disconnect(user.user_id)
    return {"ok": True}


@api.get("/alice/status")
async def alice_status(user: User = Depends(require_user)):
    doc = await db.alice_credentials.find_one({"user_id": user.user_id}, {"_id": 0})
    return {
        "has_credentials": bool(doc),
        "is_authenticated": alice_client.is_authenticated(user.user_id),
        "last_login_at": (doc or {}).get("last_login_at"),
    }


@api.post("/alice/connect")
async def alice_connect(user: User = Depends(require_user)):
    doc = await db.alice_credentials.find_one({"user_id": user.user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=400, detail="Save Alice Blue credentials first")
    creds = decrypt_dict(doc["encrypted"])
    try:
        alice_client.connect(user.user_id, creds["user_id"], creds["api_key"])
    except alice_client.AliceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.alice_credentials.update_one(
        {"user_id": user.user_id},
        {"$set": {"last_login_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True}


@api.post("/alice/disconnect")
async def alice_disconnect(user: User = Depends(require_user)):
    alice_client.disconnect(user.user_id)
    return {"ok": True}


@api.get("/alice/positions")
async def alice_positions(user: User = Depends(require_user)):
    try:
        return {"positions": alice_client.get_positions(user.user_id)}
    except alice_client.AliceError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# INDMONEY
# =============================================================================

@api.post("/indmoney/credentials")
async def indmoney_save_credentials(payload: IndMoneyCredentialsInput, user: User = Depends(require_user)):
    creds = {k: v.strip() for k, v in payload.model_dump().items()}
    encrypted = encrypt_dict(creds)
    await db.indmoney_credentials.update_one(
        {"user_id": user.user_id},
        {"$set": {"user_id": user.user_id, "encrypted": encrypted,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"ok": True}


@api.delete("/indmoney/credentials")
async def indmoney_delete_credentials(user: User = Depends(require_user)):
    await db.indmoney_credentials.delete_one({"user_id": user.user_id})
    indmoney_client.disconnect(user.user_id)
    return {"ok": True}


@api.get("/indmoney/status")
async def indmoney_status(user: User = Depends(require_user)):
    doc = await db.indmoney_credentials.find_one({"user_id": user.user_id}, {"_id": 0})
    return {
        "has_credentials": bool(doc),
        "is_authenticated": indmoney_client.is_authenticated(user.user_id),
        "last_login_at": (doc or {}).get("last_login_at"),
    }


@api.post("/indmoney/connect")
async def indmoney_connect(user: User = Depends(require_user)):
    doc = await db.indmoney_credentials.find_one({"user_id": user.user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=400, detail="Save INDmoney credentials first")
    creds = decrypt_dict(doc["encrypted"])
    try:
        indmoney_client.connect(user.user_id, creds["access_token"])
    except indmoney_client.IndMoneyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.indmoney_credentials.update_one(
        {"user_id": user.user_id},
        {"$set": {"last_login_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True}


@api.post("/indmoney/disconnect")
async def indmoney_disconnect(user: User = Depends(require_user)):
    indmoney_client.disconnect(user.user_id)
    return {"ok": True}


@api.get("/indmoney/positions")
async def indmoney_positions(user: User = Depends(require_user)):
    try:
        return {"positions": indmoney_client.get_positions(user.user_id)}
    except indmoney_client.IndMoneyError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Delta Exchange
# ---------------------------------------------------------------------------

@api.post("/delta/credentials")
async def delta_save_credentials(payload: DeltaCredentialsInput, user: User = Depends(require_user)):
    creds = {k: v.strip() if isinstance(v, str) else v for k, v in payload.model_dump().items()}
    encrypted = encrypt_dict(creds)
    await db.delta_credentials.update_one(
        {"user_id": user.user_id},
        {"$set": {"user_id": user.user_id, "encrypted": encrypted,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"ok": True}


@api.delete("/delta/credentials")
async def delta_delete_credentials(user: User = Depends(require_user)):
    await db.delta_credentials.delete_one({"user_id": user.user_id})
    delta_client.disconnect(user.user_id)
    return {"ok": True}


@api.get("/delta/status")
async def delta_status(user: User = Depends(require_user)):
    doc = await db.delta_credentials.find_one({"user_id": user.user_id}, {"_id": 0})
    return {
        "has_credentials": bool(doc),
        "is_authenticated": delta_client.is_authenticated(user.user_id),
        "last_login_at": (doc or {}).get("last_login_at"),
    }


@api.post("/delta/connect")
async def delta_connect(user: User = Depends(require_user)):
    doc = await db.delta_credentials.find_one({"user_id": user.user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=400, detail="Save Delta Exchange credentials first")
    creds = decrypt_dict(doc["encrypted"])
    try:
        delta_client.connect(user.user_id, creds["api_key"], creds["api_secret"], creds.get("environment", "india_prod"))
    except delta_client.DeltaError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.delta_credentials.update_one(
        {"user_id": user.user_id},
        {"$set": {"last_login_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True}


@api.post("/delta/disconnect")
async def delta_disconnect(user: User = Depends(require_user)):
    delta_client.disconnect(user.user_id)
    return {"ok": True}


@api.get("/delta/positions")
async def delta_positions(user: User = Depends(require_user)):
    try:
        return {"positions": delta_client.get_positions(user.user_id)}
    except delta_client.DeltaError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# UNIFIED BROKERS & POSITIONS
# =============================================================================

async def _ensure_user_webhook_token(user_id: str) -> str:
    """Get or generate a user-level webhook token."""
    doc = await db.user_webhooks.find_one({"user_id": user_id}, {"_id": 0})
    if doc and doc.get("webhook_token"):
        return doc["webhook_token"]
    # Fallback: reuse existing kotak webhook_token if present (backward compat)
    legacy = await db.kotak_credentials.find_one({"user_id": user_id}, {"_id": 0})
    token = (legacy or {}).get("webhook_token") or secrets.token_urlsafe(24)
    await db.user_webhooks.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "webhook_token": token}},
        upsert=True,
    )
    return token


@api.get("/brokers/status")
async def brokers_status(request: Request, user: User = Depends(require_user)):
    kotak_doc = await _get_creds_doc(user.user_id)
    dhan_doc = await db.dhan_credentials.find_one({"user_id": user.user_id}, {"_id": 0})
    alice_doc = await db.alice_credentials.find_one({"user_id": user.user_id}, {"_id": 0})
    indmoney_doc = await db.indmoney_credentials.find_one({"user_id": user.user_id}, {"_id": 0})
    delta_doc = await db.delta_credentials.find_one({"user_id": user.user_id}, {"_id": 0})
    webhook_token = await _ensure_user_webhook_token(user.user_id)
    base = _base_url_from_request(request)
    return {
        "kotak_neo": {
            "has_credentials": bool(kotak_doc),
            "is_authenticated": kotak_client.is_authenticated(user.user_id),
            "ucc": (kotak_doc or {}).get("ucc"),
            "last_login_at": (kotak_doc or {}).get("last_login_at"),
        },
        "dhan": {
            "has_credentials": bool(dhan_doc),
            "is_authenticated": dhan_client.is_authenticated(user.user_id),
            "last_login_at": (dhan_doc or {}).get("last_login_at"),
        },
        "alice_blue": {
            "has_credentials": bool(alice_doc),
            "is_authenticated": alice_client.is_authenticated(user.user_id),
            "last_login_at": (alice_doc or {}).get("last_login_at"),
        },
        "indmoney": {
            "has_credentials": bool(indmoney_doc),
            "is_authenticated": indmoney_client.is_authenticated(user.user_id),
            "last_login_at": (indmoney_doc or {}).get("last_login_at"),
        },
        "delta_exchange": {
            "has_credentials": bool(delta_doc),
            "is_authenticated": delta_client.is_authenticated(user.user_id),
            "last_login_at": (delta_doc or {}).get("last_login_at"),
        },
        "webhook_token": webhook_token,
        "webhook_url": f"{base}/api/webhooks/chartink/{webhook_token}",
    }


@api.get("/positions/all")
async def all_positions(user: User = Depends(require_user)):
    """Aggregate positions from all authenticated brokers."""
    positions = []
    errors = {}
    if kotak_client.is_authenticated(user.user_id):
        try:
            positions.extend(_normalise_positions(kotak_client.get_positions(user.user_id)))
        except Exception as e:
            errors["kotak_neo"] = str(e)
    if dhan_client.is_authenticated(user.user_id):
        try:
            positions.extend(dhan_client.get_positions(user.user_id))
        except Exception as e:
            errors["dhan"] = str(e)
    if alice_client.is_authenticated(user.user_id):
        try:
            positions.extend(alice_client.get_positions(user.user_id))
        except Exception as e:
            errors["alice_blue"] = str(e)
    if indmoney_client.is_authenticated(user.user_id):
        try:
            positions.extend(indmoney_client.get_positions(user.user_id))
        except Exception as e:
            errors["indmoney"] = str(e)
    if delta_client.is_authenticated(user.user_id):
        try:
            positions.extend(delta_client.get_positions(user.user_id))
        except Exception as e:
            errors["delta_exchange"] = str(e)
    return {"positions": positions, "errors": errors}


@api.get("/portfolio/risk")
async def portfolio_risk(user: User = Depends(require_user)):
    """Aggregate LONG positions across all authenticated brokers and compute
    downside risk if the EMA10 stoploss were to hit on every position.

    Per-position fields:
      symbol, broker, exchange_segment, quantity, avg_price, ltp, ema10
      current_value  = quantity * (ltp or avg_price)
      sl_value       = quantity * ema10       (None if EMA unavailable)
      risk_amount    = current_value - sl_value
      risk_pct       = risk_amount / current_value * 100

    Totals roll up only positions where ema10 is available so the % stays
    meaningful. Positions missing EMA data are reported separately.
    """
    rows = []
    errors = {}
    if kotak_client.is_authenticated(user.user_id):
        try:
            rows.extend(_normalise_positions(kotak_client.get_positions(user.user_id)))
        except Exception as e:
            errors["kotak_neo"] = str(e)
    if dhan_client.is_authenticated(user.user_id):
        try:
            rows.extend(dhan_client.get_positions(user.user_id))
        except Exception as e:
            errors["dhan"] = str(e)
    if alice_client.is_authenticated(user.user_id):
        try:
            rows.extend(alice_client.get_positions(user.user_id))
        except Exception as e:
            errors["alice_blue"] = str(e)
    if indmoney_client.is_authenticated(user.user_id):
        try:
            rows.extend(indmoney_client.get_positions(user.user_id))
        except Exception as e:
            errors["indmoney"] = str(e)

    enriched: List[dict] = []
    missing_ema: List[dict] = []
    totals = {
        "current_value": 0.0,
        "sl_value": 0.0,
        "invested": 0.0,
        "risk_amount": 0.0,
        "open_positions": 0,
    }
    for pos in rows:
        qty = int(pos.get("quantity") or 0)
        if qty <= 0:
            # Only long positions contribute to EMA10 downside risk
            continue
        symbol = pos.get("symbol") or ""
        broker = pos.get("broker") or "?"
        ex_seg = pos.get("exchange_segment") or "nse_cm"
        avg = float(pos.get("avg_price") or 0)
        ltp = pos.get("ltp")
        ltp_f = float(ltp) if ltp not in (None, "") else None
        mark_price = ltp_f if ltp_f and ltp_f > 0 else avg
        current_value = round(qty * mark_price, 2)
        invested = round(qty * avg, 2)
        ema10 = compute_ema10(symbol, ex_seg)

        item = {
            "symbol": symbol,
            "broker": broker,
            "exchange_segment": ex_seg,
            "quantity": qty,
            "avg_price": round(avg, 2),
            "ltp": round(ltp_f, 2) if ltp_f else None,
            "mark_price": round(mark_price, 2),
            "ema10": ema10,
            "current_value": current_value,
            "invested": invested,
        }
        totals["open_positions"] += 1
        totals["invested"] += invested

        if ema10 is None or ema10 <= 0:
            item["sl_value"] = None
            item["risk_amount"] = None
            item["risk_pct"] = None
            missing_ema.append(item)
            continue

        sl_value = round(qty * ema10, 2)
        risk_amount = round(current_value - sl_value, 2)
        risk_pct = round((risk_amount / current_value) * 100, 2) if current_value > 0 else 0.0
        item["sl_value"] = sl_value
        item["risk_amount"] = risk_amount
        item["risk_pct"] = risk_pct
        enriched.append(item)

        totals["current_value"] += current_value
        totals["sl_value"] += sl_value
        totals["risk_amount"] += risk_amount

    # Round totals
    for k in ("current_value", "sl_value", "invested", "risk_amount"):
        totals[k] = round(totals[k], 2)
    totals["risk_pct"] = (
        round((totals["risk_amount"] / totals["current_value"]) * 100, 2)
        if totals["current_value"] > 0
        else 0.0
    )
    totals["pnl_amount"] = round(totals["current_value"] - totals["invested"], 2)
    totals["pnl_pct"] = (
        round((totals["pnl_amount"] / totals["invested"]) * 100, 2)
        if totals["invested"] > 0
        else 0.0
    )

    return {
        "totals": totals,
        "positions": enriched,
        "positions_missing_ema": missing_ema,
        "errors": errors,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# ALERT CONFIGS
# =============================================================================

@api.get("/alerts")
async def list_alerts(user: User = Depends(require_user)):
    cur = db.alert_configs.find({"user_id": user.user_id}, {"_id": 0}).sort("created_at", -1)
    return {"alerts": [c async for c in cur]}


@api.post("/alerts")
async def create_alert(payload: AlertConfigInput, user: User = Depends(require_user)):
    cfg = AlertConfig(user_id=user.user_id, **payload.model_dump())
    doc = cfg.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.alert_configs.insert_one(doc)
    return cfg


@api.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str, user: User = Depends(require_user)):
    await db.alert_configs.delete_one({"id": alert_id, "user_id": user.user_id})
    return {"ok": True}


# =============================================================================
# SYMBOL MAPPINGS (Chartink symbol -> NSE symbol with per-symbol qty/amount)
# =============================================================================

CSV_COLUMNS = ["chartink_symbol", "nse_symbol", "quantity", "amount",
               "broker", "transaction_type", "product", "category"]


async def _resolve_mapping(user_id: str, chartink_symbol: str, broker: str):
    """Find best matching symbol mapping for (chartink_symbol, broker).
    Prefer exact broker match over '*' wildcard.
    """
    sym = chartink_symbol.upper().strip()
    cursor = db.symbol_mappings.find(
        {"user_id": user_id, "chartink_symbol": sym, "broker": {"$in": [broker, "*"]}},
        {"_id": 0},
    )
    docs = [d async for d in cursor]
    if not docs:
        return None
    # Exact broker match wins over "*"
    docs.sort(key=lambda d: 0 if d.get("broker") == broker else 1)
    return docs[0]


@api.get("/symbol-mappings")
async def list_symbol_mappings(user: User = Depends(require_user)):
    cur = db.symbol_mappings.find({"user_id": user.user_id}, {"_id": 0}).sort("chartink_symbol", 1)
    return {"mappings": [c async for c in cur]}


@api.post("/symbol-mappings")
async def create_symbol_mapping(payload: SymbolMappingInput, user: User = Depends(require_user)):
    data = payload.model_dump()
    data["chartink_symbol"] = data["chartink_symbol"].upper().strip()
    data["nse_symbol"] = data["nse_symbol"].upper().strip()
    if data.get("category") and data["category"] not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category: {data['category']}")
    mapping = SymbolMapping(user_id=user.user_id, **data)
    doc = mapping.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    # Replace any existing mapping with the same (chartink_symbol, broker) pair
    await db.symbol_mappings.delete_many({
        "user_id": user.user_id,
        "chartink_symbol": mapping.chartink_symbol,
        "broker": mapping.broker,
    })
    await db.symbol_mappings.insert_one(doc)
    return mapping


@api.put("/symbol-mappings/{mapping_id}")
async def update_symbol_mapping(mapping_id: str, payload: SymbolMappingInput, user: User = Depends(require_user)):
    data = payload.model_dump(exclude_unset=True)
    if "chartink_symbol" in data:
        data["chartink_symbol"] = data["chartink_symbol"].upper().strip()
    if "nse_symbol" in data:
        data["nse_symbol"] = data["nse_symbol"].upper().strip()
    if "quantity" in data and data["quantity"] is not None:
        data["quantity"] = int(data["quantity"])
    if "amount" in data and data["amount"] is not None:
        data["amount"] = float(data["amount"])
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    r = await db.symbol_mappings.update_one(
        {"id": mapping_id, "user_id": user.user_id},
        {"$set": data},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Mapping not found")
    return {"ok": True}


@api.delete("/symbol-mappings/{mapping_id}")
async def delete_symbol_mapping(mapping_id: str, user: User = Depends(require_user)):
    await db.symbol_mappings.delete_one({"id": mapping_id, "user_id": user.user_id})
    return {"ok": True}


@api.delete("/symbol-mappings")
async def clear_symbol_mappings(user: User = Depends(require_user)):
    res = await db.symbol_mappings.delete_many({"user_id": user.user_id})
    return {"ok": True, "deleted": res.deleted_count}


@api.get("/symbol-mappings/category-amounts")
async def list_category_amounts(user: User = Depends(require_user)):
    cur = db.category_amounts.find({"user_id": user.user_id}, {"_id": 0})
    return {"amounts": [c async for c in cur]}


@api.post("/symbol-mappings/category-amounts")
async def set_category_amount(payload: CategoryAmountInput, user: User = Depends(require_user)):
    cat = payload.category.lower()
    if cat not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category: {cat}")
    await db.category_amounts.update_one(
        {"user_id": user.user_id, "category": cat},
        {"$set": {"user_id": user.user_id, "category": cat, "amount": payload.amount,
                   "created_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"ok": True}


@api.post("/symbol-mappings/upload")
async def upload_symbol_mappings_csv(request: Request, user: User = Depends(require_user)):
    """Accept a CSV with columns: chartink_symbol, nse_symbol, quantity, amount,
    broker, transaction_type, product.  Either quantity OR amount must be set.
    broker = '*' applies to all brokers.
    Replaces existing rows for matching (chartink_symbol, broker) pairs.
    """
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty body")
    try:
        text = body.decode("utf-8-sig")
    except Exception:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8")

    reader = csv.DictReader(io.StringIO(text))
    rows: List[dict] = []
    errors: List[str] = []
    line = 1
    for raw in reader:
        line += 1
        if not raw:
            continue
        # Normalise key names (allow different cases)
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        ck = row.get("chartink_symbol") or row.get("chartink") or row.get("symbol")
        ns = row.get("nse_symbol") or row.get("nse") or row.get("trading_symbol")
        if not ck or not ns:
            errors.append(f"line {line}: chartink_symbol and nse_symbol are required")
            continue
        qty_raw = row.get("quantity") or row.get("qty") or ""
        amt_raw = row.get("amount") or row.get("amt") or ""
        broker = (row.get("broker") or "*").lower() or "*"
        if broker not in ("kotak_neo", "dhan", "alice_blue", "indmoney", "delta_exchange", "*"):
            errors.append(f"line {line}: invalid broker '{broker}'")
            continue
        try:
            qty = int(qty_raw) if qty_raw else None
        except ValueError:
            errors.append(f"line {line}: quantity must be integer")
            continue
        try:
            amt = float(amt_raw) if amt_raw else None
        except ValueError:
            errors.append(f"line {line}: amount must be number")
            continue
        if not qty and not amt:
            errors.append(f"line {line}: provide quantity OR amount")
            continue
        txn = (row.get("transaction_type") or row.get("side") or "").upper()[:1] or None
        if txn and txn not in ("B", "S"):
            errors.append(f"line {line}: transaction_type must be B or S")
            continue
        prod = (row.get("product") or "").upper() or None
        if prod and prod not in ("CNC", "MIS", "NRML"):
            errors.append(f"line {line}: product must be CNC / MIS / NRML")
            continue
        category = row.get("category") or ""
        if category and category not in CATEGORIES:
            errors.append(f"line {line}: category must be one of {', '.join(CATEGORIES)}")
            continue
        rows.append({
            "id": str(uuid.uuid4()),
            "user_id": user.user_id,
            "chartink_symbol": ck.upper(),
            "nse_symbol": ns.upper(),
            "quantity": qty,
            "amount": amt,
            "broker": broker,
            "transaction_type": txn,
            "product": prod,
            "category": category or None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    if errors and not rows:
        raise HTTPException(status_code=400, detail={"errors": errors})

    inserted = 0
    replaced = 0
    for r in rows:
        existing = await db.symbol_mappings.find_one(
            {"user_id": user.user_id, "chartink_symbol": r["chartink_symbol"], "broker": r["broker"]},
            {"_id": 0},
        )
        if existing:
            await db.symbol_mappings.delete_many({
                "user_id": user.user_id,
                "chartink_symbol": r["chartink_symbol"],
                "broker": r["broker"],
            })
            replaced += 1
        await db.symbol_mappings.insert_one(r)
        inserted += 1
    return {"ok": True, "inserted": inserted, "replaced": replaced, "errors": errors}


@api.get("/symbol-mappings/csv-template")
async def symbol_mappings_csv_template(user: User = Depends(require_user)):
    """Return a sample CSV that users can download as a starting point."""
    sample = (
        ",".join(CSV_COLUMNS) + "\n"
        "RELIANCE,RELIANCE-EQ,1,,kotak_neo,B,CNC,large_cap\n"
        "TCS,TCS,,5000,dhan,B,CNC,large_cap\n"
        "INFY,INFY,5,,*,B,CNC,\n"
    )
    return Response(content=sample, media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=symbol_mappings_template.csv"})


# =============================================================================
# CHARTINK WEBHOOK
# =============================================================================

def _detect_side_from_alert_name(alert_name: str) -> Optional[str]:
    """Auto-detect transaction side from Chartink alert name.

    Convention: if the alert name contains the word 'SELL' (case-insensitive)
    we place a SELL order. If it contains 'BUY', a BUY order. Otherwise
    return None and let downstream config decide. SELL is checked first because
    it's more specific (some alerts say things like 'BUY THE DIP, SELL ON RISE').
    """
    if not alert_name:
        return None
    n = alert_name.upper()
    if "SELL" in n:
        return "S"
    if "BUY" in n:
        return "B"
    return None


@api.post("/webhooks/chartink/{token}")
async def chartink_webhook(token: str, request: Request):
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    if not payload:
        # Chartink sometimes sends form-url-encoded
        form = await request.form()
        payload = dict(form)

    # Find user by webhook token. Check the user_webhooks collection first,
    # fall back to legacy kotak_credentials.webhook_token for backward compat.
    wh = await db.user_webhooks.find_one({"webhook_token": token}, {"_id": 0})
    if wh:
        user_id = wh["user_id"]
    else:
        cred = await db.kotak_credentials.find_one({"webhook_token": token}, {"_id": 0})
        if not cred:
            raise HTTPException(status_code=404, detail="Unknown webhook token")
        user_id = cred["user_id"]

    stocks_raw = payload.get("stocks", "")
    prices_raw = payload.get("trigger_prices", "")
    alert_name = payload.get("alert_name") or payload.get("scan_name") or "chartink"
    scan_name = payload.get("scan_name")

    stocks = [s.strip().upper() for s in str(stocks_raw).split(",") if s.strip()]
    prices = []
    for p in str(prices_raw).split(","):
        p = p.strip()
        try:
            prices.append(float(p))
        except Exception:
            prices.append(None)

    wlog = WebhookLog(
        user_id=user_id,
        alert_name=alert_name,
        scan_name=scan_name,
        stocks=stocks,
        trigger_prices=[p for p in prices if p is not None],
        raw_payload=payload,
    )

    # Find matching alert config
    cfg_doc = await db.alert_configs.find_one(
        {"user_id": user_id, "alert_name": alert_name, "enabled": True}, {"_id": 0}
    )

    result_notes: List[str] = []
    placed_any = False
    if not cfg_doc:
        result_notes.append(f"No enabled config for alert '{alert_name}' - logged only.")
    else:
        broker = cfg_doc.get("broker", "kotak_neo")
        # Alert-name auto-detection wins over both alert-config and mapping side
        alert_name_side = _detect_side_from_alert_name(alert_name)
        for idx, sym in enumerate(stocks):
            price = prices[idx] if idx < len(prices) else None

            # Consult symbol mappings (per-symbol overrides on top of alert config)
            mapping = await _resolve_mapping(user_id, sym, broker)
            order_symbol = sym
            order_qty = int(cfg_doc.get("quantity") or 1)
            order_txn = cfg_doc["transaction_type"]
            order_product = cfg_doc.get("product", "CNC")
            mapping_note = ""
            if mapping:
                order_symbol = mapping.get("nse_symbol") or sym
                if mapping.get("quantity"):
                    order_qty = int(mapping["quantity"])
                elif mapping.get("amount") and price and price > 0:
                    order_qty = max(1, int(mapping["amount"] // price))
                elif mapping.get("category") and price and price > 0:
                    # Fall back to category amount
                    cat = await db.category_amounts.find_one(
                        {"user_id": user_id, "category": mapping["category"]},
                        {"_id": 0, "amount": 1},
                    )
                    if cat and cat.get("amount", 0) > 0:
                        order_qty = max(1, int(cat["amount"] // price))
                if mapping.get("transaction_type"):
                    order_txn = mapping["transaction_type"]
                if mapping.get("product"):
                    order_product = mapping["product"]
                mapping_note = f" (mapped: {sym}→{order_symbol}, qty={order_qty})"

            # Alert name BUY/SELL keyword wins last (highest priority)
            if alert_name_side:
                order_txn = alert_name_side
                mapping_note += f" [auto-side from name: {'BUY' if alert_name_side == 'B' else 'SELL'}]"

            status, order_id, msg = _route_order(
                user_id=user_id,
                broker=broker,
                symbol=order_symbol,
                transaction_type=order_txn,
                quantity=order_qty,
                product=order_product,
                exchange_segment=cfg_doc.get("exchange_segment", "nse_cm"),
            )
            if status == "success":
                placed_any = True
            tl = TradeLog(
                user_id=user_id,
                symbol=order_symbol,
                quantity=order_qty,
                price=price,
                transaction_type=order_txn,
                order_type="MKT",
                order_id=order_id,
                status=status,
                message=f"[{broker}] {msg}{mapping_note}",
                source="chartink",
            )
            tdoc = tl.model_dump()
            tdoc["created_at"] = tdoc["created_at"].isoformat()
            await db.trade_logs.insert_one(tdoc)
            result_notes.append(f"{order_symbol} [{broker}]: {status} - {msg}{mapping_note}")

    wlog.processed = True
    wlog.result_note = " | ".join(result_notes) if result_notes else None
    wdoc = wlog.model_dump()
    wdoc["created_at"] = wdoc["created_at"].isoformat()
    await db.webhook_logs.insert_one(wdoc)

    return {"ok": True, "received": True, "placed": placed_any, "notes": result_notes}


def _route_order(user_id, broker, symbol, transaction_type, quantity, product,
                 exchange_segment, order_type="MKT", price=0.0, trigger_price=0.0,
                 amo=False):
    """Unified order router. Returns (status, order_id, message)."""
    try:
        if broker == "kotak_neo":
            if not kotak_client.is_authenticated(user_id):
                return ("skipped", None, "Kotak Neo not authenticated")
            resp = kotak_client.place_order(
                user_id=user_id,
                trading_symbol=symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                order_type=order_type,
                product=product,
                exchange_segment=exchange_segment,
                price=str(price),
                trigger_price=str(trigger_price),
                amo=amo,
            )
            oid = (resp or {}).get("nOrdNo") or (resp or {}).get("orderId") or ((resp or {}).get("data") or {}).get("nOrdNo")
            return ("success", oid, f"Order placed for {symbol}")
        if broker == "dhan":
            if not dhan_client.is_authenticated(user_id):
                return ("skipped", None, "Dhan not authenticated")
            resp = dhan_client.place_order(
                user_id=user_id, symbol=symbol,
                transaction_type=transaction_type, quantity=quantity,
                order_type=order_type, product=product,
                exchange_segment="NSE_EQ" if exchange_segment.lower().startswith("nse") else "BSE_EQ",
                price=float(price), trigger_price=float(trigger_price),
                amo=amo,
            )
            return ("success", resp.get("order_id"), f"Dhan order placed for {symbol}")
        if broker == "alice_blue":
            if not alice_client.is_authenticated(user_id):
                return ("skipped", None, "Alice Blue not authenticated")
            resp = alice_client.place_order(
                user_id=user_id, symbol=symbol,
                transaction_type=transaction_type, quantity=quantity,
                order_type=order_type, product=product,
                exchange=("NSE" if exchange_segment.lower().startswith("nse") else "BSE"),
                price=float(price), trigger_price=float(trigger_price),
                amo=amo,
            )
            return ("success", resp.get("order_id"), f"Alice order placed for {symbol}")
        if broker == "indmoney":
            if not indmoney_client.is_authenticated(user_id):
                return ("skipped", None, "INDmoney not authenticated")
            resp = indmoney_client.place_order(
                user_id=user_id, symbol=symbol,
                transaction_type=transaction_type, quantity=quantity,
                order_type=order_type, product=product,
                exchange_segment=("NSE" if exchange_segment.lower().startswith("nse") else "BSE"),
                price=float(price), trigger_price=float(trigger_price),
            )
            return ("success", resp.get("order_id"), f"INDmoney order placed for {symbol}")
        if broker == "delta_exchange":
            if not delta_client.is_authenticated(user_id):
                return ("skipped", None, "Delta Exchange not authenticated")
            resp = delta_client.place_order(
                user_id=user_id, symbol=symbol,
                transaction_type=transaction_type, quantity=quantity,
                order_type=order_type, product=product,
                exchange_segment="CRYPTO",
                price=float(price), trigger_price=float(trigger_price),
            )
            return ("success", resp.get("order_id"), f"Delta order placed for {symbol}")
        return ("error", None, f"Unknown broker '{broker}'")
    except (kotak_client.KotakError, dhan_client.DhanError, alice_client.AliceError, indmoney_client.IndMoneyError, delta_client.DeltaError) as e:
        return ("error", None, str(e))
    except Exception as e:
        return ("error", None, f"unexpected: {e}")


@api.get("/webhooks/logs")
async def list_webhook_logs(user: User = Depends(require_user), limit: int = 50):
    cur = (
        db.webhook_logs.find({"user_id": user.user_id}, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )
    return {"logs": [c async for c in cur]}


# =============================================================================
# TRADE LOGS
# =============================================================================

@api.get("/trades/logs")
async def list_trade_logs(user: User = Depends(require_user), limit: int = 50):
    cur = (
        db.trade_logs.find({"user_id": user.user_id}, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )
    return {"logs": [c async for c in cur]}


# =============================================================================
# MANUAL ORDER PLACEMENT
# After-market-order (AMO) support + optional auto EMA10 stoploss after entry.
# =============================================================================

def _place_ema_sl_for(user_id: str, broker: str, symbol: str, quantity: int,
                     product: str, exchange_segment: str) -> tuple[Optional[float], Optional[str], str]:
    """Compute EMA10 for `symbol` and place a SL-SELL order at that trigger.

    Returns (ema_value, order_id, message). On failure, ema_value/order_id may
    be None and message describes why.
    """
    ema = compute_ema10(symbol, exchange_segment)
    if ema is None:
        return (None, None, "EMA10: skipped (no historical data)")

    trigger_price = round_to_tick(ema)
    limit_price = round_to_tick(ema * 0.995)
    if limit_price >= trigger_price:
        limit_price = round_to_tick(trigger_price - TICK_SIZE)
    try:
        if broker == "kotak_neo":
            resp = kotak_client.place_order(
                user_id=user_id, trading_symbol=symbol,
                transaction_type="S", quantity=quantity,
                order_type="SL", product=product,
                exchange_segment=exchange_segment,
                price=str(limit_price), trigger_price=str(trigger_price),
            )
            oid = (resp or {}).get("nOrdNo") or (resp or {}).get("orderId")
        elif broker == "dhan":
            resp = dhan_client.place_order(
                user_id=user_id, symbol=symbol,
                transaction_type="S", quantity=quantity,
                order_type="SL", product=product,
                exchange_segment="NSE_EQ" if exchange_segment.lower().startswith("nse") else "BSE_EQ",
                price=limit_price, trigger_price=trigger_price,
            )
            oid = resp.get("order_id")
        elif broker == "alice_blue":
            resp = alice_client.place_order(
                user_id=user_id, symbol=symbol,
                transaction_type="S", quantity=quantity,
                order_type="SL", product=product,
                exchange=("NSE" if exchange_segment.lower().startswith("nse") else "BSE"),
                price=limit_price, trigger_price=trigger_price,
            )
            oid = resp.get("order_id")
        elif broker == "indmoney":
            resp = indmoney_client.place_order(
                user_id=user_id, symbol=symbol,
                transaction_type="S", quantity=quantity,
                order_type="SL", product=product,
                exchange_segment=("NSE" if exchange_segment.lower().startswith("nse") else "BSE"),
                price=limit_price, trigger_price=trigger_price,
            )
            oid = resp.get("order_id")
        elif broker == "delta_exchange":
            resp = delta_client.place_order(
                user_id=user_id, symbol=symbol,
                transaction_type="S", quantity=quantity,
                order_type="SL", product=product,
                exchange_segment="CRYPTO",
                price=limit_price, trigger_price=trigger_price,
            )
            oid = resp.get("order_id")
        else:
            return (ema, None, f"EMA10: unsupported broker '{broker}'")
        return (ema, oid, f"EMA10 SL placed @ {trigger_price} (limit {limit_price})")
    except (kotak_client.KotakError, dhan_client.DhanError, alice_client.AliceError, indmoney_client.IndMoneyError, delta_client.DeltaError) as e:
        return (ema, None, f"EMA10 SL failed: {e}")
    except Exception as e:
        return (ema, None, f"EMA10 SL unexpected error: {e}")


@api.post("/orders/manual")
async def place_manual_order(payload: ManualOrderInput, user: User = Depends(require_user)):
    """Place a manual order (with optional AMO + optional EMA10 stoploss).

    Body fields:
      broker, symbol, transaction_type (B|S), quantity, order_type (MKT|L),
      price (for limit orders), product (CNC|MIS|NRML), exchange_segment,
      amo (bool), auto_ema_sl (bool — places a SL-SELL after a long entry only).
    """
    broker = payload.broker
    if broker not in ("kotak_neo", "dhan", "alice_blue", "indmoney", "delta_exchange"):
        raise HTTPException(status_code=400, detail=f"Unsupported broker '{broker}'")

    # Place the main order
    status, order_id, msg = _route_order(
        user_id=user.user_id,
        broker=broker,
        symbol=payload.symbol.upper().strip(),
        transaction_type=payload.transaction_type,
        quantity=int(payload.quantity),
        product=payload.product,
        exchange_segment=payload.exchange_segment,
        order_type=payload.order_type,
        price=payload.price,
        amo=payload.amo,
    )

    main_log_msg = f"[{broker}{' AMO' if payload.amo else ''}] {msg}"
    tl = TradeLog(
        user_id=user.user_id,
        symbol=payload.symbol.upper().strip(),
        quantity=int(payload.quantity),
        price=payload.price if payload.order_type.upper() in ("L", "LIMIT") else None,
        transaction_type=payload.transaction_type,
        order_type=payload.order_type,
        order_id=order_id,
        status=status,
        message=main_log_msg,
        source="manual",
    )
    tdoc = tl.model_dump()
    tdoc["created_at"] = tdoc["created_at"].isoformat()
    await db.trade_logs.insert_one(tdoc)

    response = {
        "ok": status == "success",
        "status": status,
        "order_id": order_id,
        "message": main_log_msg,
        "ema_sl": None,
    }

    if status == "error":
        # Surface the broker error to the caller as 400 so the FE can show it
        raise HTTPException(status_code=400, detail=msg)
    if status == "skipped":
        # 200 with ok:false — broker is not authenticated yet. FE will warn.
        return response

    # status == "success" beyond this point.
    # Only auto-place an EMA10 SL when:
    #   - the entry was a BUY (we want to protect a long),
    #   - the entry was a MARKET order (so we know it filled immediately),
    #   - AMO is OFF (otherwise the entry hasn't filled yet — SL would
    #     trigger before there's a position).
    sl_skipped_reason = None
    if payload.auto_ema_sl:
        if payload.transaction_type.upper() not in ("B", "BUY"):
            sl_skipped_reason = "auto-SL only applies to BUY entries"
        elif payload.amo:
            sl_skipped_reason = "AMO: SL will be set by the next daily EMA10 run"
        elif payload.order_type.upper() in ("L", "LIMIT"):
            sl_skipped_reason = "Limit entry: SL skipped (run EMA10 SL after fill)"

    if payload.auto_ema_sl and sl_skipped_reason is None:
        ema, sl_oid, sl_msg = _place_ema_sl_for(
            user_id=user.user_id,
            broker=broker,
            symbol=payload.symbol.upper().strip(),
            quantity=int(payload.quantity),
            product=payload.product,
            exchange_segment=payload.exchange_segment,
        )
        sl_status = "placed" if sl_oid else ("skipped" if ema is None else "error")
        run = EmaSlRun(
            user_id=user.user_id,
            symbol=f"{payload.symbol.upper().strip()} [{broker}]",
            quantity=int(payload.quantity),
            ema10=ema,
            sl_trigger=ema,
            order_id=sl_oid,
            status=sl_status,
            message=sl_msg,
        )
        rdoc = run.model_dump()
        rdoc["created_at"] = rdoc["created_at"].isoformat()
        await db.ema_sl_runs.insert_one(rdoc)

        # Also append to trade logs so it shows in the dashboard log
        tl_sl = TradeLog(
            user_id=user.user_id,
            symbol=payload.symbol.upper().strip(),
            quantity=int(payload.quantity),
            price=ema,
            transaction_type="S",
            order_type="SL",
            order_id=sl_oid,
            status=sl_status,
            message=f"[{broker}] {sl_msg}",
            source="manual_ema_sl",
        )
        sdoc = tl_sl.model_dump()
        sdoc["created_at"] = sdoc["created_at"].isoformat()
        await db.trade_logs.insert_one(sdoc)

        response["ema_sl"] = {
            "ema10": ema,
            "status": sl_status,
            "order_id": sl_oid,
            "message": sl_msg,
        }
    elif payload.auto_ema_sl and sl_skipped_reason:
        response["ema_sl"] = {
            "ema10": None,
            "status": "skipped",
            "order_id": None,
            "message": sl_skipped_reason,
        }

    return response


@api.get("/ema-preview/{symbol}")
async def ema_preview(symbol: str, exchange_segment: str = "nse_cm"):
    """Return the latest EMA10 for a symbol — used by the manual order UI
    to preview the stoploss trigger before placing the order."""
    ema = compute_ema10(symbol, exchange_segment)
    trigger = round_to_tick(ema) if ema else None
    sl_limit = round_to_tick(ema * 0.995) if ema else None
    return {"symbol": symbol.upper(), "exchange_segment": exchange_segment,
            "ema10": ema, "sl_trigger": trigger,
            "sl_limit": sl_limit}


# =============================================================================
# EMA10 STOPLOSS RUN
# =============================================================================

async def _run_ema_sl_for_user(user_id: str, connected: Optional[dict] = None) -> dict:
    """Core EMA SL logic — shared by POST /ema-sl/run and the background scheduler."""
    if connected is None:
        connected = {
            "kotak_neo": kotak_client.is_authenticated(user_id),
            "dhan": dhan_client.is_authenticated(user_id),
            "alice_blue": alice_client.is_authenticated(user_id),
            "indmoney": indmoney_client.is_authenticated(user_id),
            "delta_exchange": delta_client.is_authenticated(user_id),
        }

    # Aggregate positions across all connected brokers
    all_positions: List[dict] = []
    if connected.get("kotak_neo"):
        try:
            all_positions.extend(_normalise_positions(kotak_client.get_positions(user_id)))
        except Exception as e:
            logger.warning("kotak positions fetch failed: %s", e)
    if connected.get("dhan"):
        try:
            all_positions.extend(dhan_client.get_positions(user_id))
        except Exception as e:
            logger.warning("dhan positions fetch failed: %s", e)
    if connected.get("alice_blue"):
        try:
            all_positions.extend(alice_client.get_positions(user_id))
        except Exception as e:
            logger.warning("alice positions fetch failed: %s", e)
    if connected.get("indmoney"):
        try:
            all_positions.extend(indmoney_client.get_positions(user_id))
        except Exception as e:
            logger.warning("indmoney positions fetch failed: %s", e)
    if connected.get("delta_exchange"):
        try:
            all_positions.extend(delta_client.get_positions(user_id))
        except Exception as e:
            logger.warning("delta positions fetch failed: %s", e)

    runs: List[dict] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for pos in all_positions:
        if pos["quantity"] <= 0:
            continue  # Only long positions
        sym = pos["symbol"]
        broker = pos.get("broker", "kotak_neo")
        ema = compute_ema10(sym, pos.get("exchange_segment", "nse_cm"))
        run = EmaSlRun(
            user_id=user_id,
            symbol=f"{sym} [{broker}]",
            quantity=pos["quantity"],
            ema10=ema,
            sl_trigger=ema,
            status="pending",
        )
        if ema is None:
            run.status = "skipped"
            run.message = "Could not fetch historical data for EMA10"
        else:
            try:
                trigger_price = round_to_tick(ema)
                limit_price = round_to_tick(ema * 0.995)
                if limit_price >= trigger_price:
                    limit_price = round_to_tick(trigger_price - TICK_SIZE)
                if broker == "kotak_neo":
                    resp = kotak_client.place_order(
                        user_id=user_id,
                        trading_symbol=sym,
                        transaction_type="S",
                        quantity=pos["quantity"],
                        order_type="SL",
                        product=pos.get("product") or "CNC",
                        exchange_segment=pos.get("exchange_segment", "nse_cm"),
                        price=str(limit_price),
                        trigger_price=str(trigger_price),
                    )
                    run.order_id = (resp or {}).get("nOrdNo") or (resp or {}).get("orderId")
                elif broker == "dhan":
                    resp = dhan_client.place_order(
                        user_id=user_id, symbol=sym,
                        transaction_type="S", quantity=pos["quantity"],
                        order_type="SL", product=pos.get("product") or "CNC",
                        exchange_segment=pos.get("exchange_segment", "NSE_EQ"),
                        price=limit_price, trigger_price=trigger_price,
                        security_id=pos.get("security_id"),
                    )
                    run.order_id = resp.get("order_id")
                elif broker == "alice_blue":
                    resp = alice_client.place_order(
                        user_id=user_id, symbol=sym,
                        transaction_type="S", quantity=pos["quantity"],
                        order_type="SL", product=pos.get("product") or "CNC",
                        exchange=("NSE" if str(pos.get("exchange_segment", "NSE")).upper().startswith("NSE") else "BSE"),
                        price=limit_price, trigger_price=trigger_price,
                    )
                    run.order_id = resp.get("order_id")
                elif broker == "indmoney":
                    resp = indmoney_client.place_order(
                        user_id=user_id, symbol=sym,
                        transaction_type="S", quantity=pos["quantity"],
                        order_type="SL", product=pos.get("product") or "CNC",
                        exchange_segment=("NSE" if str(pos.get("exchange_segment", "NSE")).upper().startswith("NSE") else "BSE"),
                        price=limit_price, trigger_price=trigger_price,
                    )
                    run.order_id = resp.get("order_id")
                elif broker == "delta_exchange":
                    resp = delta_client.place_order(
                        user_id=user_id, symbol=sym,
                        transaction_type="S", quantity=pos["quantity"],
                        order_type="SL", product=pos.get("product") or "CNC",
                        exchange_segment="CRYPTO",
                        price=limit_price, trigger_price=trigger_price,
                    )
                    run.order_id = resp.get("order_id")
                run.status = "placed"
                run.message = f"SL placed at {trigger_price} (limit {limit_price}) on {broker}"
            except (kotak_client.KotakError, dhan_client.DhanError, alice_client.AliceError, indmoney_client.IndMoneyError, delta_client.DeltaError) as e:
                run.status = "error"
                run.message = str(e)
            except Exception as e:
                run.status = "error"
                run.message = f"unexpected: {e}"
        rdoc = run.model_dump()
        rdoc["created_at"] = rdoc["created_at"].isoformat()
        await db.ema_sl_runs.insert_one(rdoc)

        tl = TradeLog(
            user_id=user_id,
            symbol=sym,
            quantity=run.quantity,
            price=ema,
            transaction_type="S",
            order_type="SL",
            order_id=run.order_id,
            status=run.status,
            message=f"[{broker}] {run.message}",
            source="ema_sl",
        )
        tdoc = tl.model_dump()
        tdoc["created_at"] = tdoc["created_at"].isoformat()
        await db.trade_logs.insert_one(tdoc)
        runs.append(run.model_dump(mode="json"))

    return {"ok": True, "count": len(runs), "runs": runs, "ran_at": now_iso}


@api.post("/ema-sl/run")
async def ema_sl_run(user: User = Depends(require_user)):
    connected = {
        "kotak_neo": kotak_client.is_authenticated(user.user_id),
        "dhan": dhan_client.is_authenticated(user.user_id),
        "alice_blue": alice_client.is_authenticated(user.user_id),
        "indmoney": indmoney_client.is_authenticated(user.user_id),
        "delta_exchange": delta_client.is_authenticated(user.user_id),
    }
    if not any(connected.values()):
        raise HTTPException(status_code=400, detail="No broker authenticated. Connect at least one.")
    return await _run_ema_sl_for_user(user.user_id, connected)


@api.get("/ema-sl/logs")
async def list_ema_logs(user: User = Depends(require_user), limit: int = 50):
    cur = (
        db.ema_sl_runs.find({"user_id": user.user_id}, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )
    return {"logs": [c async for c in cur]}


# ---------------------------------------------------------------------------
# EMA SCHEDULE
# ---------------------------------------------------------------------------

@api.get("/ema-sl/schedule")
async def get_ema_schedule(user: User = Depends(require_user)):
    doc = await db.ema_schedules.find_one({"user_id": user.user_id}, {"_id": 0})
    return {"schedule": doc if doc else None}


@api.post("/ema-sl/schedule")
async def set_ema_schedule(payload: EmaScheduleInput, user: User = Depends(require_user)):
    now = datetime.now(timezone.utc)
    interval = payload.interval
    if interval not in ("1h", "2h", "daily"):
        raise HTTPException(status_code=400, detail="interval must be 1h, 2h, or daily")
    next_run = _calc_next_run(interval, now)
    await db.ema_schedules.update_one(
        {"user_id": user.user_id},
        {"$set": {
            "user_id": user.user_id,
            "interval": interval,
            "enabled": payload.enabled,
            "next_run_at": next_run.isoformat(),
            "created_at": now.isoformat(),
        }},
        upsert=True,
    )
    return {"ok": True, "next_run_at": next_run.isoformat()}


@api.delete("/ema-sl/schedule")
async def delete_ema_schedule(user: User = Depends(require_user)):
    await db.ema_schedules.delete_one({"user_id": user.user_id})
    return {"ok": True}


def _calc_next_run(interval: str, now: datetime) -> datetime:
    """Compute the next run time for a given interval."""
    if interval == "1h":
        return (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    elif interval == "2h":
        return (now + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    else:  # daily
        nxt = (now + timedelta(days=1)).replace(hour=9, minute=15, second=0, microsecond=0)
        # If today's market hasn't started yet, schedule for today
        today_915 = now.replace(hour=9, minute=15, second=0, microsecond=0)
        if now < today_915:
            return today_915
        return nxt


async def _ema_scheduler_loop():
    """Background loop: checks MongoDB every 30s for due EMA schedules."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            cursor = db.ema_schedules.find({"enabled": True, "next_run_at": {"$lte": now.isoformat()}}, {"_id": 0})
            schedules = [s async for s in cursor]
            for sched in schedules:
                uid = sched["user_id"]
                logger.info("[scheduler] running EMA SL for user %s", uid)
                try:
                    await _run_ema_sl_for_user(uid)
                except Exception as e:
                    logger.error("[scheduler] EMA run failed for %s: %s", uid, e)
                # Update next run
                nxt = _calc_next_run(sched["interval"], datetime.now(timezone.utc))
                await db.ema_schedules.update_one(
                    {"user_id": uid},
                    {"$set": {"last_run_at": datetime.now(timezone.utc).isoformat(),
                               "next_run_at": nxt.isoformat()}},
                )
        except Exception as e:
            logger.error("[scheduler] loop error: %s", e)
        await asyncio.sleep(30)


# =============================================================================
# HEALTH
# =============================================================================

@api.get("/")
async def root():
    return {"service": "ChartinkTrade API", "status": "ok"}


@api.get("/health")
async def health():
    return {"status": "healthy", "ts": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# BACKTEST
# ---------------------------------------------------------------------------

@api.post("/backtest/run")
async def run_backtest_endpoint(user: User = Depends(require_user), symbols: str = "", period: str = "1y"):
    """Run the screening backtest. `symbols` is a comma-separated list;
    if empty the default NIFTY_100 universe is scanned.
    """
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    return await run_backtest(sym_list, period)


@api.post("/backtest/signals")
async def upload_backtest_signals(user: User = Depends(require_user), request: Request = None):
    """Upload a CSV of backtest signals (date,symbol,marketcapname,sector)
    and evaluate the screening criteria on each signal's date.
    """
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty body")
    try:
        text = body.decode("utf-8-sig")
    except Exception:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8")

    reader = csv.DictReader(io.StringIO(text))
    signals: List[dict] = []
    errors: List[str] = []
    line = 1
    for raw in reader:
        line += 1
        if not raw:
            continue
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        dt = row.get("date", "")
        sym = row.get("symbol", "") or row.get("ticker", "")
        mcap = row.get("marketcapname", "") or row.get("marketcap", "") or row.get("cap", "")
        sec = row.get("sector", "")
        if not dt or not sym:
            errors.append(f"line {line}: date and symbol are required")
            continue
        signals.append({"date": dt, "symbol": sym.upper(), "marketcapname": mcap, "sector": sec})

    if not signals:
        raise HTTPException(status_code=400, detail={"errors": errors or ["No valid rows found"]})

    result = await run_signal_backtest(signals)
    result["errors"] = errors
    return result


@api.get("/backtest/symbols")
async def list_backtest_symbols(user: User = Depends(require_user)):
    """Return the default backtest universe (NIFTY 100)."""
    return {"symbols": NIFTY_100}


# =============================================================================
# DEPLOYMENT / SEBI COMPLIANCE
# =============================================================================

def _detect_platform() -> tuple[str, bool]:
    """Return (platform_label, is_static_ip_capable)."""
    # Emergent preview injects these via ingress, outbound IP is shared/not static
    host = os.environ.get("HOSTNAME", "")
    if "emergent" in os.environ.get("KUBERNETES_SERVICE_HOST", "").lower() or \
       os.environ.get("EMERGENT_DEPLOYMENT") or host.startswith("app-"):
        return ("Emergent preview", False)
    if os.environ.get("STATIC_IP_DEPLOYMENT", "").lower() in ("1", "true", "yes"):
        return (os.environ.get("DEPLOYMENT_NAME", "Self-hosted VPS"), True)
    # Default: unknown — assume preview/dev
    return ("Emergent preview", False)


@api.get("/deployment/info")
async def deployment_info():
    """Return the current outbound IP and SEBI-compliance guidance.

    The app itself cannot make the IP static — that is a property of the
    hosting environment. Emergent preview uses pooled outbound IPs. For
    SEBI-regulated algo trading you must self-host on a VPS with a reserved
    static IP (DigitalOcean, AWS Elastic IP, Linode, Hetzner) and whitelist
    that IP with Kotak Neo.
    """
    ip = None
    source = None
    services = [
        ("https://api.ipify.org?format=json", "ip"),
        ("https://ifconfig.me/ip", None),
        ("https://icanhazip.com", None),
    ]
    for url, key in services:
        try:
            r = requests.get(url, timeout=3)
            if r.status_code != 200:
                continue
            if key:
                ip = r.json().get(key)
            else:
                ip = r.text.strip()
            source = url
            if ip:
                break
        except Exception:
            continue

    platform, is_static = _detect_platform()

    return {
        "outbound_ip": ip,
        "ip_lookup_source": source,
        "platform": platform,
        "is_static_ip": is_static,
        "sebi_compliant": is_static,
        "guidance": (
            "This deployment uses a POOLED outbound IP. For SEBI-regulated "
            "algorithmic trading, self-host on a VPS with a reserved static IP "
            "(DigitalOcean + Reserved IP, AWS + Elastic IP, Linode, Hetzner) "
            "and set STATIC_IP_DEPLOYMENT=true in the environment."
            if not is_static
            else (
                "Static-IP deployment detected. Whitelist the IP above with "
                "Kotak Neo and register it per SEBI algo-trading requirements."
            )
        ),
    }


# Mount router
app.include_router(api)

# Email + password auth router (lives under /api/auth alongside Google flow)
app.include_router(auth_service.build_router(db), prefix="/api/auth")


@app.on_event("startup")
async def _startup():
    await auth_service.ensure_indexes(db)
    await auth_service.seed_admin(db)
    _scheduler_task = asyncio.create_task(_ema_scheduler_loop())

# CORS
# IMPORTANT: when allow_credentials=True the browser rejects
# `Access-Control-Allow-Origin: *`. We use allow_origin_regex so Starlette
# echoes the caller's Origin header, which is the only valid combo with
# credentials and avoids the "Login failed" loop on the Google sign-in callback.
_cors_origins_env = os.environ.get("CORS_ORIGINS", "").strip()
_cors_kwargs = dict(
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if not _cors_origins_env:
    _cors_kwargs["allow_origin_regex"] = ".*"
elif _cors_origins_env == "*":
    _cors_kwargs["allow_origin_regex"] = ".*"
else:
    _cors_kwargs["allow_origins"] = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]

app.add_middleware(CORSMiddleware, **_cors_kwargs)


@app.on_event("shutdown")
async def _shutdown():
    mongo_client.close()
