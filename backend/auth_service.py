"""Email + password authentication service.

Lives side-by-side with the existing Emergent Google OAuth flow in `server.py`.
Tokens are JWT; clients can either keep the httpOnly cookie OR send the token
as `Authorization: Bearer <token>` (we use the latter on the preview ingress
because the ingress force-sets `ACAO: *` + `Allow-Credentials: true` which
browsers reject when `withCredentials` is on).
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
ACCESS_TTL = timedelta(days=7)
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW = timedelta(minutes=15)


def _jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + ACCESS_TTL,
        "type": "access",
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Pydantic input/output models
# ---------------------------------------------------------------------------
class RegisterInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@", 1)[1]:
            raise ValueError("Enter a valid email address.")
        return v


class LoginInput(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower()


# ---------------------------------------------------------------------------
# Brute-force lockout (per IP + email pair)
# ---------------------------------------------------------------------------
async def _check_lockout(db, identifier: str) -> None:
    doc = await db.login_attempts.find_one({"identifier": identifier}, {"_id": 0})
    if not doc:
        return
    locked_until = doc.get("locked_until")
    if locked_until:
        if isinstance(locked_until, str):
            locked_until = datetime.fromisoformat(locked_until)
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > datetime.now(timezone.utc):
            wait_seconds = int((locked_until - datetime.now(timezone.utc)).total_seconds())
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Try again in {wait_seconds // 60 + 1} min.",
            )


async def _record_failed_login(db, identifier: str) -> None:
    now = datetime.now(timezone.utc)
    doc = await db.login_attempts.find_one({"identifier": identifier}, {"_id": 0}) or {}
    attempts = int(doc.get("attempts") or 0) + 1
    update = {"attempts": attempts, "last_failed_at": now.isoformat(), "identifier": identifier}
    if attempts >= MAX_FAILED_ATTEMPTS:
        update["locked_until"] = (now + LOCKOUT_WINDOW).isoformat()
        update["attempts"] = 0  # reset after locking so user gets fresh window
    await db.login_attempts.update_one(
        {"identifier": identifier}, {"$set": update}, upsert=True
    )


async def _clear_failed_logins(db, identifier: str) -> None:
    await db.login_attempts.delete_one({"identifier": identifier})


# ---------------------------------------------------------------------------
# Session creation (shared with Google OAuth's user_sessions collection so the
# existing `require_user` dependency in server.py keeps working unchanged).
# ---------------------------------------------------------------------------
async def _create_session(db, user_id: str, email: str, response: Response) -> str:
    token = create_access_token(user_id, email)
    now = datetime.now(timezone.utc)
    await db.user_sessions.insert_one(
        {
            "user_id": user_id,
            "session_token": token,
            "expires_at": (now + ACCESS_TTL).isoformat(),
            "created_at": now.isoformat(),
            "auth_method": "password",
        }
    )
    # Best-effort cookie (some browsers reject on preview ingress; Bearer is canonical)
    response.set_cookie(
        key="session_token",
        value=token,
        max_age=int(ACCESS_TTL.total_seconds()),
        path="/",
        httponly=True,
        secure=True,
        samesite="none",
    )
    return token


# ---------------------------------------------------------------------------
# Router (mounted under /api/auth from server.py)
# ---------------------------------------------------------------------------
def build_router(db) -> APIRouter:
    router = APIRouter()

    @router.post("/register")
    async def register(payload: RegisterInput, response: Response):
        email = payload.email.lower().strip()
        existing = await db.users.find_one({"email": email}, {"_id": 0})
        if existing and existing.get("password_hash"):
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
        now = datetime.now(timezone.utc)
        if existing:
            # Google user registering a password — link to same user_id
            user_id = existing["user_id"]
            await db.users.update_one(
                {"user_id": user_id},
                {"$set": {
                    "name": payload.name.strip() or existing.get("name"),
                    "password_hash": hash_password(payload.password),
                }},
            )
        else:
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            await db.users.insert_one(
                {
                    "user_id": user_id,
                    "email": email,
                    "name": payload.name.strip(),
                    "password_hash": hash_password(payload.password),
                    "created_at": now.isoformat(),
                }
            )
        token = await _create_session(db, user_id, email, response)
        return {
            "user": {"user_id": user_id, "email": email, "name": payload.name.strip()},
            "session_token": token,
        }

    @router.post("/login")
    async def login(payload: LoginInput, request: Request, response: Response):
        email = payload.email.lower().strip()
        ip = (request.headers.get("x-forwarded-for") or request.client.host or "?").split(",")[0].strip()
        identifier = f"{ip}:{email}"

        await _check_lockout(db, identifier)

        user = await db.users.find_one({"email": email}, {"_id": 0})
        if not user or not user.get("password_hash"):
            # Tiny constant-time-ish delay to discourage user enumeration
            time.sleep(0.2)
            await _record_failed_login(db, identifier)
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        if not verify_password(payload.password, user["password_hash"]):
            await _record_failed_login(db, identifier)
            raise HTTPException(status_code=401, detail="Invalid email or password.")

        await _clear_failed_logins(db, identifier)
        token = await _create_session(db, user["user_id"], email, response)
        return {
            "user": {
                "user_id": user["user_id"],
                "email": email,
                "name": user.get("name"),
                "picture": user.get("picture"),
            },
            "session_token": token,
        }

    return router


# ---------------------------------------------------------------------------
# Startup helpers
# ---------------------------------------------------------------------------
async def ensure_indexes(db) -> None:
    try:
        await db.users.create_index("email", unique=True, sparse=True)
        await db.login_attempts.create_index("identifier", unique=True)
    except Exception as e:
        logger.warning("ensure_indexes: %s", e)


async def seed_admin(db) -> None:
    email = (os.environ.get("ADMIN_EMAIL") or "").lower().strip()
    password = os.environ.get("ADMIN_PASSWORD") or ""
    if not email or not password:
        return
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    now = datetime.now(timezone.utc)
    if existing is None:
        await db.users.insert_one(
            {
                "user_id": f"user_{uuid.uuid4().hex[:12]}",
                "email": email,
                "name": "Admin",
                "role": "admin",
                "password_hash": hash_password(password),
                "created_at": now.isoformat(),
            }
        )
        logger.info("Seeded admin user %s", email)
    elif not existing.get("password_hash") or not verify_password(password, existing["password_hash"]):
        await db.users.update_one(
            {"email": email},
            {"$set": {"password_hash": hash_password(password), "role": existing.get("role") or "admin"}},
        )
        logger.info("Updated admin password for %s", email)
