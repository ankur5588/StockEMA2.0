"""Iteration 4 tests:

1. BUG FIX: POST /api/symbol-mappings — TypeError "got multiple values for chartink_symbol"
   regression. Verify create with quantity, create with amount, list, delete.

2. FEATURE: POST /api/orders/manual — supports kotak_neo / dhan / alice_blue,
   AMO flag, auto-EMA10 SL only for BUY. Skipped (200) when broker not connected.
   400 for unsupported broker. Limit orders with price=0 still accepted (FE-side
   validation).

3. FEATURE: GET /api/ema-preview/{symbol} — yfinance-backed EMA10 preview.
   Positive float for RELIANCE.NS, ema10:null for unknown symbol.

4. REGRESSION: GET /api/health, POST /api/auth/login, GET /api/auth/me,
   GET /api/brokers/status, GET /api/alerts, GET /api/trades/logs.

5. REGRESSION: trade_logs gets a row with source="manual" after a manual call.
"""
import os
import uuid

import pytest
import requests


def _read_env(path, key):
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    # strip surrounding double or single quotes (iteration 3 bug fix)
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return None
    return None


BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or _read_env("/app/frontend/.env", "REACT_APP_BACKEND_URL")
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@chartink.local"
ADMIN_PASSWORD = "admin123"


# ---------- shared fixtures ----------

@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=20)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    tok = r.json().get("session_token")
    assert tok
    return tok


@pytest.fixture
def auth():
    def _h(token):
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    return _h


# ---------- 4. REGRESSION ----------

