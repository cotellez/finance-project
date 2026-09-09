"""Tests for the sandbox winner/loser prediction watchlist (training-only)."""

import json

import pandas as pd
import pytest

from finance import watchlist as wl


def _df_prices(*prices):
    """Build a dataframe shaped like fetch_daily_with_fallback output."""
    import numpy as np

    idx = pd.date_range("2026-01-01", periods=len(prices), freq="B")
    return pd.DataFrame(
        {
            "open": [float(p) for p in prices],
            "high": [float(p) for p in prices],
            "low": [float(p) for p in prices],
            "close": [float(p) for p in prices],
            "adjusted_close": [float(p) for p in prices],
            "volume": [np.nan] * len(prices),
        },
        index=idx,
    )


def _mock_prices(monkeypatch, sym_price, spy_price):
    def _fetch(symbol, period="5d"):
        price = sym_price if symbol != "SPY" else spy_price
        return _df_prices(price, price, price)

    monkeypatch.setattr(wl, "fetch_daily_with_fallback", _fetch)


def test_add_prediction_winner(tmp_path, monkeypatch):
    db = tmp_path / "sandbox_predictions.json"
    _mock_prices(monkeypatch, sym_price=100.0, spy_price=500.0)

    pred = wl.add_prediction("aapl", "winner", "breakout above 50-day SMA", horizon_days=30, db_path=db)

    assert pred["symbol"] == "AAPL"
    assert pred["type"] == "winner"
    assert pred["hypothesis"] == "breakout above 50-day SMA"
    assert pred["horizon_days"] == 30
    assert pred["initial_price"] == pytest.approx(100.0)
    assert pred["initial_spy_price"] == pytest.approx(500.0)
    assert pred["status"] == "active"

    stored = wl.load_watchlist(db)
    assert len(stored) == 1
    assert stored[0]["id"] == pred["id"]


def test_add_prediction_invalid_type(tmp_path, monkeypatch):
    _mock_prices(monkeypatch, sym_price=100.0, spy_price=500.0)
    with pytest.raises(ValueError, match="Prediction type must be one of"):
        wl.add_prediction("AAPL", "hold", "bad type", db_path=tmp_path / "db.json")


def test_add_prediction_empty_hypothesis(tmp_path, monkeypatch):
    _mock_prices(monkeypatch, sym_price=100.0, spy_price=500.0)
    with pytest.raises(ValueError, match="Hypothesis must be a non-empty string"):
        wl.add_prediction("AAPL", "winner", "   ", db_path=tmp_path / "db.json")


def test_add_prediction_bad_horizon(tmp_path, monkeypatch):
    _mock_prices(monkeypatch, sym_price=100.0, spy_price=500.0)
    with pytest.raises(ValueError, match="Horizon days must be greater than zero"):
        wl.add_prediction("AAPL", "winner", "thesis", horizon_days=0, db_path=tmp_path / "db.json")


def test_add_prediction_missing_price_raises(tmp_path, monkeypatch):
    def _fetch(symbol, period="5d"):
        if symbol == "SPY":
            return _df_prices(500.0)
        return pd.DataFrame(columns=["open", "high", "low", "close", "adjusted_close", "volume"])

    monkeypatch.setattr(wl, "fetch_daily_with_fallback", _fetch)
    with pytest.raises(ValueError, match="Could not fetch initial price data"):
        wl.add_prediction("BAD", "winner", "thesis", db_path=tmp_path / "db.json")


def test_evaluate_winner_correct(tmp_path, monkeypatch):
    db = tmp_path / "db.json"
    _mock_prices(monkeypatch, sym_price=100.0, spy_price=500.0)
    wl.add_prediction("AAPL", "winner", "bullish thesis", horizon_days=30, db_path=db)

    # Stock goes up, SPY flat -> winner correct, positive relative return.
    _mock_prices(monkeypatch, sym_price=110.0, spy_price=500.0)
    results = wl.evaluate_watchlist(db)
    assert len(results) == 1
    r = results[0]
    assert r["is_correct"] is True
    assert r["price_change_pct"] == pytest.approx(10.0)
    assert r["relative_return_pct"] == pytest.approx(10.0)


def test_evaluate_loser_correct(tmp_path, monkeypatch):
    db = tmp_path / "db.json"
    _mock_prices(monkeypatch, sym_price=100.0, spy_price=500.0)
    wl.add_prediction("TSLA", "loser", "bearish thesis", horizon_days=30, db_path=db)

    _mock_prices(monkeypatch, sym_price=90.0, spy_price=510.0)
    results = wl.evaluate_watchlist(db)
    r = results[0]
    assert r["is_correct"] is True
    assert r["price_change_pct"] == pytest.approx(-10.0)
    assert r["relative_return_pct"] == pytest.approx(-12.0)


def test_evaluate_benchmark_relative_return(tmp_path, monkeypatch):
    db = tmp_path / "db.json"
    _mock_prices(monkeypatch, sym_price=100.0, spy_price=500.0)
    wl.add_prediction("MSFT", "winner", "relative-value thesis", horizon_days=30, db_path=db)

    # Stock up 5%, SPY up 10% -> correct on absolute but underperforms benchmark.
    _mock_prices(monkeypatch, sym_price=105.0, spy_price=550.0)
    results = wl.evaluate_watchlist(db)
    r = results[0]
    assert r["is_correct"] is True
    assert r["price_change_pct"] == pytest.approx(5.0)
    assert r["spy_change_pct"] == pytest.approx(10.0)
    assert r["relative_return_pct"] == pytest.approx(-5.0)


def test_load_watchlist_missing(tmp_path):
    assert wl.load_watchlist(tmp_path / "nope.json") == []


def test_load_watchlist_corrupted(tmp_path):
    db = tmp_path / "db.json"
    db.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupted"):
        wl.load_watchlist(db)


def test_save_watchlist_persists(tmp_path):
    db = tmp_path / "db.json"
    wl.save_watchlist([{"id": "1", "symbol": "AAPL"}], db)
    data = json.loads(db.read_text(encoding="utf-8"))
    assert data == [{"id": "1", "symbol": "AAPL"}]