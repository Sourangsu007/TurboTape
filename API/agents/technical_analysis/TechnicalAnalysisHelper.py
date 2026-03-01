"""
TechnicalAnalysisHelper
============
A unified OHLCV + Technical Analysis fetcher for Indian stocks.

Fallback chain for raw data:
    yfinance (NSE) → Stooq → Twelve Data → Tiingo → yfinance (BSE)

Single public entry point:
    fetcher.get_technical_analysis("RELIANCE")

API keys and all indicator parameters are loaded from a .env file — never hardcoded.
"""

import json
import os
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

# Load .env from the same directory as this file (or project root / CWD)
load_dotenv()

try:
    import yfinance as yf
    _YFINANCE_AVAILABLE = True
except ImportError:
    _YFINANCE_AVAILABLE = False

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level private helpers — data cleaning
# ─────────────────────────────────────────────────────────────────────────────

def _clean_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise column names, drop bad rows, sort ascending by date."""
    df = df.copy()
    df.columns = [c.lower().strip() for c in df.columns]
    rename_map = {
        "adj close": "close", "adjclose": "close",
        "vol": "volume", "turnover": "volume",
        "adjopen": "open", "adjhigh": "high", "adjlow": "low", "adjvolume": "volume"
    }
    df.rename(columns=rename_map, inplace=True)
    required = {"open", "high", "low", "close"}
    if not required.issubset(df.columns):
        raise ValueError(f"Missing required OHLC columns. Got: {list(df.columns)}")
    if "volume" not in df.columns:
        df["volume"] = 0
    df = df[["open", "high", "low", "close", "volume"]].copy()
    df = df.apply(pd.to_numeric, errors="coerce")
    df.dropna(subset=["open", "high", "low", "close"], inplace=True)
    df = df[df["close"] > 0]
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    df.sort_index(ascending=True, inplace=True)
    df.index = df.index.normalize()
    df = df[~df.index.duplicated(keep="last")]
    return df


def _safe(val) -> Optional[float]:
    """Return rounded float or None for NaN/Inf/None values."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if (np.isnan(f) or np.isinf(f)) else round(f, 4)
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Module-level private helpers — resilient HTTP session
# ─────────────────────────────────────────────────────────────────────────────

def _make_http_session(max_retries: int = 3) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total            = max_retries,
        backoff_factor   = 1,
        status_forcelist = {500, 502, 503, 504},
        allowed_methods  = {"GET"},
        raise_on_status  = False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    return session


def _http_get(
    session:         requests.Session,
    url:             str,
    params:          dict  = None,
    headers:         dict  = None,
    connect_timeout: float = 10.0,
    read_timeout:    float = 60.0,
    max_retries:     int   = 3,
    backoff:         float = 5.0,
    provider_name:   str   = "HTTP",
) -> requests.Response:
    timeout  = (connect_timeout, read_timeout)
    last_exc = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp

        except requests.exceptions.ReadTimeout as e:
            last_exc = e
            wait = backoff * (2 ** (attempt - 1))
            logger.warning(f"[{provider_name}] ReadTimeout on attempt {attempt}/{max_retries}. Retrying in {wait:.0f}s…")
            time.sleep(wait)

        except requests.exceptions.ConnectTimeout as e:
            last_exc = e
            wait = backoff * (2 ** (attempt - 1))
            logger.warning(f"[{provider_name}] ConnectTimeout on attempt {attempt}/{max_retries}. Retrying in {wait:.0f}s…")
            time.sleep(wait)

        except requests.exceptions.ConnectionError as e:
            last_exc = e
            wait = backoff * (2 ** (attempt - 1))
            logger.warning(f"[{provider_name}] ConnectionError on attempt {attempt}/{max_retries}. Retrying in {wait:.0f}s…")
            time.sleep(wait)

        except requests.exceptions.HTTPError:
            raise

    raise requests.exceptions.RetryError(
        f"[{provider_name}] All {max_retries} attempts failed. Last error: {last_exc}"
    ) from last_exc


# ─────────────────────────────────────────────────────────────────────────────
# Module-level private helpers — provider fetchers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_yfinance(ticker_ns: str, period: str, interval: str) -> pd.DataFrame:
    if not _YFINANCE_AVAILABLE:
        raise ImportError("yfinance not installed. Run: pip install yfinance")
    t  = yf.Ticker(ticker_ns)
    df = t.history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        raise ValueError(f"yfinance returned empty DataFrame for {ticker_ns}")
    return _clean_df(df)


