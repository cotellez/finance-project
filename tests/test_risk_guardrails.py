"""Tests for hard risk guardrails / circuit breakers."""

import pytest
import pandas as pd
import numpy as np
from finance.risk_guardrails import (
    atr_trailing_stop,
    check_circuit_breakers,
    calculate_var,
    validate_position_size,
    calculate_atr,
)


@pytest.fixture
def ohlc_df():
    np.random.seed(7)
    dates = pd.date_range(end=pd.Timestamp.today(), periods=80, freq="B")
    close = 100 + np.cumsum(np.random.normal(0.05, 0.8, 80))
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "adjusted_close": close,
            "volume": [1_000_000] * 80,
        },
        index=dates,
    )


def test_calculate_atr_positive(ohlc_df):
    atr = calculate_atr(ohlc_df, window=14)
    assert atr.isna().sum() == 13  # first 13 values NaN
    assert (atr.dropna() > 0).all()


def test_atr_trailing_stop_ratchets(ohlc_df):
    out = atr_trailing_stop(ohlc_df, atr_multiple=3.0)
    assert "trailing_stop" in out.columns
    stop = out["trailing_stop"].dropna()
    # Trailing stop should never exceed the running high.
    assert (out["trailing_stop"].dropna() <= out["atr_high"].dropna()).all()


def test_atr_invalid_multiple(ohlc_df):
    with pytest.raises(ValueError, match="atr_multiple"):
        atr_trailing_stop(ohlc_df, atr_multiple=0.0)


def test_max_drawdown_detects_circuit_breaker():
    metrics = {"total_pnl_pct": -25.0, "total_value": 100_000, "positions": []}
    res = check_circuit_breakers(metrics, {"max_drawdown_pct": 20.0})
    assert res["halt"] is True
    assert any("MAX DRAWDOWN" in r for r in res["blocked_reasons"])


def test_no_breaker_when_within_limits():
    metrics = {"total_pnl_pct": -5.0, "total_value": 100_000, "positions": []}
    res = check_circuit_breakers(metrics, {"max_drawdown_pct": 20.0})
    assert res["halt"] is False


def test_position_concentration_breaker():
    metrics = {
        "total_pnl_pct": 2.0,
        "total_value": 100_000,
        "positions": [{"symbol": "AAPL", "current_value": 60_000}],
    }
    res = check_circuit_breakers(metrics, {"max_position_pct": 25.0})
    assert res["halt"] is True
    assert any("CONCENTRATION" in r for r in res["blocked_reasons"])


def test_calculate_var():
    returns = pd.Series(np.random.normal(0.001, 0.02, 500))
    var = calculate_var(returns, confidence=0.95)
    assert 0.0 <= var <= 0.1


def test_validate_position_size():
    # Cap at 25% of portfolio value.
    assert validate_position_size(50_000, 100_000, 25.0) == 25_000
    # Below cap is allowed as-is.
    assert validate_position_size(10_000, 100_000, 25.0) == 10_000


def test_check_sentiment_veto_severe_keyword():
    from finance.risk_guardrails import check_sentiment_veto
    news = [{"title": "Company faces SEC investigation over accounting fraud", "summary": "Shares plummet."}]
    res = check_sentiment_veto("AAPL", news)
    assert res["veto"] is True
    assert "CATALYST VETO" in res["reason"]


def test_check_sentiment_veto_normal():
    from finance.risk_guardrails import check_sentiment_veto
    news = [{"title": "Company beats earnings and raises guidance", "summary": "Strong growth."}]
    res = check_sentiment_veto("AAPL", news)
    assert res["veto"] is False


def test_check_earnings_blackout_active():
    from finance.risk_guardrails import check_earnings_blackout
    res = check_earnings_blackout("NVDA", earnings_date="2026-09-05", as_of_date="2026-09-02", blackout_days=5)
    assert res["in_blackout"] is True
    assert res["days_until_earnings"] == 3
    assert "EARNINGS BLACKOUT" in res["reason"]


def test_check_earnings_blackout_inactive():
    from finance.risk_guardrails import check_earnings_blackout
    res = check_earnings_blackout("NVDA", earnings_date="2026-09-20", as_of_date="2026-09-02", blackout_days=5)
    assert res["in_blackout"] is False
    assert res["days_until_earnings"] == 18
