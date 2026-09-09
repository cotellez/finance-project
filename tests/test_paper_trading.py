"""Tests for the forward paper-trading shadow ledger (no live capital)."""

import pytest
from finance import paper_trading as pt


def test_default_ledger_starts_at_2000(tmp_path):
    ledger = tmp_path / "shadow.json"
    assert pt.load_ledger(ledger) == {"cash": 2000.0, "positions": {}, "fills": []}


def test_initialize_ledger_custom_capital(tmp_path):
    ledger = tmp_path / "shadow.json"
    res = pt.initialize_ledger(5000.0, db_path=ledger)
    assert res["cash"] == 5000.0
    assert pt.load_ledger(ledger)["cash"] == 5000.0


def test_initialize_ledger_invalid_capital(tmp_path):
    ledger = tmp_path / "shadow.json"
    with pytest.raises(ValueError, match="Starting capital must be"):
        pt.initialize_ledger(-100.0, db_path=ledger)


def test_paper_buy_sell_mark(tmp_path):
    ledger = tmp_path / "shadow.json"

    # Buying $1,500 of AAPL in a $2,000 account is capped at 25% ($500).
    fill = pt.paper_buy("AAPL", 150.0, 10.0, db_path=ledger)
    assert fill["action"] == "BUY"
    assert fill["symbol"] == "AAPL"
    assert fill["shares"] == pytest.approx(round(500.0 / 150.0, 4))

    assert pt.load_ledger(ledger)["cash"] == pytest.approx(2000.0 - 500.0)

    sell = pt.paper_sell("AAPL", 160.0, db_path=ledger)
    assert sell["action"] == "SELL"
    assert sell["shares"] == pytest.approx(round(500.0 / 150.0, 4))

    # After full sell, no AAPL position remains and the account made (10/150)*500.
    assert pt.load_ledger(ledger)["positions"] == {}
    assert pt.load_ledger(ledger)["cash"] == pytest.approx(2000.0 + (10.0 / 150.0) * 500.0)


def test_paper_position_cap(tmp_path):
    ledger = tmp_path / "shadow.json"
    # Buying $100,000 of MSFT should be capped at 25% of a $2,000 portfolio.
    pt.paper_buy("MSFT", 100.0, 1000.0, db_path=ledger)
    pos = pt.load_ledger(ledger)["positions"]["MSFT"]
    # 25% of 2,000 = $500, at $100 = 5 shares max.
    assert pos["shares"] <= 5.0 + 1e-6


def test_paper_mark_to_market(tmp_path):
    ledger = tmp_path / "shadow.json"
    # $2,000 purchase of TSLA gets capped to $500 at $200 = 2.5 shares.
    pt.paper_buy("TSLA", 200.0, 10.0, db_path=ledger)
    res = pt.paper_mark_to_market({"TSLA": 220.0}, db_path=ledger)
    assert res["positions"][0]["symbol"] == "TSLA"
    assert res["positions"][0]["pnl"] == pytest.approx(2.5 * 20.0)


def test_mark_to_market_missing_price_raises(tmp_path):
    ledger = tmp_path / "shadow.json"
    pt.paper_buy("NVDA", 100.0, 5.0, db_path=ledger)
    with pytest.raises(ValueError, match="Missing current price"):
        pt.paper_mark_to_market({}, db_path=ledger)
