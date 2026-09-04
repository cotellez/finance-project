"""Tests for the yfinance data source (mocked, offline)."""

import pytest
import pandas as pd
from unittest.mock import patch
from finance.stock_data import fetch_daily, fetch_daily_with_fallback, REQUIRED_COLUMNS


def _make_yf_df():
    dates = pd.date_range(end=pd.Timestamp.today(), periods=60, freq="B")
    return pd.DataFrame(
        {
            "Open": [400.0] * 60,
            "High": [402.0] * 60,
            "Low": [398.0] * 60,
            "Close": [401.0] * 60,
            "Volume": [1000000] * 60,
            "Dividends": [0.0] * 60,
            "Stock Splits": [0.0] * 60,
        },
        index=dates,
    )


@patch("finance.stock_data.yf")
def test_fetch_daily_returns_normalized_adjusted_df(mock_yf):
    df = _make_yf_df()
    mock_yf.Ticker.return_value.history.return_value = df

    result = fetch_daily("SPY")

    assert list(result.columns) == REQUIRED_COLUMNS
    assert len(result) == 60
    # auto_adjust=True: adjusted_close sourced from Close
    assert (result["adjusted_close"] == result["close"]).all()
    # Index ascending
    assert result.index.is_monotonic_increasing


@patch("finance.stock_data.yf")
def test_fetch_daily_empty_returns_empty_df(mock_yf):
    mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()

    result = fetch_daily("ZZZZ")

    assert result.empty
    assert list(result.columns) == REQUIRED_COLUMNS


@patch("finance.stock_data.yf")
def test_fetch_daily_missing_columns_raises(mock_yf):
    df = pd.DataFrame({"Open": [1.0], "Volume": [100]})  # missing Close/High/etc.
    mock_yf.Ticker.return_value.history.return_value = df

    with pytest.raises(ValueError, match="missing columns"):
        fetch_daily("SPY")


@patch("finance.stock_data.fetch_daily")
def test_fallback_returns_yfinance_when_available(mock_fetch):
    good = _make_yf_df()
    mock_fetch.return_value = good

    result = fetch_daily_with_fallback("SPY")
    assert len(result) == 60
    mock_fetch.assert_called_once()


@patch("finance.stock_data.fetch_daily")
def test_fallback_returns_empty_when_yfinance_empty(mock_fetch):
    # yfinance returns empty; no fallback provider, so return empty DataFrame.
    mock_fetch.return_value = pd.DataFrame(columns=REQUIRED_COLUMNS)

    result = fetch_daily_with_fallback("SPY")
    assert result.empty
    assert list(result.columns) == REQUIRED_COLUMNS
    mock_fetch.assert_called_once()


@patch("finance.stock_data.fetch_daily")
def test_fallback_returns_empty_when_yfinance_raises(mock_fetch):
    mock_fetch.side_effect = RuntimeError("network down")

    result = fetch_daily_with_fallback("SPY")
    assert result.empty
    assert list(result.columns) == REQUIRED_COLUMNS
