"""FastAPI backend for the Kotak Neo + Chartink trading automation app."""
from __future__ import annotations

import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List

import requests
from dotenv import load_dotenv
from fastapi import APIRouter, Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

import kotak_client
from ema_service import compute_ema10
from models import (
    AlertConfig,
    AlertConfigInput,
    EmaSlRun,
    KotakCredentialsInput,
    KotakOtpInput,
    KotakStatus,
    TradeLog,
    User,
    WebhookLog,
)
from security import decrypt_dict, encrypt_dict

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
        }
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
    webhook_token = existing["webhook_token"] if existing else secrets.token_urlsafe(24)
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
        )
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
# CHARTINK WEBHOOK
# =============================================================================

@api.post("/webhooks/chartink/{token}")
async def chartink_webhook(token: str, request: Request):
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    if not payload:
        # Chartink sometimes sends form-url-encoded
        form = await request.form()
        payload = dict(form)

    # Find user by webhook token
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
    elif not kotak_client.is_authenticated(user_id):
        result_notes.append("Kotak Neo not authenticated - alert logged, order skipped.")
    else:
        for idx, sym in enumerate(stocks):
            price = prices[idx] if idx < len(prices) else None
            try:
                resp = kotak_client.place_order(
                    user_id=user_id,
                    trading_symbol=sym,
                    transaction_type=cfg_doc["transaction_type"],
                    quantity=int(cfg_doc["quantity"]),
                    order_type="MKT",
                    product=cfg_doc.get("product", "CNC"),
                    exchange_segment=cfg_doc.get("exchange_segment", "nse_cm"),
                )
                status = "success"
                order_id = None
                if isinstance(resp, dict):
                    order_id = resp.get("nOrdNo") or resp.get("orderId") or resp.get("data", {}).get("nOrdNo")
                msg = f"Order placed for {sym}"
                placed_any = True
            except kotak_client.KotakError as e:
                status = "error"
                order_id = None
                msg = str(e)
            tl = TradeLog(
                user_id=user_id,
                symbol=sym,
                quantity=int(cfg_doc["quantity"]),
                price=price,
                transaction_type=cfg_doc["transaction_type"],
                order_type="MKT",
                order_id=order_id,
                status=status,
                message=msg,
                source="chartink",
            )
            tdoc = tl.model_dump()
            tdoc["created_at"] = tdoc["created_at"].isoformat()
            await db.trade_logs.insert_one(tdoc)
            result_notes.append(f"{sym}: {status} - {msg}")

    wlog.processed = True
    wlog.result_note = " | ".join(result_notes) if result_notes else None
    wdoc = wlog.model_dump()
    wdoc["created_at"] = wdoc["created_at"].isoformat()
    await db.webhook_logs.insert_one(wdoc)

    return {"ok": True, "received": True, "placed": placed_any, "notes": result_notes}


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
# EMA10 STOPLOSS RUN
# =============================================================================

@api.post("/ema-sl/run")
async def ema_sl_run(user: User = Depends(require_user)):
    if not kotak_client.is_authenticated(user.user_id):
        raise HTTPException(status_code=400, detail="Not authenticated with Kotak Neo")
    try:
        raw = kotak_client.get_positions(user.user_id)
    except kotak_client.KotakError as e:
        raise HTTPException(status_code=400, detail=str(e))
    positions = _normalise_positions(raw)

    runs: List[dict] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for pos in positions:
        if pos["quantity"] <= 0:
            continue  # Only long positions
        sym = pos["symbol"]
        ema = compute_ema10(sym, pos.get("exchange_segment", "nse_cm"))
        run = EmaSlRun(
            user_id=user.user_id,
            symbol=sym,
            quantity=pos["quantity"],
            ema10=ema,
            sl_trigger=ema,
            status="pending",
        )
        if ema is None:
            run.status = "skipped"
            run.message = "Could not fetch historical data for EMA10"
        else:
            # Stop-loss-limit: trigger_price = ema10, price slightly below
            try:
                limit_price = round(ema * 0.995, 2)
                resp = kotak_client.place_order(
                    user_id=user.user_id,
                    trading_symbol=sym,
                    transaction_type="S",  # Sell to close long
                    quantity=pos["quantity"],
                    order_type="SL",
                    product=pos.get("product") or "CNC",
                    exchange_segment=pos.get("exchange_segment", "nse_cm"),
                    price=str(limit_price),
                    trigger_price=str(ema),
                )
                run.status = "placed"
                if isinstance(resp, dict):
                    run.order_id = resp.get("nOrdNo") or resp.get("orderId") or resp.get("data", {}).get("nOrdNo")
                run.message = f"SL placed at {ema} (limit {limit_price})"
            except kotak_client.KotakError as e:
                run.status = "error"
                run.message = str(e)
        rdoc = run.model_dump()
        rdoc["created_at"] = rdoc["created_at"].isoformat()
        await db.ema_sl_runs.insert_one(rdoc)

        # Also write to trade_logs
        tl = TradeLog(
            user_id=user.user_id,
            symbol=sym,
            quantity=run.quantity,
            price=ema,
            transaction_type="S",
            order_type="SL",
            order_id=run.order_id,
            status=run.status,
            message=run.message,
            source="ema_sl",
        )
        tdoc = tl.model_dump()
        tdoc["created_at"] = tdoc["created_at"].isoformat()
        await db.trade_logs.insert_one(tdoc)
        runs.append(run.model_dump(mode="json"))

    return {"ok": True, "count": len(runs), "runs": runs, "ran_at": now_iso}


@api.get("/ema-sl/logs")
async def list_ema_logs(user: User = Depends(require_user), limit: int = 50):
    cur = (
        db.ema_sl_runs.find({"user_id": user.user_id}, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )
    return {"logs": [c async for c in cur]}


# =============================================================================
# HEALTH
# =============================================================================

@api.get("/")
async def root():
    return {"service": "ChartinkTrade API", "status": "ok"}


@api.get("/health")
async def health():
    return {"status": "healthy", "ts": datetime.now(timezone.utc).isoformat()}


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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def _shutdown():
    mongo_client.close()
