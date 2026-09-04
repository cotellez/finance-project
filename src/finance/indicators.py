"""Technical indicators and market analysis engine."""

import pandas as pd
import numpy as np


def parse_time_series_daily(data: dict) -> pd.DataFrame:
    """Parse Alpha Vantage TIME_SERIES_DAILY_ADJUSTED JSON into a clean Pandas DataFrame."""
    time_series_key = "Time Series (Daily)"
    if time_series_key not in data:
        # Try fallback or check keys
        for k in data.keys():
            if "Time Series" in k:
                time_series_key = k
                break
        else:
            raise ValueError(f"Invalid Alpha Vantage response format. Keys found: {list(data.keys())}")

    ts_data = data[time_series_key]
    df = pd.DataFrame.from_dict(ts_data, orient="index")
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    # Rename columns to standard names
    col_mapping = {
        "1. open": "open",
        "2. high": "high",
        "3. low": "low",
        "4. close": "close",
        "5. adjusted close": "adjusted_close",
        "6. volume": "volume",
        "7. dividend amount": "dividend",
        "8. split coefficient": "split_coefficient",
    }
    df = df.rename(columns=col_mapping)
    
    # Convert columns to numeric
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["close", "adjusted_close"])
    return df


def calculate_sma(df: pd.DataFrame, window: int = 20, price_col: str = "adjusted_close") -> pd.Series:
    """Calculate Simple Moving Average (SMA)."""
    return df[price_col].rolling(window=window).mean()


def calculate_ema(df: pd.DataFrame, window: int = 20, price_col: str = "adjusted_close") -> pd.Series:
    """Calculate Exponential Moving Average (EMA)."""
    return df[price_col].ewm(span=window, adjust=False).mean()


def calculate_rsi(df: pd.DataFrame, window: int = 14, price_col: str = "adjusted_close") -> pd.Series:
    """Calculate Relative Strength Index (RSI)."""
    delta = df[price_col].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(com=window - 1, min_periods=window).mean()
    avg_loss = loss.ewm(com=window - 1, min_periods=window).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_volatility(df: pd.DataFrame, window: int = 20, price_col: str = "adjusted_close") -> pd.Series:
    """Calculate annualized historical volatility based on log returns."""
    log_returns = np.log(df[price_col] / df[price_col].shift(1))
    return log_returns.rolling(window=window).std() * np.sqrt(252)


def analyze_market_data(df: pd.DataFrame) -> dict:
    """Perform comprehensive technical analysis on market time-series data."""
    if df.empty or len(df) < 30:
        raise ValueError("Insufficient data points for technical analysis (minimum 30 required).")

    df["sma_20"] = calculate_sma(df, 20)
    df["sma_50"] = calculate_sma(df, 50)
    df["sma_200"] = calculate_sma(df, 200) if len(df) >= 200 else calculate_sma(df, len(df))
    df["rsi_14"] = calculate_rsi(df, 14)
    df["volatility_20"] = calculate_volatility(df, 20)

    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    price_change = latest["adjusted_close"] - prev["adjusted_close"]
    price_change_pct = (price_change / prev["adjusted_close"]) * 100

    # Trend scoring
    close_price = latest["adjusted_close"]
    sma_50_val = latest["sma_50"]
    sma_200_val = latest["sma_200"]

    trend = "Neutral"
    if close_price > sma_50_val and sma_50_val > sma_200_val:
        trend = "Strong Bullish"
    elif close_price > sma_50_val:
        trend = "Bullish"
    elif close_price < sma_50_val and sma_50_val < sma_200_val:
        trend = "Strong Bearish"
    elif close_price < sma_50_val:
        trend = "Bearish"

    rsi_val = latest["rsi_14"]
    rsi_signal = "Neutral"
    if rsi_val > 70:
        rsi_signal = "Overbought"
    elif rsi_val < 30:
        rsi_signal = "Oversold"

    return {
        "date": str(df.index[-1].date()),
        "close": round(float(latest["adjusted_close"]), 2),
        "change": round(float(price_change), 2),
        "change_pct": round(float(price_change_pct), 2),
        "volume": int(latest["volume"]),
        "sma_20": round(float(latest["sma_20"]), 2) if not pd.isna(latest["sma_20"]) else None,
        "sma_50": round(float(latest["sma_50"]), 2) if not pd.isna(latest["sma_50"]) else None,
        "sma_200": round(float(latest["sma_200"]), 2) if not pd.isna(latest["sma_200"]) else None,
        "rsi_14": round(float(rsi_val), 2) if not pd.isna(rsi_val) else None,
        "rsi_signal": rsi_signal,
        "volatility_annualized": round(float(latest["volatility_20"]) * 100, 2) if not pd.isna(latest["volatility_20"]) else None,
        "trend": trend,
    }
