"""Finance CLI package for US Stock Market tracking and investment analysis.

Public names are exposed lazily (PEP 562) so that importing a lightweight
submodule (e.g. ``finance.cache`` or the memory MCP server) does NOT trigger
the heavyweight chain of yfinance/pandas/numpy imports. This keeps MCP server
startup and CLI cold starts fast instead of paying a ~50s eager-import tax.
"""

import importlib

_LAZY_IMPORTS = {
    # market data
    "fetch_daily": ("finance.stock_data", "fetch_daily"),
    "fetch_daily_with_fallback": ("finance.stock_data", "fetch_daily_with_fallback"),
    # macro
    "get_latest_observation": ("finance.fred", "get_latest_observation"),
    # indicators
    "calculate_sma": ("finance.indicators", "calculate_sma"),
    "calculate_ema": ("finance.indicators", "calculate_ema"),
    "calculate_rsi": ("finance.indicators", "calculate_rsi"),
    "calculate_volatility": ("finance.indicators", "calculate_volatility"),
    "calculate_clv": ("finance.indicators", "calculate_clv"),
    "analyze_market_data": ("finance.indicators", "analyze_market_data"),
    # portfolio
    "add_position": ("finance.portfolio", "add_position"),
    "calculate_portfolio_metrics": ("finance.portfolio", "calculate_portfolio_metrics"),
    # optimization
    "optimize_portfolio": ("finance.optimization", "optimize_portfolio"),
    "hierarchical_risk_parity": ("finance.advanced_optimization", "hierarchical_risk_parity"),
    "black_litterman": ("finance.advanced_optimization", "black_litterman"),
    "kelly_criterion": ("finance.advanced_optimization", "kelly_criterion"),
    # backtesting
    "backtest_sma_crossover": ("finance.backtest", "backtest_sma_crossover"),
    # screening
    "score_stocks": ("finance.screener", "score_stocks"),
    # bias guards
    "assert_no_lookahead": ("finance.bias_guard", "assert_no_lookahead"),
    "shift_signal_to_position": ("finance.bias_guard", "shift_signal_to_position"),
    "point_in_time_universe": ("finance.bias_guard", "point_in_time_universe"),
    # sentiment
    "score_text": ("finance.sentiment", "score_text"),
    "score_news_items": ("finance.sentiment", "score_news_items"),
    "score_analyst_actions": ("finance.sentiment", "score_analyst_actions"),
    # risk guardrails
    "calculate_atr": ("finance.risk_guardrails", "calculate_atr"),
    "atr_trailing_stop": ("finance.risk_guardrails", "atr_trailing_stop"),
    "check_circuit_breakers": ("finance.risk_guardrails", "check_circuit_breakers"),
    "calculate_var": ("finance.risk_guardrails", "calculate_var"),
    "validate_position_size": ("finance.risk_guardrails", "validate_position_size"),
    "check_sentiment_veto": ("finance.risk_guardrails", "check_sentiment_veto"),
    "check_earnings_blackout": ("finance.risk_guardrails", "check_earnings_blackout"),
    "fetch_earnings_date": ("finance.risk_guardrails", "fetch_earnings_date"),
    "check_earnings_blackout_for_symbol": ("finance.risk_guardrails", "check_earnings_blackout_for_symbol"),
    # paper trading
    "paper_buy": ("finance.paper_trading", "paper_buy"),
    "paper_sell": ("finance.paper_trading", "paper_sell"),
    "paper_mark_to_market": ("finance.paper_trading", "paper_mark_to_market"),
    # valuation
    "price_to_earnings": ("finance.valuation", "price_to_earnings"),
    "forward_pe": ("finance.valuation", "forward_pe"),
    "earnings_yield": ("finance.valuation", "earnings_yield"),
    "peg_ratio": ("finance.valuation", "peg_ratio"),
    "valuation_score": ("finance.valuation", "valuation_score"),
    # news
    "fetch_rss_feed": ("finance.newsfeed", "fetch_rss_feed"),
    "fetch_financial_news": ("finance.newsfeed", "fetch_financial_news"),
    "score_news_feed": ("finance.newsfeed", "score_news_feed"),
    "detect_catalysts": ("finance.newsfeed", "detect_catalysts"),
}

__all__ = sorted(_LAZY_IMPORTS)


def __getattr__(name: str):
    """Resolve a public name on first access, importing only its module."""
    try:
        module_name, attr_name = _LAZY_IMPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY_IMPORTS))