def _fetch_stooq(ticker_base: str, period: str) -> pd.DataFrame:
    period_days = {
        "1mo": 30,  "3mo": 90,  "6mo": 180,
        "1y": 365,  "2y": 730,  "5y": 1825,  "10y": 3650,
    }
    days  = period_days.get(period, 365)
    end   = datetime.today()
    start = end - timedelta(days=days)

    stooq_symbol = f"{ticker_base.lower()}.ns"
    url    = "https://stooq.com/q/d/l/"
    params = {
        "s":  stooq_symbol,
        "d1": start.strftime("%Y%m%d"),
        "d2": end.strftime("%Y%m%d"),
        "i":  "d",
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    resp = requests.get(url, params=params, headers=headers, timeout=(10, 30))
    resp.raise_for_status()

    if "no data" in resp.text.lower() or len(resp.text.strip()) < 30:
        raise ValueError(f"Stooq returned no data for '{stooq_symbol}'.")

    from io import StringIO
    df = pd.read_csv(StringIO(resp.text))
    if df.empty:
        raise ValueError(f"Stooq returned empty CSV for '{stooq_symbol}'")

    df.columns = [c.lower().strip() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    return _clean_df(df)


def _fetch_twelve_data(
    ticker_base:     str,
    yf_ticker:       str,
    period:          str,
    interval:        str,
    api_key:         str,
    connect_timeout: float = 10.0,
    read_timeout:    float = 60.0,
    max_retries:     int   = 3,
    backoff:         float = 5.0,
) -> pd.DataFrame:
    if not api_key:
        raise ValueError("Twelve Data API key not configured — skipping")

    period_bars  = {
        "1mo": 30,  "3mo": 90,  "6mo": 130,
        "1y": 252,  "2y": 504,  "5y": 1260,  "10y": 2520,
    }
    interval_map = {
        "1d": "1day", "1wk": "1week", "1mo": "1month",
        "1h": "1h",   "30m": "30min", "15m": "15min",
        "5m": "5min", "1m":  "1min",
    }
    exchange_code = "BSE" if yf_ticker and yf_ticker.endswith(".BO") else "XNSE"
    params = {
        "symbol":     ticker_base,
        "exchange":   exchange_code,
        "interval":   interval_map.get(interval, "1day"),
        "outputsize": period_bars.get(period, 252),
        "apikey":     api_key,
        "format":     "JSON",
        "order":      "ASC",
    }

    session = _make_http_session(max_retries=max_retries)
    resp = _http_get(
        session,
        url             = "https://api.twelvedata.com/time_series",
        params          = params,
        connect_timeout = connect_timeout,
        read_timeout    = read_timeout,
        max_retries     = max_retries,
        backoff         = backoff,
        provider_name   = "TwelveData",
    )

    data = resp.json()
    if data.get("status") == "error":
        raise ValueError(f"Twelve Data API error: {data.get('message')}")
    values = data.get("values", [])
    if not values:
        raise ValueError("Twelve Data returned no values")

    df = pd.DataFrame(values)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)
    return _clean_df(df)


def _fetch_tiingo(
    ticker_base:     str,
    period:          str,
    api_key:         str,
    connect_timeout: float = 10.0,
    read_timeout:    float = 60.0,
    max_retries:     int   = 3,
    backoff:         float = 5.0,
) -> pd.DataFrame:
    if not api_key:
        raise ValueError("Tiingo API key not configured — skipping")

    period_days = {
        "1mo": 30,  "3mo": 90,  "6mo": 180,
        "1y": 365,  "2y": 730,  "5y": 1825,  "10y": 3650,
    }
    days  = period_days.get(period, 365)
    start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")

    # For Indian equities, Tiingo requires prepending 'nse/' (e.g. nse/polycab)
    # The default ticker_base we receive is just 'POLYCAB'
    tiingo_ticker = f"nse/{ticker_base.lower()}"
    
    url     = f"https://api.tiingo.com/tiingo/daily/{tiingo_ticker}/prices"
    params  = {"startDate": start}
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Token {api_key}",
    }

    session = _make_http_session(max_retries=max_retries)
    resp = _http_get(
        session,
        url             = url,
        params          = params,
        headers         = headers,
        connect_timeout = connect_timeout,
        read_timeout    = read_timeout,
        max_retries     = max_retries,
        backoff         = backoff,
        provider_name   = "Tiingo",
    )

    data = resp.json()
    if not data:
        raise ValueError(f"Tiingo returned no data for {ticker_base}")

    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    return _clean_df(df)


def _fetch_yfinance_bse(ticker_base: str, period: str, interval: str) -> pd.DataFrame:
    if not _YFINANCE_AVAILABLE:
        raise ImportError("yfinance not installed. Run: pip install yfinance")
    bse_ticker = f"{ticker_base}.BO"
    t  = yf.Ticker(bse_ticker)
    df = t.history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        raise ValueError(f"yfinance (BSE fallback) returned empty DataFrame for {bse_ticker}")
    return _clean_df(df)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level private helpers — technical indicators