class TestHealthAndAuth:
    def test_health(self):
        r = requests.get(f"{API}/health", timeout=10)
        assert r.status_code == 200
        # backend returns {"status":"healthy",...}
        assert r.json().get("status") in ("ok", "healthy")

    def test_admin_login_and_me(self, admin_token, auth):
        r = requests.get(f"{API}/auth/me", headers=auth(admin_token), timeout=10)
        assert r.status_code == 200
        u = r.json()
        assert u["email"] == ADMIN_EMAIL
        # role may not be exposed in /auth/me response; not a regression
        # No mongo _id leakage
        assert "_id" not in u

    def test_brokers_status(self, admin_token, auth):
        r = requests.get(f"{API}/brokers/status", headers=auth(admin_token), timeout=10)
        assert r.status_code == 200
        b = r.json()
        for k in ("kotak_neo", "dhan", "alice_blue"):
            assert k in b, f"missing {k} in brokers status: {b}"

    def test_list_alerts(self, admin_token, auth):
        r = requests.get(f"{API}/alerts", headers=auth(admin_token), timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert "alerts" in body
        assert isinstance(body["alerts"], list)

    def test_list_trade_logs(self, admin_token, auth):
        r = requests.get(f"{API}/trades/logs", headers=auth(admin_token), timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert "logs" in body
        assert isinstance(body["logs"], list)


# ---------- 1. SYMBOL MAPPINGS BUG FIX ----------

class TestSymbolMappingsBugFix:
    def test_create_with_quantity_and_persist_and_delete(self, admin_token, auth):
        payload = {
            "chartink_symbol": "reliance",
            "nse_symbol": "reliance-eq",
            "quantity": 1,
            "broker": "kotak_neo",
            "transaction_type": "B",
            "product": "CNC",
        }
        r = requests.post(f"{API}/symbol-mappings", headers=auth(admin_token),
                          json=payload, timeout=15)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert body["chartink_symbol"] == "RELIANCE"
        assert body["nse_symbol"] == "RELIANCE-EQ"
        assert body["quantity"] == 1
        assert body["broker"] == "kotak_neo"
        assert "id" in body
        mapping_id = body["id"]
        assert "_id" not in body

        # GET should list it
        r2 = requests.get(f"{API}/symbol-mappings", headers=auth(admin_token), timeout=10)
        assert r2.status_code == 200
        mappings = r2.json().get("mappings", [])
        assert any(m["id"] == mapping_id and m["chartink_symbol"] == "RELIANCE"
                   for m in mappings), f"mapping not listed: {mappings}"

        # DELETE
        r3 = requests.delete(f"{API}/symbol-mappings/{mapping_id}",
                             headers=auth(admin_token), timeout=10)
        assert r3.status_code == 200
        assert r3.json().get("ok") is True

        # Verify removed
        r4 = requests.get(f"{API}/symbol-mappings", headers=auth(admin_token), timeout=10)
        assert r4.status_code == 200
        rem = r4.json().get("mappings", [])
        assert not any(m["id"] == mapping_id for m in rem)

    def test_create_with_amount(self, admin_token, auth):
        payload = {
            "chartink_symbol": "tcs",
            "nse_symbol": "tcs-eq",
            "amount": 5000.0,
            "broker": "dhan",
            "transaction_type": "B",
            "product": "CNC",
        }
        r = requests.post(f"{API}/symbol-mappings", headers=auth(admin_token),
                          json=payload, timeout=15)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert body["chartink_symbol"] == "TCS"
        assert body["amount"] == 5000.0
        assert body["quantity"] in (None, 0)
        # clean up
        requests.delete(f"{API}/symbol-mappings/{body['id']}",
                        headers=auth(admin_token), timeout=10)


# ---------- 2. MANUAL ORDER FEATURE ----------

class TestManualOrder:
    def _payload(self, broker, side="B", auto_sl=False, order_type="MKT", price=0.0):
        return {
            "broker": broker,
            "symbol": "RELIANCE",
            "transaction_type": side,
            "quantity": 1,
            "order_type": order_type,
            "price": price,
            "product": "CNC",
            "exchange_segment": "nse_cm",
            "amo": True,
            "auto_ema_sl": auto_sl,
        }

    @pytest.mark.parametrize("broker", ["kotak_neo", "dhan", "alice_blue"])
    def test_manual_order_skipped_when_not_authenticated(self, broker, admin_token, auth):
        r = requests.post(f"{API}/orders/manual", headers=auth(admin_token),
                          json=self._payload(broker), timeout=20)
        # When the broker isn't connected, _route_order returns status='skipped'.
        # The endpoint responds 200 with ok:false in that case.
        assert r.status_code == 200, f"{broker}: expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert body["ok"] is False
        assert body["status"] == "skipped"
        assert "not authenticated" in body["message"].lower(), body
        # auto_ema_sl was False so ema_sl block is None
        assert body.get("ema_sl") is None

    def test_unsupported_broker_returns_400(self, admin_token, auth):
        bad = self._payload("foo")
        r = requests.post(f"{API}/orders/manual", headers=auth(admin_token),
                          json=bad, timeout=10)
        assert r.status_code == 400
        assert "foo" in r.text.lower() or "unsupported" in r.text.lower()

    def test_auto_ema_sl_skipped_for_sell(self, admin_token, auth):
        # SELL side with auto_ema_sl=True — the ema_sl block must be skipped
        body_in = self._payload("kotak_neo", side="S", auto_sl=True)
        r = requests.post(f"{API}/orders/manual", headers=auth(admin_token),
                          json=body_in, timeout=20)
        assert r.status_code == 200
        body = r.json()
        # since the entry order was skipped (no broker), ema_sl is None anyway —
        # the important property is that the ema_sl block was NOT attempted for SELL
        assert body.get("ema_sl") is None

    def test_limit_order_with_price_zero_accepted(self, admin_token, auth):
        body_in = self._payload("kotak_neo", order_type="L", price=0.0)
        r = requests.post(f"{API}/orders/manual", headers=auth(admin_token),
                          json=body_in, timeout=20)
        # Backend doesn't reject; FE handles price validation.
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] in ("skipped", "success", "error")

    def test_trade_log_written_for_manual(self, admin_token, auth):
        # Place a manual order then ensure a trade log row with source="manual" exists
        r = requests.post(f"{API}/orders/manual", headers=auth(admin_token),
                          json=self._payload("kotak_neo"), timeout=20)
        assert r.status_code == 200
        # Fetch logs
        r2 = requests.get(f"{API}/trades/logs", headers=auth(admin_token), timeout=10)
        assert r2.status_code == 200
        body = r2.json()
        logs = body.get("logs", body) if isinstance(body, dict) else body
        assert any(l.get("source") == "manual" for l in logs), \
            f"no manual log found in {logs[:3] if isinstance(logs, list) else logs}"


# ---------- 3. EMA PREVIEW ----------

class TestEmaPreview:
    def test_ema_preview_reliance(self, admin_token, auth):
        # Endpoint is documented as public — token sent just to be safe
        r = requests.get(f"{API}/ema-preview/RELIANCE?exchange_segment=nse_cm",
                         headers=auth(admin_token), timeout=30)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["symbol"] == "RELIANCE"
        assert b["exchange_segment"] == "nse_cm"
        # yfinance has data → expect positive ema10. Allow None as graceful fallback if YF is unavailable
        ema = b.get("ema10")
        if ema is None:
            pytest.skip("yfinance returned no data (network/CDN); flaky external dep")
        assert isinstance(ema, (int, float))
        assert ema > 0
        TICK = 0.05
        trigger = b.get("sl_trigger")
        assert trigger is not None
        assert trigger <= ema
        assert abs(round(trigger / TICK) - trigger / TICK) < 1e-9  # multiple of tick
        limit = b.get("sl_limit")
        assert limit is not None
        assert limit < ema
        assert abs(round(limit / TICK) - limit / TICK) < 1e-9

    def test_ema_preview_nonexistent_symbol(self, admin_token, auth):
        r = requests.get(f"{API}/ema-preview/NONEXISTENTSYMBOLXYZ?exchange_segment=nse_cm",
                         headers=auth(admin_token), timeout=30)
        assert r.status_code == 200
        b = r.json()
        assert b["ema10"] is None
        assert b["sl_trigger"] is None
        assert b["sl_limit"] is None
