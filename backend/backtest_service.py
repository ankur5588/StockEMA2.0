"""Backtesting engine for NSE/BSE stocks using yfinance data.

Screening criteria (all must be true on a given candle):
  1. Range expansion: (H-L) > (prev H-L) for 7 consecutive days
  2. Daily close > daily open (green candle)
  3. Daily close > 1 day ago close
  4. Weekly close > weekly open
  5. Monthly close > monthly open
  6. Volume > 500,000
  7. SMA(20) > SMA(50)
  8. SMA(50) > SMA(200)
  9. RSI(14) > 50
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Tuple

import pandas as pd
import numpy as np
import yfinance as yf

logger = logging.getLogger(__name__)

# Default universe: Nifty 50 + Nifty Next 50 symbols (NSE)
NIFTY_100 = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "BAJFINANCE", "LT", "WIPRO", "AXISBANK",
    "TITAN", "ASIANPAINT", "MARUTI", "SUNPHARMA", "HCLTECH", "NTPC", "ONGC",
    "POWERGRID", "ULTRACEMCO", "BAJAJFINSV", "ADANIPORTS", "M&M", "TATAMOTORS",
    "NESTLEIND", "TATASTEEL", "JSWSTEEL", "TECHM", "INDUSINDBK", "BPCL", "SBILIFE",
    "HINDALCO", "GRASIM", "DIVISLAB", "DRREDDY", "CIPLA", "BRITANNIA", "COALINDIA",
    "EICHERMOT", "HEROMOTOCO", "APOLLOHOSP", "BAJAJ-AUTO", "ADANIENT", "TRENT",
    "BEL", "HDFCLIFE", "DLF", "PIDILITIND", "SIEMENS", "BANKBARODA", "TVSMOTOR",
    "ICICIPRULI", "ATUL", "LUPIN", "MUTHOOTFIN", "HAVELLS", "MARICO", "AMBUJACEM",
    "TORNTPHARM", "SRTRANSFIN", "BOSCHLTD", "CADILAHC", "COLPAL", "DABUR",
    "GODREJCP", "HINDZINC", "ICICIGI", "INDIGO", "NAUKRI", "PAGEIND", "PIDILITIND",
    "PEL", "PETRONET", "SHREECEM", "TIINDIA", "VEDL", "ZOMATO", "DMART",
]


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI for a price series."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    rsi_series[:period] = np.nan
    return rsi_series


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add indicator columns to a daily OHLCV DataFrame."""
    d = df.copy()
    d["range"] = d["High"] - d["Low"]
    d["SMA20"] = d["Close"].rolling(20).mean()
    d["SMA50"] = d["Close"].rolling(50).mean()
    d["SMA200"] = d["Close"].rolling(200).mean()
    d["RSI14"] = rsi(d["Close"], 14)

    # Weekly snap (last completed week)
    if isinstance(d.index, pd.DatetimeIndex):
        weekly = d.resample("W").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last",
        })
        monthly = d.resample("ME").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last",
        })
    else:
        d_idx = d.copy()
        d_idx.index = pd.to_datetime(d_idx.index)
        weekly = d_idx.resample("W").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last",
        })
        monthly = d_idx.resample("ME").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last",
        })

    return d, weekly, monthly


def _check_criteria(df: pd.DataFrame, weekly: pd.DataFrame, monthly: pd.DataFrame,
                    idx: int) -> Tuple[Dict, bool]:
    """Check all 9 screening criteria at position `idx` in `df`.

    Returns (criteria_dict, passed).
    """
    last = df.iloc[idx]
    if idx < 1:
        return {k: False for k in _CRITERIA_KEYS}, False
    prev = df.iloc[idx - 1]
    criteria = {}

    # 1. Range expansion 7d
    range_ok = True
    for i in range(1, 8):
        if idx - i < 0:
            range_ok = False
            break
        if df["range"].iloc[idx] <= df["range"].iloc[idx - i]:
            range_ok = False
            break
    criteria["range_expansion_7d"] = range_ok

    # 2. Close > open
    criteria["close_gt_open"] = bool(last["Close"] > last["Open"])

    # 3. Close > prev close
    criteria["close_gt_prev_close"] = bool(last["Close"] > prev["Close"])

    # 4. Weekly close > open: find the week containing this date
    criteria["weekly_close_gt_open"] = False
    if not weekly.empty:
        last_dt = df.index[idx]
        # Find the weekly bar that ends on or after this date
        weekly_in_effect = weekly[weekly.index <= pd.Timestamp(last_dt)]
        if not weekly_in_effect.empty:
            wl = weekly_in_effect.iloc[-1]
            criteria["weekly_close_gt_open"] = bool(wl["Close"] > wl["Open"])

    # 5. Monthly close > open
    criteria["monthly_close_gt_open"] = False
    if not monthly.empty:
        last_dt = df.index[idx]
        monthly_in_effect = monthly[monthly.index <= pd.Timestamp(last_dt)]
        if not monthly_in_effect.empty:
            ml = monthly_in_effect.iloc[-1]
            criteria["monthly_close_gt_open"] = bool(ml["Close"] > ml["Open"])

    # 6. Volume > 500K
    volume = last.get("Volume", 0)
    if pd.isna(volume):
        volume = 0
    criteria["volume_gt_500k"] = bool(int(volume) > 500000)

    # 7-8. SMA ordering
    sma20 = last.get("SMA20", 0)
    sma50 = last.get("SMA50", 0)
    sma200 = last.get("SMA200", 0)
    if pd.isna(sma20) or pd.isna(sma50) or pd.isna(sma200):
        criteria["sma_20_gt_50"] = False
        criteria["sma_50_gt_200"] = False
    else:
        criteria["sma_20_gt_50"] = bool(sma20 > sma50)
        criteria["sma_50_gt_200"] = bool(sma50 > sma200)

    # 9. RSI > 50
    rsi_val = last.get("RSI14", 0)
    if pd.isna(rsi_val):
        criteria["rsi_gt_50"] = False
    else:
        criteria["rsi_gt_50"] = bool(rsi_val > 50)

    passed = all(criteria.values())
    return criteria, passed


