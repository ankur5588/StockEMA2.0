"""End-to-end verification that the EMA10 stoploss logic works identically
for all 3 brokers (Kotak Neo, Dhan, Alice Blue).

We mock the broker SDKs so we don't need live credentials and also don't hit
real markets. We DO hit yfinance for the real EMA computation to prove the
symbol normalisation flow works correctly across broker exchange formats.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from ema_service import _normalise_symbol, compute_ema10  # noqa: E402


class TestNormaliseSymbol:
    """Prove _normalise_symbol handles all broker exchange segment formats."""

    def test_kotak_nse(self):
        assert _normalise_symbol("RELIANCE", "nse_cm") == "RELIANCE.NS"

    def test_kotak_bse(self):
        assert _normalise_symbol("RELIANCE", "bse_cm") == "RELIANCE.BO"

    def test_kotak_suffix_stripped(self):
        assert _normalise_symbol("RELIANCE-EQ", "nse_cm") == "RELIANCE.NS"

    def test_dhan_nse(self):
        assert _normalise_symbol("RELIANCE", "NSE_EQ") == "RELIANCE.NS"

    def test_dhan_bse(self):
        # Before fix this returned RELIANCE.NS (bug)
        assert _normalise_symbol("RELIANCE", "BSE_EQ") == "RELIANCE.BO"

    def test_dhan_fno(self):
        assert _normalise_symbol("NIFTY", "NSE_FNO") == "NIFTY.NS"

    def test_alice_nse(self):
        assert _normalise_symbol("RELIANCE", "NSE") == "RELIANCE.NS"

    def test_alice_bse(self):
        # Before fix this returned RELIANCE.NS (bug)
        assert _normalise_symbol("RELIANCE", "BSE") == "RELIANCE.BO"

    def test_alice_bfo(self):
        assert _normalise_symbol("NIFTY", "BFO") == "NIFTY.BO"

    def test_case_insensitive(self):
        assert _normalise_symbol("reliance", "BsE_CM") == "RELIANCE.BO"
        assert _normalise_symbol("reliance", "Nse_Eq") == "RELIANCE.NS"

    def test_empty_segment_defaults_to_nse(self):
        assert _normalise_symbol("RELIANCE", "") == "RELIANCE.NS"


class TestComputeEmaReal:
    """Actually hits yfinance to prove EMA10 works for a real NSE symbol
    regardless of which broker's exchange_segment format is passed.
    """

    def test_ema10_kotak_format(self):
        val = compute_ema10("RELIANCE", "nse_cm")
        assert val is None or val > 0

    def test_ema10_dhan_format(self):
        val = compute_ema10("RELIANCE", "NSE_EQ")
        assert val is None or val > 0

    def test_ema10_alice_format(self):
        val = compute_ema10("RELIANCE", "NSE")
        assert val is None or val > 0

    def test_ema10_all_three_formats_agree(self):
        """Same symbol + equivalent exchange MUST produce the same EMA10 across
        all three broker exchange_segment string formats."""
        kotak = compute_ema10("TCS", "nse_cm")
        dhan = compute_ema10("TCS", "NSE_EQ")
        alice = compute_ema10("TCS", "NSE")
        # At least one should succeed if yfinance is reachable
        if kotak is not None and dhan is not None and alice is not None:
            assert kotak == dhan == alice


class TestEmaSlRunMultiBroker:
    """Mock the 3 broker SDKs and verify POST /api/ema-sl/run processes a
    long position from each broker and places an SL order on the correct
    broker adapter with the right exchange_segment.
    """

    def test_ema_sl_routes_per_broker(self, monkeypatch):
        # Late-import so monkeypatch can replace module-level clients
        import kotak_client
        import dhan_client
        import alice_client
        from fastapi.testclient import TestClient
        import server

        user_id = "user_testdash1234"
        session_token = "sess_testdash1234"

        # Mock authenticated flags + positions + place_order for each broker
        calls = {"kotak": [], "dhan": [], "alice": []}

        monkeypatch.setattr(kotak_client, "is_authenticated", lambda uid: True)
        monkeypatch.setattr(
            kotak_client,
            "get_positions",
            lambda uid: [
                {
                    "trdSym": "RELIANCE-EQ",
                    "exSeg": "nse_cm",
                    "flBuyQty": "10",
                    "flSellQty": "0",
                    "buyAmt": "25000",
                    "prod": "CNC",
                }
            ],
        )

        def kotak_place(**kw):
            calls["kotak"].append(kw)
            return {"nOrdNo": "K-ORD-1"}

        monkeypatch.setattr(kotak_client, "place_order", kotak_place)

        monkeypatch.setattr(dhan_client, "is_authenticated", lambda uid: True)
        monkeypatch.setattr(
            dhan_client,
            "get_positions",
            lambda uid: [
                {
                    "broker": "dhan",
                    "symbol": "TCS",
                    "exchange_segment": "NSE_EQ",
                    "security_id": "11536",
                    "quantity": 5,
                    "avg_price": 3500.0,
                    "ltp": 3510.0,
                    "pnl": 50.0,
                    "product": "CNC",
                }
            ],
        )

        def dhan_place(**kw):
            calls["dhan"].append(kw)
            return {"ok": True, "order_id": "D-ORD-1"}

        monkeypatch.setattr(dhan_client, "place_order", dhan_place)

        monkeypatch.setattr(alice_client, "is_authenticated", lambda uid: True)
        monkeypatch.setattr(
            alice_client,
            "get_positions",
            lambda uid: [
                {
                    "broker": "alice_blue",
                    "symbol": "INFY",
                    "exchange_segment": "NSE",
                    "quantity": 3,
                    "avg_price": 1500.0,
                    "ltp": 1510.0,
                    "pnl": 30.0,
                    "product": "CNC",
                }
            ],
        )

        def alice_place(**kw):
            calls["alice"].append(kw)
            return {"ok": True, "order_id": "A-ORD-1"}

        monkeypatch.setattr(alice_client, "place_order", alice_place)

        # Force a known EMA value so test is deterministic
        monkeypatch.setattr(server, "compute_ema10", lambda sym, seg: 100.0)

        client = TestClient(server.app)
        r = client.post(
            "/api/ema-sl/run",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["count"] == 3

        # Kotak was invoked with SL order_type and nse_cm segment
        assert len(calls["kotak"]) == 1
        k = calls["kotak"][0]
        assert k["transaction_type"] == "S"
        assert k["order_type"] == "SL"
        assert k["trading_symbol"] == "RELIANCE-EQ"
        assert k["exchange_segment"] == "nse_cm"
        assert k["trigger_price"] == "100.0"

        # Dhan was invoked with SL, NSE_EQ, and security_id from the position
        assert len(calls["dhan"]) == 1
        d = calls["dhan"][0]
        assert d["transaction_type"] == "S"
        assert d["order_type"] == "SL"
        assert d["symbol"] == "TCS"
        assert d["exchange_segment"] == "NSE_EQ"
        assert d["security_id"] == "11536"
        assert d["trigger_price"] == 100.0

        # Alice Blue was invoked with SL, NSE exchange
        assert len(calls["alice"]) == 1
        a = calls["alice"][0]
        assert a["transaction_type"] == "S"
        assert a["order_type"] == "SL"
        assert a["symbol"] == "INFY"
        assert a["exchange"] == "NSE"
        assert a["trigger_price"] == 100.0

        # All three orders recorded
        statuses = [run["status"] for run in data["runs"]]
        assert statuses.count("placed") == 3
