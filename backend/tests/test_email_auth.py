"""Iteration 3: Email + password auth endpoints (alongside Google OAuth).
Covers: register (success / duplicate / validation), login (success / wrong /
lockout), /auth/me bearer flow, no _id leakage, and existing endpoint health.
"""
import os
import time
import uuid

import pytest
import requests
from pymongo import MongoClient

def _read_env(file_path, key):
    try:
        with open(file_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        return None
    return None


BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or _read_env("/app/frontend/.env", "REACT_APP_BACKEND_URL")
).rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL") or _read_env("/app/backend/.env", "MONGO_URL") or "mongodb://localhost:27017"
DB_NAME = os.environ.get("DB_NAME") or _read_env("/app/backend/.env", "DB_NAME") or "test_database"

ADMIN_EMAIL = "admin@chartink.local"
ADMIN_PASSWORD = "admin123"


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(autouse=True)
def _clear_lockout(db):
    """Ensure brute-force lockout never blocks legitimate test logins."""
    db.login_attempts.delete_many({})
    yield


@pytest.fixture()
def fresh_email():
    return f"test_{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture(scope="module")
def admin_bearer():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    token = r.json()["session_token"]
    return token


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
class TestRegister:
    def test_register_success(self, fresh_email):
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"name": "Tester", "email": fresh_email, "password": "securepass123"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "session_token" in body and isinstance(body["session_token"], str)
        assert body["user"]["email"] == fresh_email
        assert body["user"]["name"] == "Tester"
        assert "user_id" in body["user"]
        assert "_id" not in body["user"]

    def test_register_duplicate_returns_409(self, fresh_email):
        payload = {"name": "Tester", "email": fresh_email, "password": "securepass123"}
        r1 = requests.post(f"{BASE_URL}/api/auth/register", json=payload, timeout=15)
        assert r1.status_code == 200
        r2 = requests.post(f"{BASE_URL}/api/auth/register", json=payload, timeout=15)
        assert r2.status_code == 409
        assert "already exists" in r2.json()["detail"].lower()

    def test_register_short_password_422(self, fresh_email):
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"name": "X", "email": fresh_email, "password": "short1"},
            timeout=15,
        )
        assert r.status_code == 422

    def test_register_invalid_email_422(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"name": "X", "email": "not-an-email", "password": "securepass123"},
            timeout=15,
        )
        assert r.status_code == 422

    def test_register_empty_name_422(self, fresh_email):
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"name": "", "email": fresh_email, "password": "securepass123"},
            timeout=15,
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class TestLogin:
    def test_login_admin_success(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        token = body["session_token"]
        assert isinstance(token, str) and len(token) > 20
        assert body["user"]["email"] == ADMIN_EMAIL
        assert "_id" not in body["user"]
        # Token should be a JWT (3 dot-separated segments)
        assert token.count(".") == 2

    def test_login_wrong_password_401(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": "wrong_password_x"},
            timeout=15,
        )
        assert r.status_code == 401
        assert r.json()["detail"] == "Invalid email or password."

    def test_login_unknown_user_401(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": f"nouser_{uuid.uuid4().hex[:6]}@example.com", "password": "whatever1"},
            timeout=15,
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Brute-force lockout
# ---------------------------------------------------------------------------
class TestLockout:
    def test_lockout_after_5_failures(self, db):
        # Use a unique non-admin email so we don't lock out the admin
        email = f"locktest_{uuid.uuid4().hex[:8]}@example.com"
        # register first so user exists
        requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"name": "L", "email": email, "password": "rightpass123"},
            timeout=15,
        )
        db.login_attempts.delete_many({})
        last = None
        for _ in range(5):
            last = requests.post(
                f"{BASE_URL}/api/auth/login",
                json={"email": email, "password": "wrongpass1"},
                timeout=15,
            )
            assert last.status_code == 401
        # 6th attempt should hit lockout
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": "wrongpass1"},
            timeout=15,
        )
        assert r.status_code == 429
        assert "try again in" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# /auth/me with bearer token
# ---------------------------------------------------------------------------
class TestMe:
    def test_me_with_bearer(self, admin_bearer):
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {admin_bearer}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # response shape can be {user:{...}} or flat - accept both
        user = body.get("user") or body
        assert user.get("email") == ADMIN_EMAIL
        # No _id leakage anywhere in payload
        import json as _json
        assert '"_id"' not in _json.dumps(body)

    def test_me_without_token_unauthorized(self):
        r = requests.get(f"{BASE_URL}/api/auth/me", timeout=15)
        assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Existing endpoints still work
# ---------------------------------------------------------------------------
class TestExisting:
    def test_health(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=15)
        assert r.status_code == 200

    def test_brokers_status_admin(self, admin_bearer):
        r = requests.get(
            f"{BASE_URL}/api/brokers/status",
            headers={"Authorization": f"Bearer {admin_bearer}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("kotak_neo", "dhan", "alice_blue", "webhook_token"):
            assert key in body, f"missing key {key} in /brokers/status response: {body}"


# ---------------------------------------------------------------------------
# Cleanup test users
# ---------------------------------------------------------------------------
class TestZCleanup:
    def test_cleanup(self, db):
        db.users.delete_many({"email": {"$regex": r"^(test_|locktest_|nouser_)", "$options": "i"}})
        db.login_attempts.delete_many({})
