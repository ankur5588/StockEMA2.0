"""Multi-broker (Dhan + Alice Blue + Kotak Neo) integration tests.

Covers iteration_2 features:
- /api/brokers/status returns all 3 broker statuses + webhook_token + webhook_url
- /api/dhan/credentials, /api/dhan/status, /api/dhan/connect, DELETE /api/dhan/credentials
- /api/alice/credentials, /api/alice/status, /api/alice/connect, DELETE /api/alice/credentials
- AlertConfigInput.broker field persistence
- Chartink webhook routes by broker (kotak_neo / dhan / alice_blue)
- /api/positions/all empty when no broker auth
- /api/ema-sl/run 400 'No broker authenticated' when no broker connected
- Existing Kotak endpoints still work
- User-level webhook_token persists across broker changes
"""
import os
import time
import uuid
import pytest
import requests

_RAW_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not _RAW_URL:
    # Try frontend/.env (pytest doesn't load it automatically)
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    _RAW_URL = line.strip().split("=", 1)[1]
                    break
    except Exception:
        pass
assert _RAW_URL, "REACT_APP_BACKEND_URL not set"
BASE_URL = _RAW_URL.rstrip("/")
API = f"{BASE_URL}/api"
TEST_SESSION_TOKEN = "sess_testdash1234"
TEST_USER_ID = "user_testdash1234"


# ---------- /api/brokers/status ----------
class TestBrokersStatus:
    def test_brokers_status_shape_and_webhook(self, auth_client):
        r = auth_client.get(f"{API}/brokers/status")
        assert r.status_code == 200, r.text
        data = r.json()
        # All 3 broker keys present
        for k in ("kotak_neo", "dhan", "alice_blue"):
            assert k in data, f"missing broker key {k}"
            assert "has_credentials" in data[k]
            assert "is_authenticated" in data[k]
            assert isinstance(data[k]["has_credentials"], bool)
            assert isinstance(data[k]["is_authenticated"], bool)
        # Webhook fields
        assert isinstance(data["webhook_token"], str) and len(data["webhook_token"]) > 10
        assert "/api/webhooks/chartink/" in data["webhook_url"]
        assert data["webhook_token"] in data["webhook_url"]
        pytest.shared_webhook_token = data["webhook_token"]


# ---------- DHAN ----------
class TestDhanCredentials:
    def test_dhan_save_credentials(self, auth_client):
        r = auth_client.post(f"{API}/dhan/credentials", json={
            "client_id": "TEST_FAKE_CLIENT_123",
            "access_token": "TEST_fake_access_token_xyz",
        })
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

    def test_dhan_status_after_save(self, auth_client):
        r = auth_client.get(f"{API}/dhan/status")
        assert r.status_code == 200
        data = r.json()
        assert data["has_credentials"] is True
        assert data["is_authenticated"] is False

    def test_dhan_connect_with_fake_creds_returns_400(self, auth_client):
        r = auth_client.post(f"{API}/dhan/connect")
        assert r.status_code == 400, f"got {r.status_code}: {r.text}"
        detail = (r.json().get("detail") or "").lower()
        # Message should clearly mention Dhan/client_id/invalid/auth issue, not generic
        assert any(kw in detail for kw in ("client", "invalid", "dhan", "credential", "auth", "dh-")), \
            f"Dhan error message unclear: {detail}"

    def test_dhan_delete_credentials(self, auth_client):
        r = auth_client.delete(f"{API}/dhan/credentials")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # verify
        r = auth_client.get(f"{API}/dhan/status")
        assert r.status_code == 200
        assert r.json()["has_credentials"] is False

    def test_dhan_connect_without_creds(self, auth_client):
        # No saved credentials should yield 400 with clear message
        r = auth_client.post(f"{API}/dhan/connect")
        assert r.status_code == 400
        assert "save" in r.json().get("detail", "").lower() or "dhan" in r.json().get("detail", "").lower()


