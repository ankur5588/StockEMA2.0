"""EMA10 calculation using yfinance as historical data source.

Kotak Neo symbols are NSE/BSE cash stocks. For yfinance we append `.NS` for
NSE and `.BO` for BSE. We accept the raw trading_symbol as it is returned
from the broker (e.g. `RELIANCE-EQ` -> strip `-EQ`).
"""
from __future__ import annotations
import logging
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def _normalise_symbol(symbol: str, exchange_segment: str = "nse_cm") -> str:
    """Convert a broker's trading symbol + exchange segment into a yfinance ticker.

    Accepts exchange_segment strings from multiple brokers (case-insensitive):
      - Kotak Neo: 'nse_cm', 'bse_cm'
      - Dhan:       'NSE_EQ',  'BSE_EQ',  'NSE_FNO', 'BSE_FNO'
      - Alice Blue: 'NSE',     'BSE',     'NFO',     'BFO'
    Returns 'SYMBOL.NS' for NSE and 'SYMBOL.BO' for BSE.
    """
    s = symbol.upper().strip()
    for suf in ("-EQ", "-BE", "-BZ", "-N1"):
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    seg = (exchange_segment or "").strip().lower()
    if seg.startswith("bse") or seg.startswith("bfo") or seg.startswith("b_"):
        return f"{s}.BO"
    return f"{s}.NS"


def compute_ema10(symbol: str, exchange_segment: str = "nse_cm") -> Optional[float]:
    """Return last EMA10 value on daily close. None if data unavailable."""
    ticker = _normalise_symbol(symbol, exchange_segment)
    try:
        hist = yf.Ticker(ticker).history(period="3mo", interval="1d", auto_adjust=False)
    except Exception as e:
        logger.warning("yfinance fetch failed for %s: %s", ticker, e)
        return None
    if hist is None or hist.empty or "Close" not in hist.columns:
        return None
    closes = hist["Close"].dropna()
    if len(closes) < 10:
        return None
    ema = closes.ewm(span=10, adjust=False).mean()
    val = float(ema.iloc[-1])
    return round(val, 2)
