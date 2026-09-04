"""Automated market briefing and financial reporting engine."""

import pandas as pd
from finance.stock_data import fetch_daily
from finance.indicators import analyze_market_data
from finance.fred import get_latest_observation
from finance.portfolio import load_portfolio, calculate_portfolio_metrics
from finance.optimization import optimize_portfolio


def generate_market_briefing(watchlist: list = None) -> dict:
    """Generate a comprehensive automated market briefing report."""
    if watchlist is None:
        watchlist = ["SPY", "DIA", "AAPL", "MSFT", "GOOGL"]

    # 1. Market analysis for watchlist
    market_reports = {}
    price_dfs = {}
    for symbol in watchlist:
        try:
            df = fetch_daily(symbol)
            analysis = analyze_market_data(df)
            market_reports[symbol] = analysis
            price_dfs[symbol] = df["adjusted_close"]
        except Exception as e:
            market_reports[symbol] = {"error": str(e)}

    # 2. Macro briefing (FRED)
    macro_reports = {}
    for series_id in ["FEDFUNDS", "DGS10", "CPIAUCSL", "UNRATE"]:
        try:
            obs = get_latest_observation(series_id)
            macro_reports[series_id] = obs
        except Exception as e:
            macro_reports[series_id] = {"error": str(e)}

    # 3. Portfolio & Optimization
    portfolio_positions = load_portfolio()
    portfolio_summary = None
    optimization_result = None

    if portfolio_positions:
        try:
            current_prices = {p["symbol"]: market_reports.get(p["symbol"], {}).get("close") for p in portfolio_positions}
            portfolio_summary = calculate_portfolio_metrics(portfolio_positions, current_prices)
        except Exception:
            pass

    if len(price_dfs) > 0:
        try:
            price_matrix = pd.DataFrame(price_dfs)
            optimization_result = optimize_portfolio(price_matrix)
        except Exception:
            pass

    return {
        "market_analysis": market_reports,
        "macro_indicators": macro_reports,
        "portfolio_summary": portfolio_summary,
        "portfolio_optimization": optimization_result,
    }