_CRITERIA_KEYS = [
    "range_expansion_7d", "close_gt_open", "close_gt_prev_close",
    "weekly_close_gt_open", "monthly_close_gt_open", "volume_gt_500k",
    "sma_20_gt_50", "sma_50_gt_200", "rsi_gt_50",
]


def backtest_symbol(symbol: str, period: str = "1y") -> Optional[Dict]:
    """Run the full screening criteria on a single symbol (latest candle only)."""
    ticker = yf.Ticker(f"{symbol}.NS")
    try:
        hist = ticker.history(period=period, interval="1d", auto_adjust=False)
    except Exception as e:
        logger.warning("yfinance fetch failed for %s: %s", symbol, e)
        return None

    if hist is None or hist.empty or len(hist) < 210:
        return None

    df, weekly, monthly = _compute_indicators(hist)
    last = df.iloc[-1]
    idx = len(df) - 1
    criteria, passed = _check_criteria(df, weekly, monthly, idx)

    prev = df.iloc[idx - 1] if idx >= 1 else last
    ltp = round(float(last["Close"]), 2)
    change_1d = round(float(((last["Close"] - prev["Close"]) / prev["Close"]) * 100), 2) if prev["Close"] else 0
    volume = int(last.get("Volume", 0)) if not pd.isna(last.get("Volume", 0)) else 0

    return {
        "symbol": symbol.upper(), "date": str(df.index[idx].date()),
        "ltp": ltp, "change_1d_pct": change_1d, "volume": volume,
        "sma20": round(float(last["SMA20"]), 2) if not pd.isna(last.get("SMA20", 0)) else None,
        "sma50": round(float(last["SMA50"]), 2) if not pd.isna(last.get("SMA50", 0)) else None,
        "sma200": round(float(last["SMA200"]), 2) if not pd.isna(last.get("SMA200", 0)) else None,
        "rsi14": round(float(last["RSI14"]), 2) if not pd.isna(last.get("RSI14", 0)) else None,
        "range": round(float(df["range"].iloc[-1]), 2),
        "passed": passed, "criteria": criteria,
    }


def _to_timestamp(date_str: str):
    """Parse a date string (ISO or DD-MM-YYYY) into a pd.Timestamp."""
    s = date_str.strip()
    try:
        return pd.Timestamp(s)
    except Exception:
        pass
    parts = s.split("-")
    if len(parts) == 3 and len(parts[2]) == 4:
        return pd.Timestamp(f"{parts[2]}-{parts[1]}-{parts[0]}")
    return pd.Timestamp(s)


def _forward_returns(hist: pd.DataFrame, idx: int, horizons: List[int] = None) -> Dict:
    """Compute buy-and-hold forward returns at multiple horizons.

    Buys at close of `idx`, sells at close of `idx + horizon`.
    Returns dict like {5: 2.34, 10: -1.2, ...} where values are % returns.
    """
    if horizons is None:
        horizons = [1, 5, 10, 20]
    entry_price = float(hist.iloc[idx]["Close"])
    results = {}
    for h in horizons:
        exit_idx = idx + h
        if exit_idx < len(hist):
            exit_price = float(hist.iloc[exit_idx]["Close"])
            ret = round((exit_price - entry_price) / entry_price * 100, 2)
        else:
            ret = None
        results[f"ret_{h}d"] = ret
    return results


