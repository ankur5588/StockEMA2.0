"""Offline tests for the Nifty 20/50-day portfolio kill switch and buy blocking."""
import asyncio
import os
import sys
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "unit_test_db")
os.environ.setdefault("JWT_SECRET", "unit-test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

mongomock_motor = pytest.importorskip("mongomock_motor")

import server  # noqa: E402
import dhan_client  # noqa: E402
import regime_service as regime  # noqa: E402
from stoploss_service import IST  # noqa: E402
from models import User  # noqa: E402

UID = "user_r1"
USER = User(user_id=UID, email="a@b.c", name="T", created_at=datetime.now(timezone.utc))


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def ist(h, m, day=18):          # Wed 2026-11-18
    return datetime(2026, 11, day, h, m, tzinfo=IST).astimezone(timezone.utc)


def sig(signal):
    return {"signal": signal, "sma20": 100.0 if signal == "positive" else 90.0,
            "sma50": 95.0, "last_close": 99.0, "as_of": "2026-11-17"}


@pytest.fixture
def env(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["t"]
    monkeypatch.setattr(server, "db", db)
    state = {"signal": "positive", "sold": [], "cancelled": False}

    monkeypatch.setattr(regime, "current_regime", lambda now=None: sig(state["signal"]) if state["signal"] else None)
    monkeypatch.setattr(server, "_ensure_dhan", lambda uid: _none())
    monkeypatch.setattr(dhan_client, "is_authenticated", lambda u: True)

    def cancel(u):
        state["cancelled"] = True
        return ["S1", "S2"]
    monkeypatch.setattr(dhan_client, "cancel_open_sl_orders", cancel)
    monkeypatch.setattr(dhan_client, "get_positions", lambda u: [
        {"broker": "dhan", "symbol": "TCS", "exchange_segment": "NSE_EQ", "quantity": 10, "product": "CNC"},
        {"broker": "dhan", "symbol": "INFY", "exchange_segment": "NSE_EQ", "quantity": 5, "product": "CNC"},
        {"broker": "dhan", "symbol": "NIFTY24DEC", "exchange_segment": "NSE_FNO", "quantity": 50, "product": "MARGIN"},
        {"broker": "dhan", "symbol": "SHORT", "exchange_segment": "NSE_EQ", "quantity": -3, "product": "MARGIN"},
    ])
    for m in (server.alice_client, server.indmoney_client):
        monkeypatch.setattr(m, "is_authenticated", lambda u: False)

    def fake_route(user_id, broker, symbol, txn, qty, product, seg, **kw):
        state["sold"].append((symbol, qty, txn, kw.get("order_type", "MKT")))
        return ("success", "OID", "ok")
    monkeypatch.setattr(server, "_route_order", fake_route)
    return db, state


async def _none():
    return None


def enable(mode="alert", block=True, confirm=True):
    from server import RegimeSettingsInput
    return run(server.regime_set_settings(
        RegimeSettingsInput(enabled=True, mode=mode, block_buys=block, confirm_live=confirm), USER))


def settings(db):
    return run(db.regime_settings.find_one({"user_id": UID}))


# ---- pure signal -----------------------------------------------------------

def test_signal_positive_in_uptrend():
    closes = list(range(100, 160))
    assert regime.regime_from_closes(closes)["signal"] == "positive"


def test_signal_negative_after_fall():
    closes = list(range(100, 160)) + list(range(159, 99, -2))
    r = regime.regime_from_closes(closes)
    assert r["signal"] == "negative" and r["sma20"] < r["sma50"]


def test_signal_needs_50_bars():
    assert regime.regime_from_closes([1.0] * 49) is None


def test_market_hours():
    assert regime.is_market_open(ist(9, 20))
    assert not regime.is_market_open(ist(9, 10))
    assert not regime.is_market_open(ist(15, 25))
    assert not regime.is_market_open(ist(10, 0, day=21))     # Saturday


# ---- behaviour -------------------------------------------------------------

def test_enabling_sets_baseline_and_never_sells(env):
    db, st = env
    st["signal"] = "negative"                    # already negative when switched on
    enable(mode="live")
    assert settings(db)["last_signal"] == "negative"
    assert st["sold"] == []                      # no sale on enabling
    assert not settings(db).get("pending_kill")


def test_live_mode_requires_confirmation(env):
    with pytest.raises(HTTPException):
        enable(mode="live", confirm=False)


def test_alert_mode_turning_negative_only_alerts(env):
    db, st = env
    enable(mode="alert")
    st["signal"] = "negative"
    run(server._regime_check_for_user(UID, ist(9, 20)))
    assert st["sold"] == [] and not st["cancelled"]
    kinds = [e["kind"] for e in run(_events(db))]
    assert "alert" in kinds


async def _events(db):
    return [e async for e in db.regime_events.find({"user_id": UID})]


def test_live_mode_sells_everything_once(env):
    db, st = env
    enable(mode="live")
    st["signal"] = "negative"
    run(server._regime_check_for_user(UID, ist(9, 20)))
    assert st["cancelled"]
    assert sorted(s[0] for s in st["sold"]) == ["INFY", "TCS"]          # no F&O, no shorts
    assert all(s[2] == "S" and s[3] == "MKT" for s in st["sold"])
    assert settings(db)["last_kill_date"] == "2026-11-18"
    # same day again: no second sale
    st["sold"].clear()
    run(server._regime_check_for_user(UID, ist(9, 50)))
    run(server._regime_run_pending_kill(UID, ist(10, 0)))
    assert st["sold"] == []


def test_stays_quiet_while_still_negative_next_day(env):
    db, st = env
    enable(mode="live")
    st["signal"] = "negative"
    run(server._regime_check_for_user(UID, ist(9, 20)))
    st["sold"].clear()
    run(server._regime_check_for_user(UID, ist(9, 20, day=19)))
    assert st["sold"] == []


def test_rearms_and_fires_again_on_next_turn(env):
    db, st = env
    enable(mode="live")
    st["signal"] = "negative"
    run(server._regime_check_for_user(UID, ist(9, 20)))
    st["sold"].clear()
    st["signal"] = "positive"
    run(server._regime_check_for_user(UID, ist(9, 20, day=19)))
    st["signal"] = "negative"
    run(server._regime_check_for_user(UID, ist(9, 20, day=20)))
    assert len(st["sold"]) == 2


def test_kill_waits_for_market_hours(env):
    db, st = env
    enable(mode="live")
    st["signal"] = "negative"
    run(server._regime_check_for_user(UID, ist(8, 0)))           # before market open
    assert st["sold"] == [] and settings(db)["pending_kill"]
    run(server._regime_run_pending_kill(UID, ist(9, 25)))
    assert len(st["sold"]) == 2


def test_no_data_means_no_action(env):
    db, st = env
    enable(mode="live")
    st["signal"] = None
    run(server._regime_check_for_user(UID, ist(9, 20)))
    assert st["sold"] == []


def test_buys_blocked_only_when_negative_and_enabled(env):
    db, st = env
    assert run(server._buys_blocked(UID)) is None                # never configured
    enable(mode="alert", block=True)
    assert run(server._buys_blocked(UID)) is None                # positive
    st["signal"] = "negative"
    run(server._regime_check_for_user(UID, ist(9, 20)))
    assert "Blocked" in run(server._buys_blocked(UID))
    from server import RegimeSettingsInput
    run(server.regime_set_settings(RegimeSettingsInput(enabled=True, mode="alert", block_buys=False), USER))
    assert run(server._buys_blocked(UID)) is None                # block switched off
    run(server.regime_set_settings(RegimeSettingsInput(enabled=False, mode="alert", block_buys=True), USER))
    assert run(server._buys_blocked(UID)) is None                # disabled


def test_stoploss_run_skipped_after_kill(env):
    db, st = env
    enable(mode="live")
    st["signal"] = "negative"
    run(server._regime_check_for_user(UID, ist(9, 20)))
    # the simulated kill used a fixed date; point it at the real "today" the guard reads
    run(db.regime_settings.update_one({"user_id": UID}, {"$set": {"last_kill_date": regime.today_ist()}}))
    out = run(server._run_ema_sl_for_user(UID))
    assert out["count"] == 0 and "Kill switch" in out["skipped"]
