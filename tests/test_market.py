"""Tests for market analysis, technical indicators, and portfolio management with mocked API responses."""

import pytest
import pandas as pd
from unittest.mock import patch
from finance.indicators import parse_time_series_daily, analyze_market_data, calculate_rsi, calculate_sma
from finance.portfolio import add_position, calculate_portfolio_metrics
from finance.alpha_vantage import query_alpha_vantage


@pytest.fixture
def sample_av_response():
    # Generate 50 days of dummy price data for testing indicators
    dates = pd.date_range(end=pd.Timestamp.today(), periods=50, freq="B")
    ts_data = {}
    base_price = 400.0
    for i, d in enumerate(dates):
        price = base_price + (i * 0.5)
        date_str = d.strftime("%Y-%m-%d")
        ts_data[date_str] = {
            "1. open": str(price - 1),
            "2. high": str(price + 2),
            "3. low": str(price - 2),
            "4. close": str(price),
            "5. adjusted close": str(price),
            "6. volume": "1000000",
            "7. dividend amount": "0.0000",
            "8. split coefficient": "1.0",
        }
    return {"Time Series (Daily)": ts_data}


def test_parse_and_analyze(sample_av_response):
    df = parse_time_series_daily(sample_av_response)
    assert not df.empty
    assert "adjusted_close" in df.columns

    metrics = analyze_market_data(df)
    assert "close" in metrics
    assert "rsi_14" in metrics
    assert "sma_20" in metrics
    assert metrics["trend"] in ["Bullish", "Strong Bullish", "Bearish", "Strong Bearish", "Neutral"]


def test_portfolio_tracking(tmp_path):
    db = tmp_path / "portfolio.json"
    pos = add_position("SPY", 10.0, 400.0, db_path=db)
    assert pos["symbol"] == "SPY"
    assert pos["shares"] == 10.0
    assert pos["cost_basis"] == 400.0

    current_prices = {"SPY": 420.0}
    metrics = calculate_portfolio_metrics([pos], current_prices)
    assert metrics["total_cost"] == 4000.0
    assert metrics["total_value"] == 4200.0
    assert metrics["total_pnl"] == 200.0
    assert metrics["total_pnl_pct"] == 5.0


def test_portfolio_missing_price_raises_error():
    positions = [{"symbol": "DIA", "shares": 5.0, "cost_basis": 350.0}]
    current_prices = {}  # Missing DIA price
    with pytest.raises(ValueError, match="Missing current price"):
        calculate_portfolio_metrics(positions, current_prices)


@patch("finance.alpha_vantage.requests.get")
def test_alpha_vantage_caching_and_error_handling(mock_get, tmp_path):
    import os
    os.environ["ALPHA_VANTAGE_API_KEY"] = "TEST_KEY"
    cache_db = tmp_path / "test_cache.db"

    # Mock Alpha Vantage error response
    class MockResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {"Error Message": "Invalid API call."}

    mock_get.return_value = MockResponse()

    params = {"function": "GLOBAL_QUOTE", "symbol": "INVALID"}
    with pytest.raises(ValueError, match="Alpha Vantage API Error"):
        query_alpha_vantage(params, db_path=cache_db)


@patch("finance.alpha_vantage.requests.get")
def test_alpha_vantage_information_notice_not_cached(mock_get, tmp_path):
    import os
    os.environ["ALPHA_VANTAGE_API_KEY"] = "TEST_KEY"
    cache_db = tmp_path / "test_cache.db"

    class MockResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {"Information": "This is a premium endpoint. Please subscribe."}

    mock_get.return_value = MockResponse()

    params = {"function": "TIME_SERIES_DAILY", "symbol": "SPY"}
    with pytest.raises(ValueError, match="Premium Notice"):
        query_alpha_vantage(params, db_path=cache_db)

    # No cache entry should have been written for the failed request
    assert not cache_db.exists()
