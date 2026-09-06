"""Tests for market analysis, technical indicators, and portfolio management with mocked API responses."""

import pytest
import pandas as pd
from unittest.mock import patch
from finance.indicators import parse_time_series_daily, analyze_market_data, calculate_rsi, calculate_sma, calculate_clv
from finance.portfolio import add_position, calculate_portfolio_metrics
from finance.cache import cache_response, get_cached_response


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


def test_cache_roundtrip(tmp_path):
    cache_db = tmp_path / "test_cache.db"
    key = "test:endpoint:1"
    payload = {"foo": "bar", "n": 42}

    cache_response(key, payload, db_path=cache_db)
    cached = get_cached_response(key, ttl_hours=12, db_path=cache_db)

    assert cached == payload


def test_cache_ttl_expired(tmp_path):
    import sqlite3
    from datetime import datetime, timedelta
    cache_db = tmp_path / "test_cache.db"
    key = "test:endpoint:2"
    payload = {"foo": "bar"}

    cache_response(key, payload, db_path=cache_db)

    # Backdate the cache entry so it appears stale.
    conn = sqlite3.connect(cache_db)
    conn.execute(
        "UPDATE api_cache SET timestamp = ? WHERE endpoint_key = ?",
        ((datetime.now() - timedelta(hours=24)).isoformat(), key),
    )
    conn.commit()
    conn.close()

    cached = get_cached_response(key, ttl_hours=12, db_path=cache_db)
    assert cached is None


def test_cache_missing_key(tmp_path):
    cache_db = tmp_path / "test_cache.db"
    assert get_cached_response("nonexistent", db_path=cache_db) is None


def _clv_df():
    # 5 sessions: close-at-high (+1), close-at-low (-1), mid (+0), flat (NaN), and a normal day.
    return pd.DataFrame(
        {
            "high": [10.0, 10.0, 10.0, 10.0, 100.0],
            "low": [8.0, 8.0, 8.0, 10.0, 90.0],
            "close": [10.0, 8.0, 9.0, 10.0, 95.0],
        },
        index=pd.date_range("2026-09-01", periods=5),
    )


def test_calculate_clv_bounds():
    clv = calculate_clv(_clv_df())
    values = list(clv)
    assert values[0] == pytest.approx(1.0)
    assert values[1] == pytest.approx(0.0)
    assert values[2] == pytest.approx(0.5)
    assert pd.isna(values[3])  # flat session (high == low) -> NaN, never a misleading 0
    assert values[4] == pytest.approx(0.5)
    assert clv.isna().sum() == 1


def test_calculate_clv_range():
    rng = pd.date_range("2026-09-01", periods=20)
    df = pd.DataFrame(
        {
            "high": [100.0 + i for i in range(20)],
            "low": [90.0 + i for i in range(20)],
            "close": [95.0 + i for i in range(20)],
        },
        index=rng,
    )
    clv = calculate_clv(df)
    assert ((clv >= 0) & (clv <= 1)).all()


def test_analyze_market_data_includes_clv(sample_av_response):
    df = parse_time_series_daily(sample_av_response)
    metrics = analyze_market_data(df)
    assert "clv" in metrics
    assert metrics["clv"] is not None and 0 <= metrics["clv"] <= 1
