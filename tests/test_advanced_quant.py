"""Tests for advanced optimization models (HRP, Black-Litterman, Kelly)."""

import pytest
import pandas as pd
import numpy as np
from finance.advanced_optimization import (
    hierarchical_risk_parity,
    black_litterman,
    kelly_criterion,
)


@pytest.fixture
def price_matrix():
    np.random.seed(42)
    dates = pd.date_range(end=pd.Timestamp.today(), periods=120, freq="B")
    a = 100 + np.cumsum(np.random.normal(0.05, 1.0, 120))
    b = 80 + np.cumsum(np.random.normal(0.03, 0.5, 120))
    c = 120 + np.cumsum(np.random.normal(0.0, 0.8, 120))
    return pd.DataFrame({"A": a, "B": b, "C": c}, index=dates)


def test_hrp_weights_sum_to_one(price_matrix):
    res = hierarchical_risk_parity(price_matrix)
    assert res["method"] == "hierarchical_risk_parity"
    assert set(res["tickers"]) == {"A", "B", "C"}
    assert set(res["weights"].keys()) == {"A", "B", "C"}
    total = sum(res["weights"].values())
    assert pytest.approx(total, 0.03) == 1.0
    assert all(w >= 0 for w in res["weights"].values())


def test_hrp_requires_two_assets():
    with pytest.raises(ValueError, match="at least two"):
        hierarchical_risk_parity(pd.DataFrame({"A": [1.0, 2.0, 3.0]}))


def test_black_litterman_weights(price_matrix):
    res = black_litterman(price_matrix, views={"A": 0.12})
    assert res["method"] == "black_litterman"
    assert "weights" in res
    assert "view_adjusted_returns" in res
    total = sum(res["weights"].values())
    assert pytest.approx(total, 0.03) == 1.0


def test_black_litterman_no_views(price_matrix):
    res = black_litterman(price_matrix)
    assert res["method"] == "black_litterman"
    assert sum(res["weights"].values()) == pytest.approx(1.0, abs=0.03)


def test_kelly_positive_edge():
    res = kelly_criterion(0.6, 0.2, 0.1)
    assert res["full_kelly_fraction"] == pytest.approx(0.4)
    assert res["half_kelly_fraction"] == pytest.approx(0.2)
    assert res["full_kelly_fraction"] > 0


def test_kelly_no_edge_note():
    res = kelly_criterion(0.4, 0.1, 0.2)
    assert res["full_kelly_fraction"] < 0
    assert "Negative Kelly" in res["note"]


def test_kelly_invalid_inputs():
    with pytest.raises(ValueError, match="win_rate"):
        kelly_criterion(1.5, 0.2, 0.1)
    with pytest.raises(ValueError, match="avg_win"):
        kelly_criterion(0.6, 0.0, 0.1)
