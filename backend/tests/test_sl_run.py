"""Offline end-to-end test of the stoploss run + scheduler + Dhan token renewal.

No network, no real MongoDB, no real broker: the DB is mongomock, Dhan is faked.
"""
import asyncio
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "unit_test_db")
os.environ.setdefault("JWT_SECRET", "unit-test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

mongomock_motor = pytest.importorskip("mongomock_motor")

import server  # noqa: E402
import dhan_client  # noqa: E402
import stoploss_service as sl_svc  # noqa: E402
from security import encrypt_dict  # noqa: E402

UID = "user_t1"


def _jwt(exp_dt):
    def b(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{b({'alg': 'none'})}.{b({'exp': int(exp_dt.timestamp())})}.sig"


def _flat(n=40, price=100.0, rng=2.0):
    return ([price + rng / 2] * n, [price - rng / 2] * n, [price] * n)


@pytest.fixture
def env(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["t"]
    monkeypatch.setattr(server, "db", db)
    state = {"placed": [], "modified": [], "open_sl": None}

    monkeypatch.setattr(dhan_client, "is_authenticated", lambda u: True)
    monkeypatch.setattr(dhan_client, "get_positions", lambda u: [{
        "broker": "dhan", "symbol": "TCS", "exchange_segment": "NSE_EQ", "security_id": "11536",
        "quantity": 10, "avg_price": 100.0, "ltp": 103.0, "product": "CNC"}])
    monkeypatch.setattr(dhan_client, "find_open_sl", lambda u, sid: state["open_sl"])

    def fake_modify(u, oid, qty, price, trig):
        state["modified"].append((oid, qty, price, trig))
        return {"ok": True}
    monkeypatch.setattr(dhan_client, "modify_sl", fake_modify)

    def fake_place(**kw):
        state["placed"].append(kw)
        return {"ok": True, "order_id": "OID1"}
    monkeypatch.setattr(dhan_client, "place_order", fake_place)
    monkeypatch.setattr(dhan_client, "_security_id_for", lambda s, seg="NSE_EQ": "11536")

    monkeypatch.setattr(sl_svc, "fetch_ohlc", lambda sym, seg="nse_cm": _flat(rng=2.0))
    # other brokers off
    for m in (server.alice_client, server.indmoney_client, server.delta_client):
        monkeypatch.setattr(m, "is_authenticated", lambda u: False)
    return db, state


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_places_one_sl_at_higher_of_atr_and_fixed(env):
    db, st = env
    out = run(server._run_ema_sl_for_user(UID))
    assert out["count"] == 1
    r = out["runs"][0]
    # ATR stop = 100 - 2*2 = 96 ; fixed 8% = 92  -> 96 wins
    assert r["sl_trigger"] == 96.0 and r["basis"] == "atr"
    assert r["status"] == "placed"
    assert len(st["placed"]) == 1
    assert st["placed"][0]["trigger_price"] == 96.0
    assert st["placed"][0]["order_type"] == "SL"


def test_second_run_updates_existing_order_instead_of_new(env):
    db, st = env
    run(server._run_ema_sl_for_user(UID))
    st["open_sl"] = {"orderId": "OID1", "triggerPrice": 90.0}
    st["placed"].clear()
    out = run(server._run_ema_sl_for_user(UID))
    assert st["placed"] == []                       # no duplicate order
    assert st["modified"] and st["modified"][0][3] == 96.0
    assert out["runs"][0]["status"] == "placed"


def test_stop_never_moves_down_next_day(env, monkeypatch):
    db, st = env
    run(server._run_ema_sl_for_user(UID))                       # stop 96 saved
    monkeypatch.setattr(sl_svc, "fetch_ohlc",
                        lambda sym, seg="nse_cm": _flat(price=95.0, rng=2.0))  # ATR stop would be 91
    st["placed"].clear()
    out = run(server._run_ema_sl_for_user(UID))
    assert out["runs"][0]["sl_trigger"] == 96.0 and out["runs"][0]["basis"] == "previous"


def test_price_below_stop_is_not_sold_automatically(env, monkeypatch):
    db, st = env
    monkeypatch.setattr(dhan_client, "get_positions", lambda u: [{
        "broker": "dhan", "symbol": "TCS", "exchange_segment": "NSE_EQ", "security_id": "11536",
        "quantity": 10, "avg_price": 100.0, "ltp": 90.0, "product": "CNC"}])
    out = run(server._run_ema_sl_for_user(UID))
    assert out["runs"][0]["status"] == "skipped"
    assert st["placed"] == [] and st["modified"] == []


def test_fixed_stop_used_when_market_data_missing(env, monkeypatch):
    db, st = env
    monkeypatch.setattr(sl_svc, "fetch_ohlc", lambda sym, seg="nse_cm": None)
    out = run(server._run_ema_sl_for_user(UID))
    assert out["runs"][0]["sl_trigger"] == 92.0 and out["runs"][0]["basis"] == "fixed"


def test_trailing_state_cleared_when_position_closed(env, monkeypatch):
    db, st = env
    run(server._run_ema_sl_for_user(UID))
    assert run(db.sl_state.count_documents({"user_id": UID})) == 1
    monkeypatch.setattr(dhan_client, "get_positions", lambda u: [])
    run(server._run_ema_sl_for_user(UID))
    assert run(db.sl_state.count_documents({"user_id": UID})) == 0


def test_default_schedule_created_at_0930_ist(env):
    db, _ = env
    run(db.dhan_credentials.insert_one({"user_id": UID, "encrypted": "x"}))
    run(server._ensure_default_schedules())
    sched = run(db.ema_schedules.find_one({"user_id": UID}))
    assert sched["enabled"] and sched["interval"] == "daily"
    nxt = datetime.fromisoformat(sched["next_run_at"]).astimezone(sl_svc.IST)
    assert (nxt.hour, nxt.minute) == (9, 30) and nxt.weekday() < 5


def test_old_schedule_is_retimed(env):
    db, _ = env
    run(db.dhan_credentials.insert_one({"user_id": UID, "encrypted": "x"}))
    run(db.ema_schedules.insert_one({"user_id": UID, "interval": "daily", "enabled": True,
                                     "next_run_at": "2026-01-01T09:15:00+00:00"}))
    run(server._ensure_default_schedules())
    sched = run(db.ema_schedules.find_one({"user_id": UID}))
    nxt = datetime.fromisoformat(sched["next_run_at"]).astimezone(sl_svc.IST)
    assert (nxt.hour, nxt.minute) == (9, 30)


def test_token_renewed_when_under_14h_left(env, monkeypatch):
    db, _ = env
    old = _jwt(datetime.now(timezone.utc) + timedelta(hours=5))
    new = _jwt(datetime.now(timezone.utc) + timedelta(hours=24))
    doc = {"user_id": UID, "encrypted": encrypt_dict({"client_id": "1", "access_token": old})}
    run(db.dhan_credentials.insert_one(dict(doc)))
    monkeypatch.setattr(dhan_client, "renew_token",
                        lambda cid, tok: {"access_token": new, "expiry": None})
    monkeypatch.setattr(dhan_client, "connect", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(dhan_client, "is_authenticated", lambda u: False)
    monkeypatch.setattr(dhan_client, "disconnect", lambda u: None)
    run(server._renew_dhan_if_needed(doc))
    saved = run(db.dhan_credentials.find_one({"user_id": UID}))
    assert server.decrypt_dict(saved["encrypted"])["access_token"] == new
    assert saved["last_renewed_at"]


def test_token_not_renewed_when_plenty_of_time(env, monkeypatch):
    db, _ = env
    tok = _jwt(datetime.now(timezone.utc) + timedelta(hours=22))
    doc = {"user_id": UID, "encrypted": encrypt_dict({"client_id": "1", "access_token": tok})}
    run(db.dhan_credentials.insert_one(dict(doc)))
    called = []
    monkeypatch.setattr(dhan_client, "renew_token", lambda *a: called.append(1))
    run(server._renew_dhan_if_needed(doc))
    assert not called


def test_expired_token_reports_clear_error(env, monkeypatch):
    db, _ = env
    tok = _jwt(datetime.now(timezone.utc) - timedelta(hours=1))
    run(db.dhan_credentials.insert_one(
        {"user_id": UID, "encrypted": encrypt_dict({"client_id": "1", "access_token": tok})}))
    monkeypatch.setattr(dhan_client, "is_authenticated", lambda u: False)
    err = run(server._ensure_dhan(UID))
    assert "expired" in err.lower()
