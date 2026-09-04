"""Finance CLI package for US Stock Market tracking and investment analysis."""

from finance.stock_data import fetch_daily, fetch_daily_with_fallback
from finance.fred import get_latest_observation
from finance.indicators import (
    calculate_sma,
    calculate_ema,
    calculate_rsi,
    calculate_volatility,
    analyze_market_data,
)
from finance.portfolio import add_position, calculate_portfolio_metrics
from finance.optimization import optimize_portfolio
from finance.advanced_optimization import (
    hierarchical_risk_parity,
    black_litterman,
    kelly_criterion,
)
from finance.backtest import backtest_sma_crossover
from finance.screener import score_stocks
from finance.bias_guard import assert_no_lookahead, shift_signal_to_position, point_in_time_universe
from finance.sentiment import score_text, score_news_items, score_analyst_actions
from finance.risk_guardrails import (
    calculate_atr,
    atr_trailing_stop,
    check_circuit_breakers,
    calculate_var,
    validate_position_size,
    check_sentiment_veto,
    check_earnings_blackout,
    fetch_earnings_date,
    check_earnings_blackout_for_symbol,
)
from finance.paper_trading import paper_buy, paper_sell, paper_mark_to_market
from finance.valuation import (
    price_to_earnings,
    forward_pe,
    earnings_yield,
    peg_ratio,
    valuation_score,
)
from finance.newsfeed import (
    fetch_rss_feed,
    fetch_financial_news,
    score_news_feed,
    detect_catalysts,
)
