"""Tests for the forward paper-trading shadow ledger (no live capital)."""

import pytest
from finance import paper_trading as pt


def test_paper_buy_sell_mark(tmp_path):
    ledger = tmp_path / "shadow.json"

    fill = pt.paper_buy("AAPL", 150.0, 10.0, db_path=ledger)
    assert fill["action"] == "BUY"
    assert fill["symbol"] == "AAPL"
    assert fill["shares"] == 10.0

    assert pt.load_ledger(ledger)["cash"] == pytest.approx(100_000 - 1500.0)

    sell = pt.paper_sell("AAPL", 160.0, db_path=ledger)
    assert sell["action"] == "SELL"
    assert sell["shares"] == 10.0

    # After full sell, no AAPL position remains.
    assert pt.load_ledger(ledger)["positions"] == {}
    assert pt.load_ledger(ledger)["cash"] == pytest.approx(100_000 + 100.0)


def test_paper_position_cap(tmp_path):
    ledger = tmp_path / "shadow.json"
    # Buying a large amount should be capped at 25% of a 100k portfolio.
    pt.paper_buy("MSFT", 100.0, 1000.0, db_path=ledger)
    pos = pt.load_ledger(ledger)["positions"]["MSFT"]
    # 25% of 100k = 25k, at $100 = 250 shares max.
    assert pos["shares"] <= 250.0 + 1e-6


def test_paper_mark_to_market(tmp_path):
    ledger = tmp_path / "shadow.json"
    pt.paper_buy("TSLA", 200.0, 10.0, db_path=ledger)
    res = pt.paper_mark_to_market({"TSLA": 220.0}, db_path=ledger)
    assert res["positions"][0]["symbol"] == "TSLA"
    assert res["positions"][0]["pnl"] == pytest.approx(200.0)


def test_mark_to_market_missing_price_raises(tmp_path):
    ledger = tmp_path / "shadow.json"
    pt.paper_buy("NVDA", 100.0, 5.0, db_path=ledger)
    with pytest.raises(ValueError, match="Missing current price"):
        pt.paper_mark_to_market({}, db_path=ledger)
