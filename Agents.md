# Finance Project: Agents & Rules Architecture

## Purpose
Track the US Stock Market (S&P 500 & Dow Jones) and individual stocks, perform technical and macro financial analysis, and maximize investments through quantitative models, optimization, and risk guardrails.

## Core Rules & Safety
1. **API Key Security:** Never hardcode API keys or pass them via command-line arguments (process `argv`). API keys must be read strictly from environment variables (`FRED_API_KEY`) or secure storage, and passed via environment inheritance.
2. **Rate Limit & Error Protection:** All external API responses (FRED) must be cached locally in SQLite with TTL to prevent quota exhaustion. Guard against HTTP 200 OK error payloads.
3. **Data Integrity & Validation:** Validate all fetched market data and reject malformed/missing data frames before running indicators or generating portfolio valuations.
4. **Offline Testing:** Unit tests (`pytest`) must mock all external API calls so test suites run fully offline without consuming API credits.
5. **Portfolio Safety:** Fail explicitly or emit prominent warnings rather than defaulting missing price data to zero during portfolio valuations.

## Modules & Architecture
- **Market Data (`stock_data.py`):** Fetches split/dividend-adjusted OHLCV from Yahoo Finance (yfinance). Primary and sole provider of market prices.
- **SQLite Cache (`cache.py`):** Generic TTL-based response cache used by FRED and newsfeed to avoid redundant network calls.
- **Market & Indicators Engine (`indicators.py`):** Calculates technical indicators (SMA, EMA, RSI, MACD, Volatility) and trend scores.
- **Portfolio Tracker & Optimizer (`portfolio.py`):** Tracks holdings, cost basis, performance, and risk metrics using modern portfolio theory.
- **CLI Interface (`cli.py`):** Unified command-line utility for market quotes, analysis, portfolio tracking, and memory management.