# ─────────────────────────────────────────────────────────────────────────────

def _calc_sma(close: pd.Series, period: int) -> Optional[float]:
    if len(close) < period:
        return None
    return _safe(close.rolling(window=period).mean().iloc[-1])


def _calc_ema(close: pd.Series, period: int) -> Optional[float]:
    if len(close) < period:
        return None
    return _safe(close.ewm(span=period, adjust=False).mean().iloc[-1])


def _calc_rsi_full(
    close:      pd.Series,
    rsi_length: int = 14,
    sma_length: int = 14,
    ema_length: int = 14,
) -> dict:
    empty = {"rsi": None, "rsi_sma": None, "rsi_ema": None}
    if len(close) < rsi_length + 1:
        return empty
    try:
        delta      = close.diff()
        gain       = delta.clip(lower=0)
        loss       = -delta.clip(upper=0)
        avg_gain   = gain.ewm(com=rsi_length - 1, min_periods=rsi_length).mean()
        avg_loss   = loss.ewm(com=rsi_length - 1, min_periods=rsi_length).mean()
        rs         = avg_gain / avg_loss.replace(0, np.nan)
        rsi_series = 100 - (100 / (1 + rs))

        rsi_sma = (
            _safe(rsi_series.rolling(window=sma_length).mean().iloc[-1])
            if len(rsi_series.dropna()) >= sma_length else None
        )
        rsi_ema = (
            _safe(rsi_series.ewm(span=ema_length, adjust=False).mean().iloc[-1])
            if len(rsi_series.dropna()) >= ema_length else None
        )

        return {
            "rsi":     _safe(rsi_series.iloc[-1]),
            "rsi_sma": rsi_sma,
            "rsi_ema": rsi_ema,
        }
    except Exception as e:
        logger.warning(f"RSI calculation error: {e}")
        return empty


def _calc_adx(
    high:          pd.Series,
    low:           pd.Series,
    close:         pd.Series,
    adx_length:    int = 14,
    adx_smoothing: int = 14,
) -> dict:
    empty = {"adx": None, "di_plus": None, "di_minus": None}
    min_rows = adx_length + adx_smoothing + 1
    if len(close) < min_rows:
        return empty
    try:
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)

        dm_plus  = high.diff()
        dm_minus = -low.diff()
        dm_plus  = dm_plus.where((dm_plus > dm_minus) & (dm_plus > 0),  0.0)
        dm_minus = dm_minus.where((dm_minus > dm_plus) & (dm_minus > 0), 0.0)

        atr  = tr.ewm(com=adx_length - 1,    min_periods=adx_length).mean()
        di_p  = 100 * dm_plus.ewm( com=adx_length - 1, min_periods=adx_length).mean() / atr.replace(0, np.nan)
        di_m  = 100 * dm_minus.ewm(com=adx_length - 1, min_periods=adx_length).mean() / atr.replace(0, np.nan)
        dx    = 100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)
        adx   = dx.ewm(com=adx_smoothing - 1, min_periods=adx_smoothing).mean()

        return {
            "adx":      _safe(adx.iloc[-1]),
            "di_plus":  _safe(di_p.iloc[-1]),
            "di_minus": _safe(di_m.iloc[-1]),
        }
    except Exception as e:
        logger.warning(f"ADX calculation error: {e}")
        return empty


