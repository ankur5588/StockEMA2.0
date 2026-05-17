"""Iteration 5: INDmoney endpoints + CSV template + regressions.

Covers:
  - GET /api/brokers/status now returns an 'indmoney' block
  - POST /api/indmoney/credentials (idempotent upsert)
  - GET  /api/indmoney/status reflects has_credentials=true
  - DELETE /api/indmoney/credentials clears them
  - POST /api/indmoney/connect → 400 when no creds + 400 with IndMoneyError when invalid token
  - POST /api/orders/manual with broker='indmoney' → 200 + skipped
  - POST /api/symbol-mappings/upload accepts 'indmoney'
  - POST /api/orders/manual with broker='foo' still 400
  - Regression endpoints still up
"""

import os
import uuid

import pytest
import requests
from pymongo import MongoClient


def _read_env(path, key):
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip(chr(34)).strip(chr(39))
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
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module", autouse=True)
def _clear_lockout(db):
    db.login_attempts.delete_many({})
    yield


@pytest.fixture(scope="module")
def admin_token(db):
    db.login_attempts.delete_many({})
    r = requests.post(
        f"{API}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def H(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# --- /api/brokers/status now contains indmoney --------------------------------
class TestBrokersStatus:
    def test_brokers_status_includes_indmoney(self, H):
        r = requests.get(f"{API}/brokers/status", headers=H, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "indmoney" in body, f"missing indmoney in {body.keys()}"
        ind = body["indmoney"]
        for k in ("has_credentials", "is_authenticated", "last_login_at"):
            assert k in ind, f"missing {k} in indmoney block: {ind}"
        assert isinstance(ind["has_credentials"], bool)
        assert isinstance(ind["is_authenticated"], bool)

    def test_brokers_status_includes_existing_brokers(self, H):
        r = requests.get(f"{API}/brokers/status", headers=H, timeout=15)
        body = r.json()
        for k in ("kotak_neo", "dhan", "alice_blue", "webhook_token"):
            assert k in body, f"missing legacy broker key {k}"


# --- INDmoney credentials lifecycle ------------------------------------------
class TestIndMoneyCredentials:
    def test_initial_status_no_creds(self, H, db):
        # Make sure we start clean
        requests.delete(f"{API}/indmoney/credentials", headers=H, timeout=15)
        r = requests.get(f"{API}/indmoney/status", headers=H, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["has_credentials"] is False
        assert body["is_authenticated"] is False

    def test_connect_without_creds_returns_400(self, H):
        # Ensure no creds
        requests.delete(f"{API}/indmoney/credentials", headers=H, timeout=15)
        r = requests.post(f"{API}/indmoney/connect", headers=H, timeout=15)
        assert r.status_code == 400, r.text
        assert "save indmoney credentials first" in r.json()["detail"].lower()

    def test_save_credentials_idempotent(self, H):
        # First save
        r1 = requests.post(
            f"{API}/indmoney/credentials",
            headers=H,
            json={"access_token": "stub_token_iteration5_aaa"},
            timeout=15,
        )
        assert r1.status_code == 200, r1.text
        assert r1.json()["ok"] is True

        # Second save (upsert) -- same user, must still 200
        r2 = requests.post(
            f"{API}/indmoney/credentials",
            headers=H,
            json={"access_token": "stub_token_iteration5_bbb"},
            timeout=15,
        )
        assert r2.status_code == 200, r2.text

        # Now GET reflects has_credentials=true
        s = requests.get(f"{API}/indmoney/status", headers=H, timeout=15)
        assert s.status_code == 200
        body = s.json()
        assert body["has_credentials"] is True
        # Session not yet established
        assert body["is_authenticated"] is False

    def test_brokers_status_reflects_saved_creds(self, H):
        r = requests.get(f"{API}/brokers/status", headers=H, timeout=15)
        body = r.json()
        assert body["indmoney"]["has_credentials"] is True

    def test_connect_with_invalid_token_returns_400(self, H):
        # We've saved a stub token; INDmoney upstream cannot be reached → IndMoneyError → 400
        r = requests.post(f"{API}/indmoney/connect", headers=H, timeout=15)
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert isinstance(detail, str) and len(detail) > 0
        # Must NOT be the "save creds first" branch
        assert "save indmoney credentials first" not in detail.lower()

    def test_delete_credentials(self, H):
        r = requests.delete(f"{API}/indmoney/credentials", headers=H, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

        # Verify
        s = requests.get(f"{API}/indmoney/status", headers=H, timeout=15)
        body = s.json()
        assert body["has_credentials"] is False
        assert body["is_authenticated"] is False


# --- Manual order routing for indmoney ---------------------------------------
class TestManualOrderIndmoney:
    def test_manual_order_indmoney_unauth_returns_skipped(self, H):
        # Make sure no creds + not authenticated
        requests.delete(f"{API}/indmoney/credentials", headers=H, timeout=15)
        r = requests.post(
            f"{API}/orders/manual",
            headers=H,
            json={
                "broker": "indmoney",
                "symbol": "RELIANCE",
                "quantity": 1,
                "transaction_type": "B",
                "order_type": "MKT",
                "product": "CNC",
            },
            timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("status") == "skipped", body
        msg = (body.get("message") or "").lower()
        assert "indmoney" in msg and "not authenticated" in msg, body

    def test_manual_order_unsupported_broker_400(self, H):
        r = requests.post(
            f"{API}/orders/manual",
            headers=H,
            json={
                "broker": "foo",
                "symbol": "RELIANCE",
                "quantity": 1,
                "transaction_type": "B",
                "order_type": "MKT",
                "product": "CNC",
            },
            timeout=15,
        )
        assert r.status_code == 400, r.text


# --- Symbol mapping CSV upload accepts indmoney -------------------------------
class TestSymbolMappingsCSV:
    CSV = (
        "chartink_symbol,nse_symbol,quantity,amount,broker,transaction_type,product\n"
        "HDFC,HDFCBANK,,10000,indmoney,B,CNC\n"
    )

    def test_csv_upload_indmoney_inserted(self, H, admin_token, db):
        # Endpoint reads request.body() directly — post raw CSV text
        headers = {
            "Authorization": f"Bearer {admin_token}",
            "Content-Type": "text/csv",
        }
        r = requests.post(
            f"{API}/symbol-mappings/upload",
            headers=headers,
            data=self.CSV.encode("utf-8"),
            timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Body should contain inserted/created/count >0 — be flexible on field name
        inserted = body.get("inserted") or body.get("created") or body.get("count") or 0
        skipped = body.get("skipped") or body.get("errors") or []
        # the indmoney row must have been inserted (not in skipped/errors)
        if isinstance(skipped, list):
            skip_text = " ".join(str(s).lower() for s in skipped)
            assert "invalid broker" not in skip_text, body

        # Verify row in DB
        doc = db.symbol_mappings.find_one({"chartink_symbol": "HDFC", "broker": "indmoney"})
        assert doc is not None, "indmoney mapping was not persisted"

        # cleanup
        db.symbol_mappings.delete_many({"chartink_symbol": "HDFC", "broker": "indmoney"})


# --- Regression: ema-preview --------------------------------------------------
class TestRegression:
    def test_ema_preview_reliance(self):
        # No auth required for this read endpoint
        r = requests.get(f"{API}/ema-preview/RELIANCE", timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "ema10" in body
        assert body["ema10"] is not None and float(body["ema10"]) > 0

    def test_auth_me_with_bearer(self, admin_token):
        r = requests.get(
            f"{API}/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert r.status_code == 200
        user = r.json().get("user") or r.json()
        assert user.get("email") == ADMIN_EMAIL

    def test_manual_order_kotak_unauth(self, H):
        r = requests.post(
            f"{API}/orders/manual",
            headers=H,
            json={
                "broker": "kotak_neo",
                "symbol": "RELIANCE",
                "quantity": 1,
                "transaction_type": "B",
                "order_type": "MKT",
                "product": "CNC",
            },
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("status") == "skipped"

    def test_symbol_mappings_post_still_works(self, H, db):
        unique = f"TEST_IT5_{uuid.uuid4().hex[:6]}"
        r = requests.post(
            f"{API}/symbol-mappings",
            headers=H,
            json={
                "chartink_symbol": unique,
                "nse_symbol": "RELIANCE",
                "quantity": 1,
                "broker": "indmoney",
                "transaction_type": "B",
                "product": "CNC",
            },
            timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        # cleanup
        db.symbol_mappings.delete_many({"chartink_symbol": unique})
