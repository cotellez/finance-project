"""Tests for the 3 new financial pillars: Tax Lots, Dividends, and Rebalance Engine."""

import pytest
from unittest.mock import MagicMock, patch
from finance.tax_lots import (
    load_tax_lots,
    save_tax_lots,
    add_tax_lot,
    realize_tax_lots,
)
from finance.dividends import (
    fetch_symbol_dividend_info,
    analyze_portfolio_dividends,
)
from finance.rebalance import (
    calculate_portfolio_drift,
    generate_rebalance_orders,
)


@pytest.fixture
def tmp_tax_lots_db(tmp_path):
    return tmp_path / "tax_lots.json"


def test_tax_lot_add_and_load(tmp_tax_lots_db):
    lot = add_tax_lot("AAPL", 10.0, 150.0, "2026-01-15", fees=1.0, db_path=tmp_tax_lots_db)
    assert lot["symbol"] == "AAPL"
    assert lot["shares"] == 10.0
    assert lot["purchase_price"] == 150.0

    lots = load_tax_lots(tmp_tax_lots_db)
    assert len(lots) == 1
    assert lots[0]["symbol"] == "AAPL"


def test_tax_lot_fifo_realization(tmp_tax_lots_db):
    # Add two lots: one earlier at $100, one later at $120
    add_tax_lot("AAPL", 5.0, 100.0, "2026-01-10", db_path=tmp_tax_lots_db)
    add_tax_lot("AAPL", 5.0, 120.0, "2026-02-10", db_path=tmp_tax_lots_db)

    # Sell 6 shares at $150 using FIFO:
    # Lot 1 (5 sh @ $100 -> gain: 5 * 50 = $250)
    # Lot 2 (1 sh @ $120 -> gain: 1 * 30 = $30)
    # Total gain: $280
    res = realize_tax_lots("AAPL", 6.0, 150.0, method="FIFO", db_path=tmp_tax_lots_db)
    assert res["shares_sold"] == 6.0
    assert res["realized_gain_loss"] == 280.0
    assert len(res["lots_affected"]) == 2

    # Remaining lots should have 4 shares left in Lot 2
    remaining = load_tax_lots(tmp_tax_lots_db)
    assert len(remaining) == 1
    assert remaining[0]["shares"] == 4.0
    assert remaining[0]["purchase_price"] == 120.0


def test_tax_lot_lifo_realization(tmp_tax_lots_db):
    add_tax_lot("MSFT", 5.0, 200.0, "2026-01-10", db_path=tmp_tax_lots_db)
    add_tax_lot("MSFT", 5.0, 300.0, "2026-02-10", db_path=tmp_tax_lots_db)

    # Sell 5 shares at $250 using LIFO:
    # Depletes Lot 2 (5 sh @ $300 -> loss: 5 * -50 = -$250)
    res = realize_tax_lots("MSFT", 5.0, 250.0, method="LIFO", db_path=tmp_tax_lots_db)
    assert res["realized_gain_loss"] == -250.0

    remaining = load_tax_lots(tmp_tax_lots_db)
    assert len(remaining) == 1
    assert remaining[0]["purchase_price"] == 200.0


def test_tax_lot_oversell_error(tmp_tax_lots_db):
    add_tax_lot("NVDA", 2.0, 200.0, db_path=tmp_tax_lots_db)
    with pytest.raises(ValueError, match="Cannot sell 5.0 shares"):
        realize_tax_lots("NVDA", 5.0, 250.0, db_path=tmp_tax_lots_db)


@patch("finance.dividends.cache_response")
@patch("finance.dividends.get_cached_response", return_value=None)
def test_dividends_offline_analysis(mock_get_cached, mock_cache):
    info = {
        "dividendRate": 2.50,
        "dividendYield": 0.025,
        "exDividendDate": "2026-09-15",
        "payoutRatio": 0.45,
    }

    with patch("yfinance.Ticker") as mock_ticker:
        instance = MagicMock()
        instance.info = info
        mock_ticker.return_value = instance

        div_info = fetch_symbol_dividend_info("SCHD")
        assert div_info["symbol"] == "SCHD"
        assert div_info["dividend_rate"] == 2.50
        assert div_info["dividend_yield"] == 0.025

    with patch("yfinance.Tickers") as mock_tickers:
        instance = MagicMock()
        instance.info = info
        container = MagicMock()
        container.tickers = {"SCHD": instance}
        mock_tickers.return_value = container

        positions = [
            {"symbol": "SCHD", "shares": 10.0, "cost_basis": 100.0, "current_price": 100.0}
        ]
        res = analyze_portfolio_dividends(positions)
        assert res["total_annual_income"] == 25.0  # 10 * 2.50
        assert res["portfolio_yield_on_cost"] == 2.5
        assert res["monthly_estimated_income"] == round(25.0 / 12.0, 2)


def test_rebalance_drift_calculation():
    positions = [
        {"symbol": "SCHD", "shares": 50.0, "cost_basis": 100.0, "current_price": 100.0},  # $5,000 (50%)
        {"symbol": "NVDA", "shares": 50.0, "cost_basis": 100.0, "current_price": 100.0},  # $5,000 (50%)
    ]
    target_weights = {"SCHD": 0.60, "NVDA": 0.40}  # targets 60% and 40%

    drifts = calculate_portfolio_drift(positions, target_weights)
    drift_map = {d["symbol"]: d["drift_pct"] for d in drifts}

    assert drift_map["SCHD"] == -10.0  # 50% - 60% = -10%
    assert drift_map["NVDA"] == 10.0   # 50% - 40% = +10%


def test_rebalance_order_generation_with_caps():
    positions = [
        {"symbol": "SCHD", "shares": 50.0, "cost_basis": 100.0, "current_price": 100.0},  # $5,000
        {"symbol": "NVDA", "shares": 50.0, "cost_basis": 100.0, "current_price": 100.0},  # $5,000
    ]
    # Total portfolio is $10,000. Target NVDA is 50%, but single-stock cap is 25%.
    target_weights = {"SCHD": 0.50, "NVDA": 0.50}

    res = generate_rebalance_orders(
        positions, target_weights, available_cash=0.0, max_position_pct=25.0
    )
    # NVDA should be capped to 25% ($2,500), forcing a SELL of 25 shares
    nvda_order = next((o for o in res["orders"] if o["symbol"] == "NVDA"), None)
    assert nvda_order is not None
    assert nvda_order["action"] == "SELL"
    assert nvda_order["shares"] == 25
    assert any("Cap adjusted for NVDA" in w for w in res["warnings"])
