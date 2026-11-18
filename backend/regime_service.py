"""Market regime signal for the portfolio kill switch.

Signal (Nifty 50 daily closes):
    negative  when  SMA20 < SMA50      -> stop new buys; (live mode) sell everything once
    positive  otherwise                -> re-arm

Decided on COMPLETED daily bars only (today's partial bar is dropped), checked
every weekday morning, so it matches the backtest: decide at the close, act next day.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Optional, Sequence

from stoploss_service import IST

logger = logging.getLogger(__name__)

INDEX_TICKER = "^NSEI"
FAST = 20
SLOW = 50

CHECK_HOUR = 9
CHECK_MINUTE = 20
MARKET_OPEN = time(9, 15)
MARKET_CLOSE_SELL_CUTOFF = time(15, 20)   # no new kill sells after this


def regime_from_closes(closes: Sequence[float], dates: Optional[Sequence] = None) -> Optional[dict]:
    """Pure function. Returns {signal, sma20, sma50, last_close, as_of} or None."""
    if len(closes) < SLOW:
        return None
    sma20 = sum(closes[-FAST:]) / FAST
    sma50 = sum(closes[-SLOW:]) / SLOW
    return {
        "signal": "negative" if sma20 < sma50 else "positive",
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2),
        "last_close": round(closes[-1], 2),
        "as_of": str(dates[-1])[:10] if dates is not None and len(dates) else None,
    }


def is_market_open(now: datetime) -> bool:
    """Weekday, 09:15 to 15:20 IST (holidays are not known here)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(IST)
    return local.weekday() < 5 and MARKET_OPEN <= local.time() <= MARKET_CLOSE_SELL_CUTOFF


def today_ist(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(IST).date().isoformat()


def fetch_closes(now: Optional[datetime] = None):
    """Completed daily closes of Nifty 50 (list of floats, list of dates) or None."""
    import yfinance as yf

    now = now or datetime.now(timezone.utc)
    try:
        hist = yf.Ticker(INDEX_TICKER).history(period="1y", interval="1d", auto_adjust=False)
    except Exception as e:
        logger.warning("Nifty fetch failed: %s", e)
        return None
    if hist is None or hist.empty:
        return None
    closes = hist["Close"].dropna()
    local = now.astimezone(IST)
    # Drop today's bar while the session is open or before the close is final
    if len(closes) and closes.index[-1].date() == local.date() and local.time() < time(16, 0):
        closes = closes.iloc[:-1]
    if len(closes) < SLOW:
        return None
    return [float(x) for x in closes], [d.date().isoformat() for d in closes.index]


def current_regime(now: Optional[datetime] = None) -> Optional[dict]:
    got = fetch_closes(now)
    if got is None:
        return None
    closes, dates = got
    return regime_from_closes(closes, dates)