def _calc_psar(
    high:     pd.Series,
    low:      pd.Series,
    close:    pd.Series,
    af_start: float = 0.002,
    af_step:  float = 0.002,
    af_max:   float = 0.5,
) -> dict:
    empty = {"psar": None, "psar_trend": None}
    if len(close) < 2:
        return empty
    try:
        h, l, c = high.values, low.values, close.values
        n = len(c)

        bull = True
        af   = af_start
        ep   = l[0]
        psar = h[0]

        psar_arr  = np.zeros(n)
        trend_arr = np.zeros(n, dtype=bool)

        for i in range(1, n):
            prev_psar = psar
            if bull:
                psar = prev_psar + af * (ep - prev_psar)
                psar = min(psar, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
                if h[i] > ep:
                    ep = h[i]
                    af = min(af + af_step, af_max)
                if l[i] < psar:
                    bull  = False
                    psar  = ep
                    ep    = l[i]
                    af    = af_start
            else:
                psar = prev_psar + af * (ep - prev_psar)
                psar = max(psar, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
                if l[i] < ep:
                    ep = l[i]
                    af = min(af + af_step, af_max)
                if h[i] > psar:
                    bull  = True
                    psar  = ep
                    ep    = h[i]
                    af    = af_start

            psar_arr[i]  = psar
            trend_arr[i] = bull

        return {
            "psar":       _safe(psar_arr[-1]),
            "psar_trend": "bullish" if bool(trend_arr[-1]) else "bearish",
        }
    except Exception as e:
        logger.warning(f"PSAR calculation error: {e}")
        return empty


def _calc_supertrend(
    high:       pd.Series,
    low:        pd.Series,
    close:      pd.Series,
    period:     int   = 7,
    multiplier: float = 3.0,
) -> dict:
    empty = {"supertrend": None, "supertrend_trend": None}
    if len(close) < period + 1:
        return empty
    try:
        hl_avg = (high + low) / 2
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.ewm(com=period - 1, min_periods=period).mean()

        upper_band = hl_avg + multiplier * atr
        lower_band = hl_avg - multiplier * atr

        supertrend = pd.Series(np.nan, index=close.index, dtype=float)
        direction  = pd.Series(0,      index=close.index, dtype=int)

        for i in range(period, len(close)):
            ub      = upper_band.iloc[i]
            lb      = lower_band.iloc[i]
            prev_ub = upper_band.iloc[i - 1]
            prev_lb = lower_band.iloc[i - 1]

            ub = ub if (ub < prev_ub or close.iloc[i - 1] > prev_ub) else prev_ub
            lb = lb if (lb > prev_lb or close.iloc[i - 1] < prev_lb) else prev_lb

            prev_st = supertrend.iloc[i - 1]

            if np.isnan(prev_st):
                direction.iloc[i]  = 1
                supertrend.iloc[i] = lb
            elif prev_st == upper_band.iloc[i - 1]:
                direction.iloc[i]  = 1  if close.iloc[i] > ub else -1
                supertrend.iloc[i] = lb if direction.iloc[i] == 1 else ub
            else:
                direction.iloc[i]  = -1 if close.iloc[i] < lb else 1
                supertrend.iloc[i] = lb if direction.iloc[i] == 1 else ub

        return {
            "supertrend":       _safe(supertrend.iloc[-1]),
            "supertrend_trend": "bullish" if int(direction.iloc[-1]) == 1 else "bearish",
        }
    except Exception as e:
        logger.warning(f"SuperTrend calculation error: {e}")
        return empty


def _calc_donchian(
    high:   pd.Series,
    low:    pd.Series,
    length: int = 20,
) -> dict:
    """
    Donchian Channels.
    upper  = highest high over the last `length` bars
    lower  = lowest  low  over the last `length` bars
    middle = (upper + lower) / 2
    """
    empty = {"upper": None, "middle": None, "lower": None}
    if len(high) < length:
        return empty
    try:
        upper  = _safe(high.rolling(window=length).max().iloc[-1])
        lower  = _safe(low.rolling(window=length).min().iloc[-1])
        middle = _safe((upper + lower) / 2) if upper is not None and lower is not None else None
        return {"upper": upper, "middle": middle, "lower": lower}
    except Exception as e:
        logger.warning(f"Donchian Channels calculation error: {e}")
        return empty


def _calc_donchian_slope(
    high:        pd.Series,
    low:         pd.Series,
    dc_length:   int = 20,
    slope_bars:  int = 5,
) -> dict:
    """
    Donchian Channel Slope.

    Measures the rate of change of the Donchian midline over the last
    `slope_bars` periods.  A rising slope signals a widening / bullish
    channel; a falling slope signals a narrowing / bearish channel.

    Parameters
    ----------
    dc_length   : rolling window for the Donchian channel itself (default 20)
    slope_bars  : how many bars back to measure the midline change  (default 5)

    Returns
    -------
    slope           : absolute change in midline per bar (price units)
    slope_pct       : percentage change in midline per bar (relative to current mid)
    slope_direction : "rising" | "falling" | "flat"
                      flat = |slope_pct| < 0.05 % per bar
    """
    empty = {"slope": None, "slope_pct": None, "slope_direction": None}
    min_bars = dc_length + slope_bars
    if len(high) < min_bars:
        return empty
    try:
        upper  = high.rolling(window=dc_length).max()
        lower  = low.rolling(window=dc_length).min()
        middle = (upper + lower) / 2

        mid_now  = middle.iloc[-1]
        mid_prev = middle.iloc[-(slope_bars + 1)]

        if pd.isna(mid_now) or pd.isna(mid_prev) or mid_prev == 0:
            return empty

        slope     = (mid_now - mid_prev) / slope_bars          # price units / bar
        slope_pct = (slope / mid_prev) * 100                   # % per bar

        if abs(slope_pct) < 0.05:
            direction = "flat"
        elif slope_pct > 0:
            direction = "rising"
        else:
            direction = "falling"

        return {
            "slope":           _safe(slope),
            "slope_pct":       _safe(slope_pct),
            "slope_direction": direction,
        }
    except Exception as e:
        logger.warning(f"Donchian Slope calculation error: {e}")
        return empty


def _calc_candle_wick(
    open_:  pd.Series,
    high:   pd.Series,
    low:    pd.Series,
    close:  pd.Series,
) -> dict:
    """
    Candle Wick Size Analysis for the most recent candle.

    Definitions
    -----------
    candle_range  = high - low  (total candle length)
    body          = abs(close - open)
    body_top      = max(open, close)
    body_bottom   = min(open, close)
    upper_wick    = high - body_top
    lower_wick    = body_bottom - low

    Ratios (each expressed as % of candle_range so they sum to ~100 %)
    -------------------------------------------------------------------
    upper_wick_pct  = upper_wick / candle_range * 100
    lower_wick_pct  = lower_wick / candle_range * 100
    body_pct        = body       / candle_range * 100

    candle_type     : "bullish"  close > open
                      "bearish"  close < open
                      "doji"     body < 5 % of range

    Special pattern flags  (each True/False)
    ----------------------------------------
    is_hammer       : lower_wick >= 2× body AND upper_wick <= 0.1× range
                      AND body_pct <= 35 % — bullish reversal signal
    is_shooting_star: upper_wick >= 2× body AND lower_wick <= 0.1× range
                      AND body_pct <= 35 % — bearish reversal signal
    is_doji         : body < 5 % of range — indecision
    is_pin_bar      : either hammer or shooting star
    """
    empty = {
        "candle_range":    None,
        "body":            None,
        "upper_wick":      None,
        "lower_wick":      None,
        "upper_wick_pct":  None,
        "lower_wick_pct":  None,
        "body_pct":        None,
        "candle_type":     None,
        "is_hammer":       None,
        "is_shooting_star": None,
        "is_doji":         None,
        "is_pin_bar":      None,
    }
    if len(close) < 1:
        return empty
    try:
        o = float(open_.iloc[-1])
        h = float(high.iloc[-1])
        l = float(low.iloc[-1])
        c = float(close.iloc[-1])

        candle_range = h - l
        if candle_range == 0:
            # Zero-range candle (e.g. halted trading) — return zeros not None
            return {
                "candle_range":     0.0,
                "body":             0.0,
                "upper_wick":       0.0,
                "lower_wick":       0.0,
                "upper_wick_pct":   0.0,
                "lower_wick_pct":   0.0,
                "body_pct":         0.0,
                "candle_type":      "doji",
                "is_hammer":        False,
                "is_shooting_star": False,
                "is_doji":          True,
                "is_pin_bar":       False,
            }

        body        = abs(c - o)
        body_top    = max(o, c)
        body_bottom = min(o, c)
        upper_wick  = h - body_top
        lower_wick  = body_bottom - l

        upper_wick_pct = round(upper_wick  / candle_range * 100, 2)
        lower_wick_pct = round(lower_wick  / candle_range * 100, 2)
        body_pct       = round(body        / candle_range * 100, 2)

        # Candle type
        if body < candle_range * 0.05:
            candle_type = "doji"
        elif c > o:
            candle_type = "bullish"
        else:
            candle_type = "bearish"

        # Pattern flags
        is_doji         = body_pct < 5.0
        is_hammer       = (
            lower_wick  >= 2.0 * body         and
            upper_wick  <= 0.1 * candle_range  and
            body_pct    <= 35.0
        )
        is_shooting_star = (
            upper_wick  >= 2.0 * body         and
            lower_wick  <= 0.1 * candle_range  and
            body_pct    <= 35.0
        )
        is_pin_bar = is_hammer or is_shooting_star

        return {
            "candle_range":     _safe(candle_range),
            "body":             _safe(body),
            "upper_wick":       _safe(upper_wick),
            "lower_wick":       _safe(lower_wick),
            "upper_wick_pct":   upper_wick_pct,
            "lower_wick_pct":   lower_wick_pct,
            "body_pct":         body_pct,
            "candle_type":      candle_type,
            "is_hammer":        is_hammer,
            "is_shooting_star": is_shooting_star,
            "is_doji":          is_doji,
            "is_pin_bar":       is_pin_bar,
        }
    except Exception as e:
        logger.warning(f"Candle Wick calculation error: {e}")
        return empty


def _calc_obv(
    close:      pd.Series,
    volume:     pd.Series,
    sma_length: int = 20,
) -> dict:
    empty = {"obv": None, "obv_sma": None, "obv_trend": None}
    if len(close) < 2 or len(volume) < 2:
        return empty
    try:
        direction  = np.sign(close.diff()).fillna(0)
        obv_series = (direction * volume).cumsum()
        obv_latest = _safe(obv_series.iloc[-1])

        obv_sma   = None
        obv_trend = "neutral"
        if len(obv_series.dropna()) >= sma_length:
            sma_val   = _safe(obv_series.rolling(window=sma_length).mean().iloc[-1])
            obv_sma   = sma_val
            if obv_latest is not None and sma_val is not None:
                obv_trend = "bullish" if obv_latest > sma_val else "bearish"

        return {"obv": obv_latest, "obv_sma": obv_sma, "obv_trend": obv_trend}
    except Exception as e:
        logger.warning(f"OBV calculation error: {e}")
        return empty


def _calc_volume(
    volume:     pd.Series,
    sma_length: int = 20,
) -> dict:
    empty = {
        "volume_latest": None, "volume_sma": None,
        "volume_ratio":  None, "volume_trend": None,
    }
    if volume is None or volume.empty:
        return empty
    try:
        vol_latest = _safe(volume.iloc[-1])

        if len(volume.dropna()) >= sma_length:
            sma_val = _safe(volume.rolling(window=sma_length).mean().iloc[-1])
            ratio   = _safe(vol_latest / sma_val) if sma_val and sma_val > 0 else None

            if ratio is None:
                trend = "insufficient_data"
            elif ratio >= 1.5:
                trend = "above_average"
            elif ratio >= 0.75:
                trend = "average"
            else:
                trend = "below_average"

            return {
                "volume_latest": vol_latest, "volume_sma": sma_val,
                "volume_ratio":  ratio,      "volume_trend": trend,
            }
        return {
            "volume_latest": vol_latest, "volume_sma": None,
            "volume_ratio":  None,       "volume_trend": "insufficient_data",
        }
    except Exception as e:
        logger.warning(f"Volume calculation error: {e}")
        return empty


def _calc_delivery(delivery_pct: Optional[float] = None) -> dict:
    return {
        "delivery_pct": _safe(delivery_pct),
        "source_note": (
            None if delivery_pct is not None
            else "Requires NSE/BSE Bhavcopy — not available from current data providers"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main Class
# ─────────────────────────────────────────────────────────────────────────────

class TechnicalAnalysisHelper:
    """
    Unified OHLCV + Technical Analysis fetcher for Indian stocks.

    Fallback chain:
        yfinance (NSE) → Stooq → Twelve Data → Tiingo → yfinance (BSE)

    All configuration loaded from .env.  Single public method:
        get_technical_analysis(ticker_name, ...)
    """

    _EXCHANGE_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}

    def __init__(self):
        # ── API keys ──────────────────────────────────────────────────────────
        self.__td_key     = os.getenv("TWELVE_DATA_API_KEY",   "").strip()
        self.__tiingo_key = os.getenv("TIINGO_API_KEY",        "").strip()

        # ── Behaviour ─────────────────────────────────────────────────────────
        self.__exchange    = os.getenv("PREFERRED_EXCHANGE",    "NSE").upper().strip()
        self.__retry_delay = float(os.getenv("PROVIDER_RETRY_DELAY", "1.0"))

        # ── HTTP timeout / retry params ───────────────────────────────────────
        self.__http_connect_timeout = float(os.getenv("HTTP_CONNECT_TIMEOUT", "10.0"))
        self.__http_read_timeout    = float(os.getenv("HTTP_READ_TIMEOUT",    "60.0"))
        self.__http_max_retries     = int(os.getenv("HTTP_MAX_RETRIES",       "3"))
        self.__http_backoff         = float(os.getenv("HTTP_BACKOFF",         "5.0"))

        # ── RSI params ────────────────────────────────────────────────────────
        self.__rsi_length     = int(os.getenv("RSI_LENGTH",     "14"))
        self.__rsi_sma_length = int(os.getenv("RSI_SMA_LENGTH", "14"))
        self.__rsi_ema_length = int(os.getenv("RSI_EMA_LENGTH", "14"))

        # ── ADX params ────────────────────────────────────────────────────────
        self.__adx_length    = int(os.getenv("ADX_LENGTH",    "14"))
        self.__adx_smoothing = int(os.getenv("ADX_SMOOTHING", "14"))

        # ── PSAR params ───────────────────────────────────────────────────────
        self.__psar_af_start = float(os.getenv("PSAR_AF_START", "0.002"))
        self.__psar_af_step  = float(os.getenv("PSAR_AF_STEP",  "0.002"))
        self.__psar_af_max   = float(os.getenv("PSAR_AF_MAX",   "0.5"))

        # ── SuperTrend params ─────────────────────────────────────────────────
        self.__st_period     = int(os.getenv("SUPERTREND_PERIOD",       "7"))
        self.__st_multiplier = float(os.getenv("SUPERTREND_MULTIPLIER", "3.0"))

        # ── Donchian params ───────────────────────────────────────────────────
        self.__donchian_length      = int(os.getenv("DONCHIAN_LENGTH",       "20"))
        self.__donchian_slope_bars  = int(os.getenv("DONCHIAN_SLOPE_BARS",   "5"))

        # ── OBV params ────────────────────────────────────────────────────────
        self.__obv_sma_length = int(os.getenv("OBV_SMA_LENGTH", "20"))

        # ── Volume params ─────────────────────────────────────────────────────
        self.__volume_sma_length = int(os.getenv("VOLUME_SMA_LENGTH", "20"))

        if not self.__td_key:
            logger.info("TWELVE_DATA_API_KEY not set — Twelve Data will be skipped")
        if not self.__tiingo_key:
            logger.info("TIINGO_API_KEY not set — Tiingo will be skipped")

    # =========================================================================
    # PUBLIC
    # =========================================================================

    def get_technical_analysis(
        self,
        ticker_name:   str,
        period:        str  = "1y",
        interval:      str  = "1d",
        as_dict:       bool = False,
        force_refresh: bool = False,
    ):
        base, yf_ticker = self.__normalise(ticker_name)

        df, source = self.__fetch_with_fallback(base, yf_ticker, period, interval)
        exchange_label = "BSE" if ".BO" in yf_ticker else "NSE"

        if df is None:
            result = self.__build_error_response(
                base, exchange_label, period, interval,
                error=f"All data providers failed for '{base}'"
            )
            return result if as_dict else json.dumps(result, indent=2)

        indicators = self.__compute_indicators(df)

        result = {
            "ticker":        base,
            "exchange":      exchange_label,
            "currency":      "INR",
            "data_source":   source,
            "as_of":         df.index[-1].strftime("%Y-%m-%d"),
            "current_price": _safe(df["close"].iloc[-1]),
            "period":        period,
            "interval":      interval,
            "indicators":    indicators,
            "error":         None,
        }

        logger.info(f"✓ Technical analysis complete for {base} via {source}")
        return result if as_dict else json.dumps(result, indent=2)

    def clear_cache(self):
        # In-memory cache removed. Disk cache handled by orchestrator.
        logger.info("TechnicalAnalysisHelper cache cleared")

    # =========================================================================
    # PRIVATE — ticker normalisation
    # =========================================================================

    def __normalise(self, ticker: str) -> tuple[str, str]:
        ticker = ticker.upper().strip()
        if ticker.endswith(".NS"):
            return ticker[:-3], ticker
        if ticker.endswith(".BO") or ticker.endswith(".BSE"):
            base = ticker.split(".")[0]
            return base, f"{base}.BO"
        suffix = self._EXCHANGE_SUFFIX.get(self.__exchange, ".NS")
        return ticker, f"{ticker}{suffix}"

    # =========================================================================
    # PRIVATE — data fetching with fallback chain
    # =========================================================================

    def __fetch_with_fallback(
        self, base: str, yf_ticker: str, period: str, interval: str
    ) -> tuple[Optional[pd.DataFrame], str]:
        providers = [
            ("yfinance_nse", self.__try_yfinance),
            ("stooq",        self.__try_stooq),
            ("twelve_data",  self.__try_twelve_data),
            ("tiingo",       self.__try_tiingo),
            ("yfinance_bse", self.__try_yfinance_bse),
        ]
        for name, fn in providers:
            try:
                logger.info(f"[{base}] Attempting provider: {name}")
                df = fn(base, yf_ticker, period, interval)
                logger.info(f"[{base}] ✓ {name} succeeded — {len(df)} rows")
                return df, name
            except Exception as e:
                logger.warning(f"[{base}] ✗ {name} failed: {e}")
                time.sleep(self.__retry_delay)
        return None, "none"

    def __try_yfinance(self, base, yf_ticker, period, interval):
        return _fetch_yfinance(yf_ticker, period, interval)

    def __try_stooq(self, base, yf_ticker, period, interval):
        if interval not in ("1d", "1wk", "1mo"):
            raise ValueError(f"Stooq skipped — intraday interval '{interval}' not supported")
        return _fetch_stooq(base, period)

    def __try_twelve_data(self, base, yf_ticker, period, interval):
        return _fetch_twelve_data(
            base, yf_ticker, period, interval, self.__td_key,
            connect_timeout=self.__http_connect_timeout,
            read_timeout=self.__http_read_timeout,
            max_retries=self.__http_max_retries,
            backoff=self.__http_backoff,
        )

    def __try_tiingo(self, base, yf_ticker, period, interval):
        if interval not in ("1d", "1wk", "1mo"):
            raise ValueError("Tiingo only supports daily/weekly/monthly intervals")
        return _fetch_tiingo(
            base, period, self.__tiingo_key,
            connect_timeout=self.__http_connect_timeout,
            read_timeout=self.__http_read_timeout,
            max_retries=self.__http_max_retries,
            backoff=self.__http_backoff,
        )

    def __try_yfinance_bse(self, base, yf_ticker, period, interval):
        return _fetch_yfinance_bse(base, period, interval)

    # =========================================================================
    # PRIVATE — indicator computation
    # =========================================================================

    def __compute_indicators(self, df: pd.DataFrame) -> dict:
        high   = df["high"]
        low    = df["low"]
        close  = df["close"]
        open_  = df["open"]
        volume = df["volume"]

        return {
            "sma": {
                "sma_20": _calc_sma(close, 20),
                "sma_30": _calc_sma(close, 30),
                "sma_50": _calc_sma(close, 50),
            },
            "ema": {
                "ema_20": _calc_ema(close, 20),
                "ema_30": _calc_ema(close, 30),
                "ema_50": _calc_ema(close, 50),
            },
            "rsi": _calc_rsi_full(
                close,
                rsi_length=self.__rsi_length,
                sma_length=self.__rsi_sma_length,
                ema_length=self.__rsi_ema_length,
            ),
            "adx": _calc_adx(
                high, low, close,
                adx_length=self.__adx_length,
                adx_smoothing=self.__adx_smoothing,
            ),
            "psar": _calc_psar(
                high, low, close,
                af_start=self.__psar_af_start,
                af_step=self.__psar_af_step,
                af_max=self.__psar_af_max,
            ),
            "supertrend": _calc_supertrend(
                high, low, close,
                period=self.__st_period,
                multiplier=self.__st_multiplier,
            ),
            "donchian": _calc_donchian(
                high, low,
                length=self.__donchian_length,
            ),
            "donchian_slope": _calc_donchian_slope(
                high, low,
                dc_length=self.__donchian_length,
                slope_bars=self.__donchian_slope_bars,
            ),
            "candle_wick": _calc_candle_wick(open_, high, low, close),
            "obv": _calc_obv(
                close, volume,
                sma_length=self.__obv_sma_length,
            ),
            "volume": _calc_volume(
                volume,
                sma_length=self.__volume_sma_length,
            ),
            "delivery": _calc_delivery(),
        }

    # =========================================================================
    # PRIVATE — response builders
    # =========================================================================

    def __build_error_response(
        self, ticker: str, exchange: str, period: str, interval: str, error: str
    ) -> dict:
        return {
            "ticker":        ticker,
            "exchange":      exchange,
            "currency":      "INR",
            "data_source":   "none",
            "as_of":         None,
            "current_price": None,
            "period":        period,
            "interval":      interval,
            "indicators": {
                "sma":            {"sma_20": None, "sma_30": None, "sma_50": None},
                "ema":            {"ema_20": None, "ema_30": None, "ema_50": None},
                "rsi":            {"rsi": None, "rsi_sma": None, "rsi_ema": None},
                "adx":            {"adx": None, "di_plus": None, "di_minus": None},
                "psar":           {"psar": None, "psar_trend": None},
                "supertrend":     {"supertrend": None, "supertrend_trend": None},
                "donchian":       {"upper": None, "middle": None, "lower": None},
                "donchian_slope": {"slope": None, "slope_pct": None, "slope_direction": None},
                "candle_wick": {
                    "candle_range": None, "body": None,
                    "upper_wick": None,   "lower_wick": None,
                    "upper_wick_pct": None, "lower_wick_pct": None, "body_pct": None,
                    "candle_type": None,
                    "is_hammer": None, "is_shooting_star": None,
                    "is_doji": None,   "is_pin_bar": None,
                },
                "obv":            {"obv": None, "obv_sma": None, "obv_trend": None},
                "volume":         {"volume_latest": None, "volume_sma": None, "volume_ratio": None, "volume_trend": None},
                "delivery":       {"delivery_pct": None, "source_note": "Requires NSE/BSE Bhavcopy — not available from current data providers"},
            },
            "error": error,
        }