def backtest_signal(symbol: str, target_date: str, forward_horizons: List[int] = None) -> Optional[Dict]:
    """Check screening criteria for a symbol on a specific historical date
    and simulate forward returns.

    The CSV contains signals generated on `target_date`. We check if
    the stock met the screening criteria *on that date*, then compute
    buy-and-hold returns at multiple forward horizons.
    """
    if forward_horizons is None:
        forward_horizons = [1, 5, 10, 20]
    max_forward = max(forward_horizons)

    target_dt = _to_timestamp(target_date)

    # Fetch enough backward data (2.5y) + forward data for horizons
    start = target_dt - pd.DateOffset(years=2, months=6)
    end = target_dt + pd.DateOffset(days=max_forward * 2 + 10)

    ticker = yf.Ticker(f"{symbol}.NS")
    try:
        hist = ticker.history(start=start, end=end, interval="1d", auto_adjust=False)
    except Exception as e:
        logger.warning("yfinance fetch failed for %s: %s", symbol, e)
        return None

    if hist is None or hist.empty or len(hist) < 210:
        return None

    # Match target date to index
    if hasattr(hist.index, "tz") and hist.index.tz is not None:
        target = target_dt.tz_localize(hist.index.tz) if target_dt.tz is None else target_dt
    else:
        target = target_dt.tz_localize(None) if hasattr(target_dt, "tz") and target_dt.tz is not None else target_dt

    trading_days = hist.index[hist.index <= target]
    if trading_days.empty:
        logger.warning("No trading data for %s on or before %s", symbol, target_date)
        return None

    nearest_idx = hist.index.get_loc(trading_days[-1])
    if isinstance(nearest_idx, slice):
        nearest_idx = nearest_idx.stop - 1
    if nearest_idx < 200:
        return None

    df, weekly, monthly = _compute_indicators(hist)
    idx = nearest_idx
    criteria, passed = _check_criteria(df, weekly, monthly, idx)

    last = df.iloc[idx]
    prev = df.iloc[idx - 1] if idx >= 1 else last
    ltp = round(float(last["Close"]), 2)
    change_1d = round(float(((last["Close"] - prev["Close"]) / prev["Close"]) * 100), 2) if prev["Close"] else 0
    volume = int(last.get("Volume", 0)) if not pd.isna(last.get("Volume", 0)) else 0

    # Compute forward returns for passed signals
    returns = _forward_returns(hist, idx, forward_horizons) if passed else {}

    return {
        "symbol": symbol.upper(), "date": str(df.index[idx].date()),
        "ltp": ltp, "change_1d_pct": change_1d, "volume": volume,
        "sma20": round(float(last["SMA20"]), 2) if not pd.isna(last.get("SMA20", 0)) else None,
        "sma50": round(float(last["SMA50"]), 2) if not pd.isna(last.get("SMA50", 0)) else None,
        "sma200": round(float(last["SMA200"]), 2) if not pd.isna(last.get("SMA200", 0)) else None,
        "rsi14": round(float(last["RSI14"]), 2) if not pd.isna(last.get("RSI14", 0)) else None,
        "range": round(float(df["range"].iloc[idx]), 2),
        "passed": passed, "criteria": criteria,
        "forward_returns": returns,
    }


async def run_backtest(symbols: Optional[List[str]] = None, period: str = "1y") -> Dict:
    """Run backtest across a universe of symbols (latest candle)."""
    if symbols is None or len(symbols) == 0:
        symbols = NIFTY_100

    results: List[Dict] = []
    for sym in symbols:
        result = backtest_symbol(sym.strip().upper(), period)
        if result is not None:
            results.append(result)

    return _summarize(results, len(symbols))


async def run_signal_backtest(signals: List[Dict]) -> Dict:
    """Run backtest on a list of signal dicts from a CSV upload.

    Each signal has: date, symbol, marketcapname, sector.
    Evaluates whether the stock met the screening criteria on that date.
    """
    results: List[Dict] = []
    total = len(signals)
    passed_count = 0

    for sig in signals:
        sym = sig["symbol"].strip().upper()
        dt = sig["date"].strip()
        result = backtest_signal(sym, dt)
        if result is None:
            results.append({
                "symbol": sym, "date": dt, "marketcapname": sig.get("marketcapname", ""),
                "sector": sig.get("sector", ""), "passed": False,
                "error": "No data", "criteria": {k: False for k in _CRITERIA_KEYS},
            })
        else:
            result["marketcapname"] = sig.get("marketcapname", "")
            result["sector"] = sig.get("sector", "")
            if result["passed"]:
                passed_count += 1
            results.append(result)

    return _summarize(results, total, include_detail=True)


