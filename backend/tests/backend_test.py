"""End-to-end backend test suite for ChartinkTrade API.

Covers: health, auth, kotak credentials & status, kotak login/positions error handling,
ema-sl, alerts CRUD, chartink webhook, logs.
"""
import os
import time
import uuid
import pytest
import requests

import os as _os
BASE_URL = _os.environ.get("REACT_APP_BACKEND_URL", "https://chartink-auto-order.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
TEST_SESSION_TOKEN = "sess_testdash1234"
TEST_USER_ID = "user_testdash1234"


# ---------- HEALTH ----------
class TestHealth:
    def test_health(self, api_client):
        r = api_client.get(f"{API}/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert "ts" in data

    def test_root(self, api_client):
        r = api_client.get(f"{API}/")
        assert r.status_code == 200
        assert r.json().get("status") == "ok"


# ---------- AUTH ----------
class TestAuth:
    def test_auth_me_no_token(self, api_client):
        r = api_client.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_auth_me_invalid_token(self, api_client):
        r = api_client.get(f"{API}/auth/me", headers={"Authorization": "Bearer invalid_token_xyz"})
        assert r.status_code == 401

    def test_auth_me_valid(self, auth_client):
        r = auth_client.get(f"{API}/auth/me")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user_id"] == TEST_USER_ID
        assert data["email"] == "trader.demo@example.com"


# ---------- KOTAK CREDENTIALS ----------
class TestKotakCredentials:
    def test_save_credentials(self, auth_client):
        payload = {
            "mobile": "+919999999999",
            "password": "dummy_password",
            "mpin": "123456",
            "consumer_key": "fake_consumer_key",
            "consumer_secret": "fake_consumer_secret",
        }
        r = auth_client.post(f"{API}/kotak/credentials", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert isinstance(data["webhook_token"], str)
        assert len(data["webhook_token"]) > 10
        # Stash for later tests
        pytest.webhook_token = data["webhook_token"]

    def test_status_after_save(self, auth_client):
        r = auth_client.get(f"{API}/kotak/status")
        assert r.status_code == 200
        data = r.json()
        assert data["has_credentials"] is True
        assert data["is_authenticated"] is False
        assert data["webhook_token"]
        assert "/api/webhooks/chartink/" in data["webhook_url"]
        assert data["webhook_token"] in data["webhook_url"]

    def test_kotak_login_invalid_creds(self, auth_client):
        # Dummy creds - should fail gracefully with 400, not 500
        r = auth_client.post(f"{API}/kotak/login")
        assert r.status_code == 400, f"Expected 400 but got {r.status_code}: {r.text}"
        assert "detail" in r.json()

    def test_kotak_positions_not_auth(self, auth_client):
        r = auth_client.get(f"{API}/kotak/positions")
        assert r.status_code == 400
        assert "Not authenticated with Kotak Neo" in r.json().get("detail", "")

    def test_ema_sl_run_not_auth(self, auth_client):
        r = auth_client.post(f"{API}/ema-sl/run")
        assert r.status_code == 400
        assert "no broker authenticated" in r.json().get("detail", "").lower()


# ---------- WEBHOOK ----------
class TestChartinkWebhook:
    def test_webhook_unknown_token(self, api_client):
        r = api_client.post(f"{API}/webhooks/chartink/bogus_token_xyz", json={"stocks": "RELIANCE"})
        assert r.status_code == 404

    def test_webhook_json_payload(self, api_client, auth_client):
        # Ensure credentials exist to get webhook token
        s = auth_client.get(f"{API}/kotak/status").json()
        token = s["webhook_token"]
        payload = {
            "stocks": "RELIANCE,INFY",
            "trigger_prices": "2500,1800",
            "alert_name": "Morning Breakouts",
            "scan_name": "morning-scan",
        }
        r = api_client.post(f"{API}/webhooks/chartink/{token}", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["placed"] is False  # Kotak not authenticated
        assert data["received"] is True

    def test_webhook_logs_contains_entry(self, auth_client):
        # small wait for insert
        time.sleep(0.3)
        r = auth_client.get(f"{API}/webhooks/logs")
        assert r.status_code == 200
        logs = r.json()["logs"]
        assert any("RELIANCE" in l.get("stocks", []) for l in logs)
        assert any(l.get("alert_name") == "Morning Breakouts" for l in logs)

    def test_webhook_form_urlencoded(self, api_client, auth_client):
        s = auth_client.get(f"{API}/kotak/status").json()
        token = s["webhook_token"]
        # form-urlencoded
        r = requests.post(
            f"{API}/webhooks/chartink/{token}",
            data={"stocks": "TCS", "trigger_prices": "3500", "alert_name": "form-test"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True


# ---------- ALERTS CRUD ----------
class TestAlerts:
    def test_alerts_full_crud(self, auth_client):
        # List initially
        r = auth_client.get(f"{API}/alerts")
        assert r.status_code == 200

        # Create
        payload = {
            "alert_name": f"TEST_alert_{uuid.uuid4().hex[:6]}",
            "transaction_type": "B",
            "quantity": 1,
            "product": "CNC",
            "exchange_segment": "nse_cm",
            "enabled": True,
        }
        r = auth_client.post(f"{API}/alerts", json=payload)
        assert r.status_code == 200, r.text
        created = r.json()
        assert created["alert_name"] == payload["alert_name"]
        alert_id = created["id"]

        # List contains new
        r = auth_client.get(f"{API}/alerts")
        assert r.status_code == 200
        ids = [a["id"] for a in r.json()["alerts"]]
        assert alert_id in ids

        # Delete
        r = auth_client.delete(f"{API}/alerts/{alert_id}")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Verify removed
        r = auth_client.get(f"{API}/alerts")
        ids = [a["id"] for a in r.json()["alerts"]]
        assert alert_id not in ids


# ---------- LOGS ----------
class TestLogs:
    def test_trade_logs(self, auth_client):
        r = auth_client.get(f"{API}/trades/logs")
        assert r.status_code == 200
        assert isinstance(r.json()["logs"], list)

    def test_ema_sl_logs(self, auth_client):
        r = auth_client.get(f"{API}/ema-sl/logs")
        assert r.status_code == 200
        assert isinstance(r.json()["logs"], list)


# ---------- CLEANUP ----------
class TestZCleanup:
    def test_delete_kotak_credentials(self, auth_client):
        r = auth_client.delete(f"{API}/kotak/credentials")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Verify cleared
        r = auth_client.get(f"{API}/kotak/status")
        assert r.status_code == 200
        data = r.json()
        assert data["has_credentials"] is False
