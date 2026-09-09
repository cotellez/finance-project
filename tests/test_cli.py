"""Tests for finance CLI."""

import pytest
from finance.cli import add_transaction, get_summary, load_transactions


def test_add_income(tmp_path):
    db = tmp_path / "finance.json"
    tx = add_transaction("income", 1000.0, "Salary", "2026-09-01", db_path=db)
    assert tx["amount"] == 1000.0
    assert tx["type"] == "income"
    assert tx["category"] == "Salary"

    txs = load_transactions(db)
    assert len(txs) == 1


def test_add_expense(tmp_path):
    db = tmp_path / "finance.json"
    add_transaction("income", 500.0, "Freelance", "2026-09-01", db_path=db)
    add_transaction("expense", 50.0, "Groceries", "2026-09-02", db_path=db)

    summary = get_summary(db)
    assert summary["total_income"] == 500.0
    assert summary["total_expense"] == 50.0
    assert summary["balance"] == 450.0
    assert summary["count"] == 2


def test_invalid_amount(tmp_path):
    db = tmp_path / "finance.json"
    with pytest.raises(ValueError):
        add_transaction("income", -10.0, "Bad", db_path=db)
    with pytest.raises(ValueError):
        add_transaction("expense", 0.0, "Zero", db_path=db)


def test_invalid_type(tmp_path):
    db = tmp_path / "finance.json"
    with pytest.raises(ValueError):
        add_transaction("transfer", 100.0, "Invalid", db_path=db)


# --- Sandbox watchlist CLI ---

class _Args:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_watchlist_handlers_roundtrip(tmp_path, monkeypatch, capsys):
    import pandas as pd
    from finance.cli import (
        handle_watchlist_add,
        handle_watchlist_list,
        handle_watchlist_evaluate,
    )
    from finance import watchlist as wl

    def _df(price):
        return pd.DataFrame(
            {
                "open": [price, price, price],
                "high": [price, price, price],
                "low": [price, price, price],
                "close": [price, price, price],
                "adjusted_close": [price, price, price],
                "volume": [0.0, 0.0, 0.0],
            }
        )

    prices = {"AAPL": 100.0, "SPY": 500.0}

    def _fetch(symbol, period="5d"):
        return _df(prices[symbol])

    monkeypatch.setattr(wl, "fetch_daily_with_fallback", _fetch)

    db = tmp_path / "sandbox_predictions.json"

    args = _Args(symbol="AAPL", type="winner", hypothesis="breakout thesis", horizon=30)
    assert handle_watchlist_add(args, db_path=db) == 0

    out = capsys.readouterr().out
    assert "SANDBOX / TRAINING PREDICTION ONLY" in out
    assert "Logged WINNER prediction for AAPL" in out

    assert handle_watchlist_list(_Args(), db_path=db) == 0
    out = capsys.readouterr().out
    assert "AAPL" in out
    assert "SANDBOX / TRAINING PREDICTION ONLY" in out

    prices["AAPL"] = 110.0  # stock up, winner on track
    assert handle_watchlist_evaluate(_Args(), db_path=db) == 0
    out = capsys.readouterr().out
    assert "CORRECT" in out
    assert "SANDBOX / TRAINING PREDICTION ONLY" in out