# ---------- ALICE BLUE ----------
class TestAliceCredentials:
    def test_alice_save_credentials(self, auth_client):
        r = auth_client.post(f"{API}/alice/credentials", json={
            "user_id": "TEST_AB_USER",
            "api_key": "TEST_fake_alice_api_key",
        })
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

    def test_alice_status_after_save(self, auth_client):
        r = auth_client.get(f"{API}/alice/status")
        assert r.status_code == 200
        data = r.json()
        assert data["has_credentials"] is True
        assert data["is_authenticated"] is False

    def test_alice_connect_with_fake_creds_returns_400(self, auth_client):
        r = auth_client.post(f"{API}/alice/connect")
        assert r.status_code == 400, f"got {r.status_code}: {r.text}"
        detail = (r.json().get("detail") or "").lower()
        # Message should mention API key / alice / invalid / not available
        assert any(kw in detail for kw in ("api key", "alice", "invalid", "credential", "not available", "auth")), \
            f"Alice error message unclear: {detail}"

    def test_alice_delete_credentials(self, auth_client):
        r = auth_client.delete(f"{API}/alice/credentials")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r = auth_client.get(f"{API}/alice/status")
        assert r.status_code == 200
        assert r.json()["has_credentials"] is False


# ---------- ALERTS WITH BROKER FIELD ----------
class TestAlertsBrokerField:
    def test_alert_create_with_dhan_broker(self, auth_client):
        name = f"TEST_alert_dhan_{uuid.uuid4().hex[:6]}"
        payload = {
            "alert_name": name, "transaction_type": "B", "quantity": 1,
            "product": "CNC", "exchange_segment": "nse_cm",
            "enabled": True, "broker": "dhan",
        }
        r = auth_client.post(f"{API}/alerts", json=payload)
        assert r.status_code == 200, r.text
        created = r.json()
        assert created["broker"] == "dhan"
        assert created["alert_name"] == name
        pytest.dhan_alert_id = created["id"]
        pytest.dhan_alert_name = name

        # Verify GET /api/alerts returns broker field
        r = auth_client.get(f"{API}/alerts")
        assert r.status_code == 200
        match = next((a for a in r.json()["alerts"] if a["id"] == created["id"]), None)
        assert match is not None
        assert match["broker"] == "dhan"

    def test_alert_create_with_alice_blue_broker(self, auth_client):
        name = f"TEST_alert_alice_{uuid.uuid4().hex[:6]}"
        r = auth_client.post(f"{API}/alerts", json={
            "alert_name": name, "transaction_type": "B", "quantity": 1,
            "broker": "alice_blue", "enabled": True,
        })
        assert r.status_code == 200
        created = r.json()
        assert created["broker"] == "alice_blue"
        pytest.alice_alert_id = created["id"]
        pytest.alice_alert_name = name

    def test_alert_create_with_kotak_broker(self, auth_client):
        name = f"TEST_alert_kotak_{uuid.uuid4().hex[:6]}"
        r = auth_client.post(f"{API}/alerts", json={
            "alert_name": name, "transaction_type": "B", "quantity": 1,
            "broker": "kotak_neo", "enabled": True,
        })
        assert r.status_code == 200
        assert r.json()["broker"] == "kotak_neo"
        pytest.kotak_alert_id = r.json()["id"]
        pytest.kotak_alert_name = name


