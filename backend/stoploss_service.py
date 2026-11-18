"""Stoploss maths: ATR trailing stop + fixed-percent stop, and IST scheduling.

Final stop for a long position:

    atr_stop   = highest close of last LOOKBACK days - ATR_MULT * ATR(ATR_PERIOD)
    fixed_stop = avg_entry_price * (1 - FIXED_PCT / 100)
    stop       = max(atr_stop, fixed_stop, previous_stop)     # trailing: never moves down

One SL order per position is placed at `stop`. Two sell orders for the same
shares would be rejected by the broker, so the tighter (higher) of the two
protective levels is used.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

ATR_PERIOD = 14
ATR_MULT = 2.0
LOOKBACK = 22
FIXED_PCT = 8.0
RUN_HOUR = 9
RUN_MINUTE = 30


# ---------------------------------------------------------------------------
# Maths (pure, no network)
# ---------------------------------------------------------------------------

def compute_atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
                period: int = ATR_PERIOD) -> Optional[float]:
    """Wilder ATR. Returns None if there is not enough data."""
    n = len(closes)
    if n < period + 1 or len(highs) != n or len(lows) != n:
        return None
    trs = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def compute_stop(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    avg_price: float,
    prev_stop: Optional[float] = None,
    atr_period: int = ATR_PERIOD,
    atr_mult: float = ATR_MULT,
    lookback: int = LOOKBACK,
    fixed_pct: float = FIXED_PCT,
) -> dict:
    """Return {atr, atr_stop, fixed_stop, stop, basis}. `stop` is None when
    neither ATR data nor an entry price is available."""
    atr = compute_atr(highs, lows, closes, atr_period)
    atr_stop = None
    if atr is not None and len(closes) >= 1:
        hh = max(closes[-lookback:])
        atr_stop = hh - atr_mult * atr
        if atr_stop <= 0:
            atr_stop = None
    fixed_stop = avg_price * (1 - fixed_pct / 100.0) if avg_price and avg_price > 0 else None

    candidates = {
        "atr": atr_stop,
        "fixed": fixed_stop,
        "previous": prev_stop if prev_stop and prev_stop > 0 else None,
    }
    live = {k: v for k, v in candidates.items() if v is not None}
    if not live:
        return {"atr": atr, "atr_stop": None, "fixed_stop": None, "stop": None, "basis": None}
    basis = max(live, key=lambda k: live[k])
    return {
        "atr": round(atr, 2) if atr is not None else None,
        "atr_stop": round(atr_stop, 2) if atr_stop is not None else None,
        "fixed_stop": round(fixed_stop, 2) if fixed_stop is not None else None,
        "stop": round(live[basis], 2),
        "basis": basis,
    }


# ---------------------------------------------------------------------------
# Market data (yfinance)
# ---------------------------------------------------------------------------

def _yf_ticker(symbol: str, exchange_segment: str) -> str:
    from ema_service import _normalise_symbol  # same symbol rules as before
    return _normalise_symbol(symbol, exchange_segment)


def fetch_ohlc(symbol: str, exchange_segment: str = "nse_cm"):
    """Return (highs, lows, closes) lists of daily bars, or None."""
    import yfinance as yf

    ticker = _yf_ticker(symbol, exchange_segment)
    try:
        hist = yf.Ticker(ticker).history(period="6mo", interval="1d", auto_adjust=False)
    except Exception as e:
        logger.warning("yfinance fetch failed for %s: %s", ticker, e)
        return None
    if hist is None or hist.empty:
        return None
    hist = hist.dropna(subset=["High", "Low", "Close"])
    if len(hist) < ATR_PERIOD + 2:
        return None
    return (
        [float(x) for x in hist["High"]],
        [float(x) for x in hist["Low"]],
        [float(x) for x in hist["Close"]],
    )


def stop_for_position(symbol: str, exchange_segment: str, avg_price: float,
                      prev_stop: Optional[float] = None) -> dict:
    """Fetch data and compute the stop. If market data is missing the fixed
    stop (and previous stop) still apply."""
    ohlc = fetch_ohlc(symbol, exchange_segment)
    if ohlc is None:
        res = compute_stop([], [], [], avg_price, prev_stop)
        res["data_ok"] = False
        res["last_close"] = None
        return res
    h, l, c = ohlc
    res = compute_stop(h, l, c, avg_price, prev_stop)
    res["data_ok"] = True
    res["last_close"] = round(c[-1], 2)
    return res


# ---------------------------------------------------------------------------
# Scheduling (IST, weekdays only)
# ---------------------------------------------------------------------------

def next_daily_run(now: datetime, hour: int = RUN_HOUR, minute: int = RUN_MINUTE) -> datetime:
    """Next weekday `hour:minute` IST strictly after `now`. Returns a UTC datetime."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(IST)
    cand = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if cand <= local:
        cand += timedelta(days=1)
    while cand.weekday() >= 5:  # 5=Sat, 6=Sun
        cand += timedelta(days=1)
    return cand.astimezone(timezone.utc)


def next_run(interval: str, now: datetime) -> datetime:
    """Next run time (UTC) for the stored schedule interval."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if interval == "1h":
        return (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    if interval == "2h":
        return (now + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    return next_daily_run(now)