def _summarize(results: List[Dict], total_scanned: int,
               include_detail: bool = False) -> Dict:
    """Build summary dict from a list of result dicts.

    Includes portfolio allocation recommendations based on pass rates
    per market-cap category and position sizing analysis.
    """
    CAPITAL = 500000  # ₹5,00,000

    passed = [r for r in results if r.get("passed")]
    failed = [r for r in results if not r.get("passed")]
    passed_symbols = [r["symbol"] for r in passed]
    data_available = len(results)

    # Aggregation by sector and marketcap
    sector_breakdown = {}
    marketcap_breakdown = {}
    for r in results:
        sec = r.get("sector", "Unknown")
        cap = r.get("marketcapname", "Unknown")
        sector_breakdown.setdefault(sec, {"total": 0, "passed": 0})
        sector_breakdown[sec]["total"] += 1
        if r.get("passed"):
            sector_breakdown[sec]["passed"] += 1
        marketcap_breakdown.setdefault(cap, {"total": 0, "passed": 0})
        marketcap_breakdown[cap]["total"] += 1
        if r.get("passed"):
            marketcap_breakdown[cap]["passed"] += 1

    # ---- Portfolio allocation by market cap ----
    # Compute pass rate per category, then allocate proportionally
    cap_pass_rates = {}
    for cap, data in marketcap_breakdown.items():
        if cap == "Unknown":
            continue
        rate = (data["passed"] / data["total"] * 100) if data["total"] > 0 else 0
        cap_pass_rates[cap] = rate

    total_rate = sum(cap_pass_rates.values()) or 1  # avoid div-by-zero
    allocation = {}
    for cap, rate in cap_pass_rates.items():
        pct = round(rate / total_rate * 100, 1) if total_rate > 0 else 0
        allocation[cap] = {
            "pass_rate": round(rate, 1),
            "allocation_pct": pct,
            "capital_amount": round(CAPITAL * pct / 100),
            "signals_total": marketcap_breakdown[cap]["total"],
            "signals_passed": marketcap_breakdown[cap]["passed"],
        }

    # ---- Positions per day analysis ----
    from collections import Counter
    date_counts = Counter()
    for r in results:
        dt = r.get("date", "")
        if r.get("passed") and dt:
            date_counts[dt] += 1

    counts = list(date_counts.values())
    avg_positions = round(sum(counts) / len(counts), 1) if counts else 0
    max_positions = max(counts) if counts else 0
    trading_days = len(date_counts)

    # ---- Forward-return analysis (win rate & returns) ----
    HORIZONS = [1, 5, 10, 20]
    returns_analysis = {}
    for h in HORIZONS:
        key = f"ret_{h}d"
        vals = []
        for r in passed:
            fr = r.get("forward_returns") or {}
            v = fr.get(key)
            if v is not None:
                vals.append(v)
        if vals:
            arr = np.array(vals)
            wins = sum(1 for v in vals if v > 0)
            losses = sum(1 for v in vals if v <= 0)
            returns_analysis[f"{h}d"] = {
                "count": len(vals),
                "win_rate": round(wins / len(vals) * 100, 1),
                "loss_rate": round(losses / len(vals) * 100, 1),
                "avg_return": round(float(np.mean(arr)), 2),
                "median_return": round(float(np.median(arr)), 2),
                "best_return": round(float(np.max(arr)), 2),
                "worst_return": round(float(np.min(arr)), 2),
                "std_return": round(float(np.std(arr)), 2),
                "total_wins": wins,
                "total_losses": losses,
            }
        else:
            returns_analysis[f"{h}d"] = {
                "count": 0, "win_rate": 0, "avg_return": 0,
            }

    # Per-trade capital with risk consideration
    per_trade = round(CAPITAL / max_positions / 2) if max_positions > 0 else 0

    avg_rsi = float(np.mean([r["rsi14"] for r in results if r.get("rsi14") is not None])) if passed else 0

    summary = {
        "total_scanned": total_scanned,
        "data_available": data_available,
        "passed": len(passed),
        "failed": len(failed),
        "pass_rate": round(len(passed) / data_available * 100, 1) if data_available else 0,
        "passed_symbols": passed_symbols,
        "avg_rsi_passed": round(avg_rsi, 2),
        "results": results if include_detail else [r for r in results],
        "sector_breakdown": sector_breakdown,
        "marketcap_breakdown": marketcap_breakdown,
        "portfolio": {
            "total_capital": CAPITAL,
            "allocation": allocation,
            "avg_open_positions": avg_positions,
            "max_open_positions": max_positions,
            "trading_days_with_signals": trading_days,
            "per_trade_capital": per_trade,
            "max_positions_at_once": max(1, max_positions),
        },
        "returns": returns_analysis,
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }
    return summary
