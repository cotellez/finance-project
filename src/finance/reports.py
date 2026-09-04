"""Automated market briefing and financial reporting engine."""

import pandas as pd
from finance.stock_data import fetch_daily
from finance.indicators import analyze_market_data
from finance.fred import get_latest_observation
from finance.portfolio import load_portfolio, calculate_portfolio_metrics
from finance.optimization import optimize_portfolio
from finance.sentiment import score_news_items
from finance.newsfeed import fetch_financial_news, detect_catalysts, score_news_feed
from finance.logging_setup import get_logger

logger = get_logger(__name__)


def _fetch_ticker_news_sentiment(symbol: str, max_items: int = 5) -> dict:
    """Fetch recent news for a ticker via yfinance and score sentiment.

    Returns sentiment summary dict or an error dict if news is unavailable.
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        news = ticker.news
        if not news:
            return {"symbol": symbol, "label": "neutral", "score": 0.0, "items": 0}

        # Normalize yfinance news shape into {title, summary} for sentiment scorer
        items = []
        for entry in news[:max_items]:
            content = entry.get("content", entry) if isinstance(entry, dict) else {}
            title = content.get("title", "") if isinstance(content, dict) else ""
            summary = content.get("summary", "") if isinstance(content, dict) else ""
            if title:
                items.append({"title": title, "summary": summary})

        if not items:
            return {"symbol": symbol, "label": "neutral", "score": 0.0, "items": 0}

        result = score_news_items(items)
        return {"symbol": symbol, **result}
    except Exception as e:
        logger.debug("Ticker news sentiment unavailable for %s: %s", symbol, e)
        return {"symbol": symbol, "label": "unavailable", "score": None, "items": 0, "error": str(e)}


def generate_market_briefing(watchlist: list = None, include_sentiment: bool = True) -> dict:
    """Generate a comprehensive automated market briefing report.

    Args:
        watchlist: List of ticker symbols to analyze (defaults to SPY, DIA, AAPL, MSFT, GOOGL).
        include_sentiment: Whether to include news sentiment and catalyst sections.
    """
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

    # 4. News & Sentiment (broad market + per-ticker)
    market_sentiment = None
    ticker_sentiments = []
    catalysts = None

    if include_sentiment:
        try:
            news_result = fetch_financial_news(sources=("cnbc", "marketwatch"), limit=40)
            if news_result.get("items"):
                market_sentiment = score_news_feed(news_result["items"])
                catalysts = detect_catalysts(news_result["items"])
            else:
                market_sentiment = {"label": "neutral", "score": 0.0, "items_scored": 0}
        except Exception as e:
            logger.debug("Broad market news sentiment unavailable: %s", e)
            market_sentiment = {"label": "unavailable", "score": None, "items_scored": 0, "error": str(e)}

        for symbol in watchlist:
            try:
                tsent = _fetch_ticker_news_sentiment(symbol)
                ticker_sentiments.append(tsent)
            except Exception:
                ticker_sentiments.append({"symbol": symbol, "label": "unavailable", "score": None, "items": 0})

    return {
        "market_analysis": market_reports,
        "macro_indicators": macro_reports,
        "portfolio_summary": portfolio_summary,
        "portfolio_optimization": optimization_result,
        "market_sentiment": market_sentiment,
        "ticker_sentiments": ticker_sentiments,
        "catalysts": catalysts,
    }
