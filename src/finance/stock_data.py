"""Free stock market data source using yfinance (Yahoo Finance).

Provides split- and dividend-adjusted daily OHLCV data without a subscription.
Yahoo Finance's "Adj Close" is adjusted for splits and dividends, preserving
price continuity for backtests and technical analysis.
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


def fetch_daily_with_fallback(
    symbol: str,
    period: str = DEFAULT_PERIOD,
    interval: str = DEFAULT_INTERVAL,
    db_path: Path = None,
) -> pd.DataFrame:
    """Fetch daily OHLCV data.

    yfinance is the sole data provider. Returns an empty DataFrame if the
    source is unavailable or returns no data so callers can handle missing
    data explicitly rather than fail silently.
    """
    try:
        df = fetch_daily(symbol, period=period, interval=interval)
        if not df.empty:
            return df
        logger.warning("yfinance returned no data for %s.", symbol)
    except Exception as e:
        logger.warning("yfinance failed for %s (%s).", symbol, e)
    return pd.DataFrame(columns=REQUIRED_COLUMNS)
