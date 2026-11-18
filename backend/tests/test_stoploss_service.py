"""Offline unit tests for ATR trailing stop, 8% fixed stop and IST scheduling."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stoploss_service import compute_atr, compute_stop, next_daily_run, next_run, IST  # noqa: E402


def _flat(n=40, price=100.0, rng=2.0):
    closes = [price] * n
    highs = [price + rng / 2] * n
    lows = [price - rng / 2] * n
    return highs, lows, closes


def test_atr_constant_range():
    h, l, c = _flat(rng=2.0)
    assert abs(compute_atr(h, l, c) - 2.0) < 1e-9


def test_atr_not_enough_data():
    h, l, c = _flat(n=10)
    assert compute_atr(h, l, c) is None


def test_atr_stop_is_highest_close_minus_2_atr():
    h, l, c = _flat(rng=2.0)
    r = compute_stop(h, l, c, avg_price=0)
    assert r["atr_stop"] == 96.0   # 100 - 2*2
    assert r["stop"] == 96.0
    assert r["basis"] == "atr"


def test_fixed_8pct_wins_when_tighter():
    h, l, c = _flat(rng=10.0)         # ATR 10 -> atr_stop 80
    r = compute_stop(h, l, c, avg_price=100.0)  # fixed 92
    assert r["fixed_stop"] == 92.0
    assert r["stop"] == 92.0
    assert r["basis"] == "fixed"


def test_atr_wins_when_tighter_than_fixed():
    h, l, c = _flat(rng=2.0)          # atr_stop 96
    r = compute_stop(h, l, c, avg_price=100.0)  # fixed 92
    assert r["stop"] == 96.0 and r["basis"] == "atr"


def test_trailing_never_moves_down():
    h, l, c = _flat(rng=10.0)         # atr_stop 80, fixed 92
    r = compute_stop(h, l, c, avg_price=100.0, prev_stop=97.5)
    assert r["stop"] == 97.5 and r["basis"] == "previous"


def test_trailing_moves_up_with_new_high():
    h, l, c = _flat(rng=2.0)
    c = c[:-1] + [120.0]
    h = h[:-1] + [121.0]
    r = compute_stop(h, l, c, avg_price=100.0, prev_stop=96.0)
    assert r["stop"] > 96.0


def test_fixed_only_when_no_market_data():
    r = compute_stop([], [], [], avg_price=200.0)
    assert r["stop"] == 184.0 and r["basis"] == "fixed"


def test_no_inputs_gives_none():
    r = compute_stop([], [], [], avg_price=0)
    assert r["stop"] is None


def _ist(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def test_daily_run_is_0930_ist_not_utc():
    # Wed 2026-11-18 08:00 IST -> same day 09:30 IST
    nxt = next_daily_run(_ist(2026, 11, 18, 8, 0).astimezone(timezone.utc))
    local = nxt.astimezone(IST)
    assert (local.year, local.month, local.day, local.hour, local.minute) == (2026, 11, 18, 9, 30)
    assert nxt.hour == 4 and nxt.minute == 0  # 09:30 IST == 04:00 UTC


def test_daily_run_after_time_goes_next_day():
    nxt = next_daily_run(_ist(2026, 11, 18, 9, 31).astimezone(timezone.utc)).astimezone(IST)
    assert (nxt.day, nxt.hour, nxt.minute) == (19, 9, 30)


def test_daily_run_skips_weekend():
    # Friday 2026-11-20 10:00 IST -> Monday 2026-11-23 09:30 IST
    nxt = next_daily_run(_ist(2026, 11, 20, 10, 0).astimezone(timezone.utc)).astimezone(IST)
    assert nxt.weekday() == 0 and (nxt.day, nxt.hour, nxt.minute) == (23, 9, 30)


def test_next_run_intervals():
    now = datetime(2026, 11, 18, 5, 10, tzinfo=timezone.utc)
    assert next_run("1h", now).hour == 6
    assert next_run("2h", now).hour == 7
    assert next_run("daily", now).astimezone(IST).hour == 9
