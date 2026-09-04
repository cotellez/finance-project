"""Tests for optimization, backtesting, screener, and automated reporting modules."""

import pytest
import pandas as pd
from finance.optimization import optimize_portfolio
from finance.backtest import backtest_sma_crossover
from finance.screener import score_stocks


@pytest.fixture
def sample_price_matrix():
    dates = pd.date_range(end=pd.Timestamp.today(), periods=100, freq="B")
    data_a = [100 + i * 0.2 for i in range(100)]
    data_b = [50 + i * 0.1 for i in range(100)]
    df = pd.DataFrame({"A": data_a, "B": data_b}, index=dates)
    return df


def test_optimize_portfolio(sample_price_matrix):
    res = optimize_portfolio(sample_price_matrix, risk_free_rate=0.03)
    assert "weights" in res
    assert "sharpe_ratio" in res
    assert len(res["weights"]) == 2
    # Weights should sum to 1.0
    total_weight = sum(res["weights"].values())
    assert pytest.approx(total_weight, 0.01) == 1.0


def test_backtest_sma_crossover(sample_price_matrix):
    res = backtest_sma_crossover(sample_price_matrix, fast_window=10, slow_window=30, price_col="A")
    assert "total_strategy_return_pct" in res
    assert "max_drawdown_pct" in res
    assert "sharpe_ratio" in res


def test_score_stocks(sample_price_matrix):
    stock_dict = {"A": sample_price_matrix[["A"]].rename(columns={"A": "adjusted_close"}),
                  "B": sample_price_matrix[["B"]].rename(columns={"B": "adjusted_close"})}
    scores = score_stocks(stock_dict)
    assert len(scores) == 2
    assert "ticker" in scores[0]
    assert "composite_score" in scores[0]