# ---------- CHARTINK WEBHOOK ROUTING ----------
class TestWebhookRouting:
    def _token(self, auth_client):
        return auth_client.get(f"{API}/brokers/status").json()["webhook_token"]

    def test_webhook_routes_to_dhan(self, api_client, auth_client):
        token = self._token(auth_client)
        payload = {
            "stocks": "RELIANCE",
            "trigger_prices": "2500",
            "alert_name": pytest.dhan_alert_name,
        }
        r = api_client.post(f"{API}/webhooks/chartink/{token}", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        notes_text = " ".join(data.get("notes", [])).lower()
        assert "dhan" in notes_text, f"expected Dhan in notes: {notes_text}"
        # Since Dhan not authenticated, expect 'not authenticated' in notes
        assert "not authenticated" in notes_text or "skipped" in notes_text, notes_text
        assert data["placed"] is False

    def test_webhook_routes_to_alice_blue(self, api_client, auth_client):
        token = self._token(auth_client)
        payload = {
            "stocks": "INFY",
            "trigger_prices": "1800",
            "alert_name": pytest.alice_alert_name,
        }
        r = api_client.post(f"{API}/webhooks/chartink/{token}", json=payload)
        assert r.status_code == 200
        data = r.json()
        notes_text = " ".join(data.get("notes", [])).lower()
        assert "alice" in notes_text, f"expected Alice in notes: {notes_text}"
        assert "not authenticated" in notes_text or "skipped" in notes_text

    def test_webhook_routes_to_kotak(self, api_client, auth_client):
        token = self._token(auth_client)
        payload = {
            "stocks": "TCS",
            "trigger_prices": "3500",
            "alert_name": pytest.kotak_alert_name,
        }
        r = api_client.post(f"{API}/webhooks/chartink/{token}", json=payload)
        assert r.status_code == 200
        data = r.json()
        notes_text = " ".join(data.get("notes", [])).lower()
        assert "kotak" in notes_text, f"expected Kotak in notes: {notes_text}"


# ---------- POSITIONS / EMA-SL ----------
class TestPositionsAndEmaSl:
    def test_positions_all_empty_no_broker_auth(self, auth_client):
        r = auth_client.get(f"{API}/positions/all")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["positions"] == []
        # No errors when no broker is authenticated
        assert data.get("errors", {}) == {}

    def test_ema_sl_run_no_broker(self, auth_client):
        r = auth_client.post(f"{API}/ema-sl/run")
        assert r.status_code == 400, f"got {r.status_code}: {r.text}"
        assert "no broker" in r.json().get("detail", "").lower()


# ---------- KOTAK STILL WORKS ----------
class TestKotakStillWorks:
    def test_kotak_credentials_save(self, auth_client):
        r = auth_client.post(f"{API}/kotak/credentials", json={
            "mobile": "+919999999999",
            "password": "dummy_password",
            "mpin": "123456",
            "consumer_key": "fake_consumer_key",
            "consumer_secret": "fake_consumer_secret",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert isinstance(data["webhook_token"], str)

    def test_kotak_status(self, auth_client):
        r = auth_client.get(f"{API}/kotak/status")
        assert r.status_code == 200
        data = r.json()
        assert data["has_credentials"] is True
        assert data["is_authenticated"] is False
        assert "/api/webhooks/chartink/" in data["webhook_url"]

    def test_kotak_login_invalid_creds_400(self, auth_client):
        r = auth_client.post(f"{API}/kotak/login")
        assert r.status_code == 400, r.text


# ---------- USER-LEVEL WEBHOOK TOKEN PERSISTENCE ----------
class TestWebhookTokenPersistence:
    def test_token_persists_across_broker_changes(self, auth_client):
        t1 = auth_client.get(f"{API}/brokers/status").json()["webhook_token"]
        # Save dhan credentials
        auth_client.post(f"{API}/dhan/credentials", json={
            "client_id": "TEST_X", "access_token": "TEST_TOK"
        })
        t2 = auth_client.get(f"{API}/brokers/status").json()["webhook_token"]
        # Save alice credentials
        auth_client.post(f"{API}/alice/credentials", json={
            "user_id": "TEST_AB", "api_key": "TEST_AKEY"
        })
        t3 = auth_client.get(f"{API}/brokers/status").json()["webhook_token"]
        # Delete one
        auth_client.delete(f"{API}/dhan/credentials")
        t4 = auth_client.get(f"{API}/brokers/status").json()["webhook_token"]
        assert t1 == t2 == t3 == t4, f"Token changed: {t1} {t2} {t3} {t4}"


# ---------- CLEANUP ----------
class TestZCleanup:
    def test_cleanup_alerts(self, auth_client):
        for aid_attr in ("dhan_alert_id", "alice_alert_id", "kotak_alert_id"):
            aid = getattr(pytest, aid_attr, None)
            if aid:
                auth_client.delete(f"{API}/alerts/{aid}")

    def test_cleanup_kotak(self, auth_client):
        auth_client.delete(f"{API}/kotak/credentials")

    def test_cleanup_dhan(self, auth_client):
        auth_client.delete(f"{API}/dhan/credentials")

    def test_cleanup_alice(self, auth_client):
        auth_client.delete(f"{API}/alice/credentials")
