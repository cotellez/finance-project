"""Free stock market data source using yfinance (Yahoo Finance).

Provides split- and dividend-adjusted daily OHLCV data without a subscription.
Yahoo Finance's "Adj Close" is adjusted for splits and dividends, preserving
price continuity for backtests and technical analysis.

This is the recommended data provider for the CLI/analysis layer. The Alpha
Vantage MCP server remains available for natural-language agent access (its
free endpoints require no subscription).
"""

import yfinance as yf
import pandas as pd
from pathlib import Path
from finance.logging_setup import get_logger

logger = get_logger(__name__)

DEFAULT_PERIOD = "2y"
DEFAULT_INTERVAL = "1d"

COLUMN_MAPPING = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adjusted_close",
    "Volume": "volume",
}

REQUIRED_COLUMNS = ["open", "high", "low", "close", "adjusted_close", "volume"]


def fetch_daily(symbol: str, period: str = DEFAULT_PERIOD, interval: str = DEFAULT_INTERVAL) -> pd.DataFrame:
    """Fetch daily OHLCV data for a symbol from Yahoo Finance (free).

    With auto_adjust=True the returned "Close" is already split- and
    dividend-adjusted, so "adjusted_close" is sourced from "Close".

    Args:
        symbol: Ticker symbol (e.g. "SPY").
        period: How far back to fetch (e.g. "1y", "2y", "5y", "max").
        interval: Data interval; default is "1d".

    Returns:
        A normalized DataFrame with DatetimeIndex (ascending) and columns
        open/high/low/close/adjusted_close/volume, or an empty DataFrame if
        no data is returned.

    Raises:
        ValueError: If the DataFrame is missing required columns or the symbol
            yields no rows.
    """
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval, auto_adjust=True)

    if df is None or df.empty:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    required_source = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required_source if c not in df.columns]
    if missing:
        raise ValueError(
            f"Unexpected Yahoo Finance response for {symbol}; missing columns: {missing}"
        )

    df = df.rename(columns=COLUMN_MAPPING)
    if "adjusted_close" not in df.columns:
        # auto_adjust=True: Close is already the split/dividend-adjusted close.
        df["adjusted_close"] = df["close"]

    df = df[[c for c in REQUIRED_COLUMNS if c in df.columns]].copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = df.sort_index()
    for col in ["open", "high", "low", "close", "adjusted_close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close", "adjusted_close"])
    return df


def _from_alpha_vantage_payload(data: dict, symbol: str) -> pd.DataFrame:
    """Convert an Alpha Vantage TIME_SERIES_DAILY payload to the normalized schema.

    Alpha Vantage's free daily endpoint is unadjusted, so adjusted_close is
    set equal to close (best-effort approximation for fallback scenarios).
    """
    time_series_key = None
    for k in data:
        if "Time Series" in k:
            time_series_key = k
            break
    if not time_series_key:
        raise ValueError(f"No time series data in Alpha Vantage payload for {symbol}.")

    rows = data[time_series_key]
    records = []
    for ts, vals in rows.items():
        if not isinstance(vals, dict):
            continue
        try:
            records.append(
                {
                    "index": pd.to_datetime(ts),
                    "open": float(vals["1. open"]),
                    "high": float(vals["2. high"]),
                    "low": float(vals["3. low"]),
                    "close": float(vals["4. close"]),
                    "adjusted_close": float(vals["4. close"]),
                    "volume": float(vals.get("5. volume", 0)),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue

    if not records:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    df = pd.DataFrame(records).set_index("index").sort_index()
    return df[REQUIRED_COLUMNS]


def fetch_daily_with_fallback(
    symbol: str,
    period: str = DEFAULT_PERIOD,
    interval: str = DEFAULT_INTERVAL,
    db_path: Path = None,
) -> pd.DataFrame:
    """Fetch daily OHLCV, falling back to Alpha Vantage free endpoints on failure.

    Primary source is yfinance (split/dividend-adjusted). If it returns no data,
    raises, or is unavailable, we attempt Alpha Vantage's free TIME_SERIES_DAILY
    endpoint (unadjusted; adjusted_close approximated as close). This provides a
    resilience layer against Yahoo outages and intermittent rate-limits.
    """
    try:
        df = fetch_daily(symbol, period=period, interval=interval)
        if not df.empty:
            return df
        logger.warning("yfinance returned no data for %s; trying Alpha Vantage fallback.", symbol)
    except Exception as e:
        logger.warning("yfinance failed for %s (%s); trying Alpha Vantage fallback.", symbol, e)

    if interval != "1d":
        # Alpha Vantage free fallback only supports daily granularity.
        logger.warning(
            "Alpha Vantage fallback only supports daily interval, not '%s'. Returning empty.", interval
        )
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    try:
        from finance.alpha_vantage import query_alpha_vantage
        data = query_alpha_vantage(
            {"function": "TIME_SERIES_DAILY", "symbol": symbol.upper()},
            ttl_hours=24,
            db_path=db_path,
        )
        return _from_alpha_vantage_payload(data, symbol)
    except Exception as e:
        logger.warning("Alpha Vantage fallback failed for %s: %s", symbol, e)
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
