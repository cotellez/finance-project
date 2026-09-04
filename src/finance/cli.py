#!/usr/bin/env python3
"""Finance & US Stock Market CLI implementation."""

import argparse
import sys
from datetime import date
from pathlib import Path
from finance.memory import (
    DEFAULT_LONG_TERM_DB,
    DEFAULT_SHORT_TERM_DB,
    remember,
    recall,
    forget,
    push_context,
    clear_short_term_memory,
    get_short_term_memory,
    load_long_term_memory,
)
from finance.stock_data import fetch_daily
from finance.indicators import analyze_market_data
from finance.portfolio import (
    load_portfolio,
    add_position,
    calculate_portfolio_metrics,
)
from finance.fred import get_latest_observation
from finance.optimization import optimize_portfolio
from finance.backtest import backtest_sma_crossover
from finance.screener import score_stocks
from finance.reports import generate_market_briefing
import pandas as pd

DEFAULT_DB = Path("finance.json")


def load_transactions(db_path: Path = DEFAULT_DB) -> list:
    import json
    if not db_path.exists():
        return []
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []


def get_summary(db_path: Path = DEFAULT_DB) -> dict:
    txs = load_transactions(db_path)
    total_income = sum(t["amount"] for t in txs if t["type"] == "income")
    total_expense = sum(t["amount"] for t in txs if t["type"] == "expense")
    balance = total_income - total_expense
    return {
        "total_income": round(total_income, 2),
        "total_expense": round(total_expense, 2),
        "balance": round(balance, 2),
        "count": len(txs),
    }


def add_transaction(tx_type: str, amount: float, category: str, tx_date: str = None, db_path: Path = DEFAULT_DB) -> dict:
    return add_transaction_impl(tx_type, amount, category, tx_date, db_path)


def handle_add(args, db_path: Path = DEFAULT_DB) -> int:
    try:
        tx = add_transaction_impl(
            tx_type=args.type,
            amount=args.amount,
            category=args.category,
            tx_date=args.date,
            db_path=db_path,
        )
        print(f"Added {tx['type']}: ${tx['amount']:.2f} for '{tx['category']}' on {tx['date']}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def add_transaction_impl(tx_type: str, amount: float, category: str, tx_date: str = None, db_path: Path = DEFAULT_DB) -> dict:
    import json
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    if tx_type not in ("income", "expense"):
        raise ValueError("Type must be either 'income' or 'expense'.")
    
    if not tx_date:
        tx_date = date.today().isoformat()
    else:
        date.fromisoformat(tx_date)

    tx = {
        "type": tx_type,
        "amount": round(float(amount), 2),
        "category": category,
        "date": tx_date,
    }

    if not db_path.exists():
        txs = []
    else:
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                txs = json.load(f)
        except json.JSONDecodeError:
            txs = []

    txs.append(tx)
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(txs, f, indent=2)

    push_context(f"Added {tx['type']}: ${tx['amount']:.2f} for '{tx['category']}'")
    return tx


def handle_list(args, db_path: Path = DEFAULT_DB) -> int:
    import json
    if not db_path.exists():
        txs = []
    else:
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                txs = json.load(f)
        except json.JSONDecodeError:
            txs = []

    push_context("Listed all transactions")
    if not txs:
        print("No transactions recorded yet.")
        return 0
    print(f"{'Date':<12} | {'Type':<8} | {'Amount':<10} | {'Category'}")
    print("-" * 50)
    for t in txs:
        print(f"{t['date']:<12} | {t['type']:<8} | ${t['amount']:<9.2f} | {t['category']}")
    return 0


def handle_summary(args, db_path: Path = DEFAULT_DB) -> int:
    import json
    if not db_path.exists():
        txs = []
    else:
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                txs = json.load(f)
        except json.JSONDecodeError:
            txs = []

    total_income = sum(t["amount"] for t in txs if t["type"] == "income")
    total_expense = sum(t["amount"] for t in txs if t["type"] == "expense")
    balance = total_income - total_expense

    push_context("Viewed financial summary")
    print(f"Total Income:  ${total_income:.2f}")
    print(f"Total Expense: ${total_expense:.2f}")
    print(f"Net Balance:   ${balance:.2f}")
    print(f"Transactions:  {len(txs)}")
    return 0


# Market CLI handlers
def handle_market_quote(args) -> int:
    try:
        import yfinance as yf
        info = yf.Ticker(args.symbol).info
        if not info or "regularMarketPrice" not in info and "currentPrice" not in info and "previousClose" not in info:
            print(f"No quote found for symbol '{args.symbol}'.")
            return 1

        price = info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose")
        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose") or 0
        change = price - prev_close if prev_close else None
        change_pct = (change / prev_close * 100) if prev_close and change is not None else None

        print(f"=== Quote: {args.symbol.upper()} ({info.get('shortName') or args.symbol.upper()}) ===")
        print(f"Price:        ${price:.2f}")
        if change is not None:
            pct = f"({change_pct:+.2f}%)" if change_pct is not None else ""
            print(f"Change:       ${change:+.2f} {pct}")
        print(f"Volume:       {info.get('volume', 0):,}")
        if prev_close:
            print(f"Prev Close:   ${prev_close:.2f}")
        push_context(f"Fetched quote for {args.symbol.upper()}")
        return 0
    except Exception as e:
        print(f"Error fetching quote: {e}", file=sys.stderr)
        return 1


def handle_market_analyze(args) -> int:
    try:
        raw_data = fetch_daily(args.symbol)
        df = raw_data
        metrics = analyze_market_data(df)

        print(f"=== Market Analysis: {args.symbol.upper()} ({metrics['date']}) ===")
        print(f"Close Price:          ${metrics['close']:.2f}")
        print(f"Daily Change:         ${metrics['change']:.2f} ({metrics['change_pct']:+.2f}%)")
        print(f"Volume:               {metrics['volume']:,}")
        print(f"20-day SMA:           ${metrics['sma_20'] if metrics['sma_20'] is not None else 'N/A'}")
        print(f"50-day SMA:           ${metrics['sma_50'] if metrics['sma_50'] is not None else 'N/A'}")
        print(f"200-day SMA:          ${metrics['sma_200'] if metrics['sma_200'] is not None else 'N/A'}")
        print(f"14-day RSI:           {metrics['rsi_14'] if metrics['rsi_14'] is not None else 'N/A'} ({metrics['rsi_signal']})")
        print(f"Annualized Volatility: {metrics['volatility_annualized']}%" if metrics['volatility_annualized'] is not None else "Annualized Volatility: N/A")
        print(f"Trend Score:          {metrics['trend']}")
        push_context(f"Analyzed market for {args.symbol.upper()} - Trend: {metrics['trend']}")
        return 0
    except Exception as e:
        print(f"Error analyzing market: {e}", file=sys.stderr)
        return 1


# Portfolio CLI handlers
def handle_portfolio_add(args) -> int:
    try:
        pos = add_position(args.symbol, args.shares, args.cost_basis)
        print(f"Added/Updated position: {pos['symbol']} | {pos['shares']} shares @ ${pos['cost_basis']:.2f}")
        push_context(f"Added portfolio position: {pos['symbol']} ({pos['shares']} shares)")
        return 0
    except Exception as e:
        print(f"Error adding position: {e}", file=sys.stderr)
        return 1


def handle_portfolio_list(args) -> int:
    positions = load_portfolio()
    if not positions:
        print("No portfolio positions recorded yet.")
        return 0

    print(f"{'Symbol':<8} | {'Shares':<10} | {'Cost Basis':<12}")
    print("-" * 38)
    for p in positions:
        print(f"{p['symbol']:<8} | {p['shares']:<10.2f} | ${p['cost_basis']:<11.2f}")
    push_context("Listed portfolio positions")
    return 0


def handle_portfolio_summary(args) -> int:
    try:
        positions = load_portfolio()
        if not positions:
            print("No portfolio positions recorded yet.")
            return 0

        # Fetch current prices for all held symbols
        current_prices = {}
        import yfinance as yf
        tickers = yf.Tickers(" ".join(p["symbol"] for p in positions))
        for p in positions:
            sym = p["symbol"]
            info = tickers.tickers[sym].info
            price = info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose")
            if price:
                current_prices[sym] = float(price)
            else:
                # Fallback to latest adjusted daily close if price is missing
                df = fetch_daily(sym)
                if not df.empty:
                    current_prices[sym] = float(df.iloc[-1]["adjusted_close"])
                else:
                    print(f"Warning: No price data for {sym}, skipping.", file=sys.stderr)

        metrics = calculate_portfolio_metrics(positions, current_prices)

        print(f"=== Portfolio Summary ===")
        print(f"Total Cost Basis:  ${metrics['total_cost']:,.2f}")
        print(f"Total Market Val:  ${metrics['total_value']:,.2f}")
        print(f"Total Unrealized P&L: ${metrics['total_pnl']:,.2f} ({metrics['total_pnl_pct']:+.2f}%)")
        print("\nPositions:")
        print(f"{'Symbol':<8} | {'Shares':<8} | {'Basis':<10} | {'Price':<10} | {'Value':<10} | {'P&L':<10}")
        print("-" * 68)
        for item in metrics["positions"]:
            print(f"{item['symbol']:<8} | {item['shares']:<8.2f} | ${item['cost_basis']:<9.2f} | ${item['current_price']:<9.2f} | ${item['current_value']:<9.2f} | ${item['pnl']:<9.2f} ({item['pnl_pct']:+.2f}%)")

        push_context("Viewed portfolio valuation summary")
        return 0
    except Exception as e:
        print(f"Error calculating portfolio summary: {e}", file=sys.stderr)
        return 1


def handle_portfolio_analyze(args) -> int:
    try:
        import yfinance as yf

        positions = load_portfolio()
        if not positions:
            print("No portfolio positions recorded yet.")
            return 0

        symbols = [p["symbol"] for p in positions]

        # Fetch current price + key metrics from yfinance in one batch
        tickers = yf.Tickers(" ".join(symbols))
        price_data = {}
        for sym in symbols:
            try:
                info = tickers.tickers[sym].info
                price_data[sym] = {
                    "price": info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose"),
                    "beta": info.get("beta") or info.get("beta3Year"),
                    "dividend_yield": info.get("dividendYield") or info.get("yield") or 0,
                    "expense_ratio": info.get("netExpenseRatio"),
                    "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                    "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                    "ytd_return": info.get("ytdReturn"),
                    "name": info.get("shortName") or info.get("longName") or sym,
                }
            except Exception:
                price_data[sym] = {"price": None, "beta": None, "dividend_yield": 0, "expense_ratio": None, "fifty_two_week_low": None, "fifty_two_week_high": None, "ytd_return": None, "name": sym}

        # Build position rows
        total_cost = 0.0
        total_value = 0.0
        weighted_beta = 0.0
        weighted_div_yield = 0.0
        rows = []

        for p in positions:
            sym = p["symbol"]
            shares = p["shares"]
            basis = p["cost_basis"]
            cost = shares * basis
            total_cost += cost

            pd_info = price_data.get(sym, {})
            price = pd_info.get("price")
            if price is None:
                print(f"Warning: No price data for {sym}, skipping.", file=sys.stderr)
                continue

            val = shares * price
            total_value += val
            pnl = val - cost
            pnl_pct = (pnl / cost) * 100 if cost > 0 else 0.0
            weight = 0.0  # computed after total_value known

            beta = pd_info.get("beta")
            div_yield = pd_info.get("dividend_yield", 0) or 0

            rows.append({
                "symbol": sym,
                "name": pd_info.get("name", sym),
                "shares": shares,
                "cost_basis": basis,
                "price": price,
                "value": val,
                "cost": cost,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "beta": beta,
                "dividend_yield": div_yield,
                "expense_ratio": pd_info.get("expense_ratio"),
                "fifty_two_week_low": pd_info.get("fifty_two_week_low"),
                "fifty_two_week_high": pd_info.get("fifty_two_week_high"),
                "ytd_return": pd_info.get("ytd_return"),
            })

        if total_value == 0:
            print("No valid price data for any holdings.")
            return 1

        total_pnl = total_value - total_cost
        total_pnl_pct = (total_pnl / total_cost) * 100 if total_cost > 0 else 0.0

        # Compute weights and weighted metrics
        for r in rows:
            r["weight"] = (r["value"] / total_value) * 100
            weighted_beta += (r["weight"] / 100) * (r["beta"] or 1.0)
            weighted_div_yield += (r["weight"] / 100) * r["dividend_yield"]

        # Display
        print("=" * 70)
        print("  PORTFOLIO ANALYSIS")
        print("=" * 70)
        print()
        print(f"  {'Symbol':<8} {'Shares':>7} {'Cost':>10} {'Price':>10} {'Value':>10} {'P&L':>12} {'P&L%':>8} {'Weight':>7}")
        print("  " + "-" * 78)
        for r in rows:
            pnl_sign = "+" if r["pnl"] >= 0 else ""
            print(f"  {r['symbol']:<8} {r['shares']:>7.2f} {r['cost']:>10.2f} {r['price']:>10.2f} {r['value']:>10.2f} {pnl_sign}{r['pnl']:>10.2f} {r['pnl_pct']:>+7.2f}% {r['weight']:>6.1f}%")
        print("  " + "-" * 78)
        pnl_sign = "+" if total_pnl >= 0 else ""
        print(f"  {'TOTAL':<8} {'':>7} {total_cost:>10.2f} {'':>10} {total_value:>10.2f} {pnl_sign}{total_pnl:>10.2f} {total_pnl_pct:>+7.2f}% {'100.0':>6}%")
        print()

        # Per-position detail cards
        print("=" * 70)
        print("  POSITION DETAILS")
        print("=" * 70)
        for r in rows:
            print()
            print(f"  {r['symbol']} — {r['name']}")
            print(f"  {'Beta:':<16} {r['beta'] if r['beta'] is not None else 'N/A'}")
            print(f"  {'Dividend Yield:':<16} {r['dividend_yield']*100:.2f}%" if r['dividend_yield'] else f"  {'Dividend Yield:':<16} 0.00%")
            if r['expense_ratio'] is not None:
                print(f"  {'Expense Ratio:':<16} {r['expense_ratio']:.2f}%")
            if r['fifty_two_week_low'] and r['fifty_two_week_high']:
                print(f"  {'52-Wk Range:':<16} ${r['fifty_two_week_low']:.2f} – ${r['fifty_two_week_high']:.2f}")
            if r['ytd_return'] is not None:
                print(f"  {'YTD Return:':<16} {r['ytd_return']:+.2f}%")
            print(f"  {'Weight:':<16} {r['weight']:.1f}%")
        print()

        # Portfolio-level summary
        print("=" * 70)
        print("  PORTFOLIO SUMMARY")
        print("=" * 70)
        print(f"  Total Cost Basis:    ${total_cost:,.2f}")
        print(f"  Total Market Value:  ${total_value:,.2f}")
        print(f"  Total Unrealized P&L: {pnl_sign}${abs(total_pnl):,.2f} ({total_pnl_pct:+.2f}%)")
        print(f"  Holdings:            {len(rows)}")
        print(f"  Portfolio Beta:      {weighted_beta:.3f}")
        print(f"  Blended Div Yield:   {weighted_div_yield*100:.2f}%")
        print()

        push_context(f"Analyzed portfolio: {len(rows)} positions, value ${total_value:,.2f}, P&L {total_pnl_pct:+.2f}%")
        return 0
    except Exception as e:
        print(f"Error analyzing portfolio: {e}", file=sys.stderr)
        return 1


# Macro CLI handlers
def handle_macro_overview(args) -> int:
    indicators = [
        ("FEDFUNDS", "Federal Funds Rate"),
        ("DGS10", "10-Year Treasury Yield"),
        ("CPIAUCSL", "Consumer Price Index (Inflation)"),
        ("UNRATE", "Unemployment Rate"),
    ]
    print("=== US Macroeconomic Dashboard (FRED) ===")
    print(f"{'Indicator':<35} | {'Series ID':<10} | {'Latest Date':<12} | {'Value':<10} | {'Change'}")
    print("-" * 80)
    for series_id, name in indicators:
        try:
            obs = get_latest_observation(series_id)
            change_str = f"{obs['change']:+.2f}" if obs['change'] is not None else "N/A"
            print(f"{name:<35} | {series_id:<10} | {obs['date']:<12} | {obs['value']:<10.2f} | {change_str}")
        except Exception as e:
            print(f"{name:<35} | {series_id:<10} | Error: {e}")
    push_context("Viewed macroeconomic overview dashboard")
    return 0


def handle_macro_series(args) -> int:
    try:
        obs = get_latest_observation(args.series_id)
        print(f"=== FRED Series: {obs['series_id']} ===")
        print(f"Latest Date:   {obs['date']}")
        print(f"Value:         {obs['value']}")
        if obs['previous_value'] is not None:
            print(f"Previous Date: {obs['previous_date']}")
            print(f"Previous Val:  {obs['previous_value']}")
            print(f"Change:        {obs['change']:+.2f}")
        push_context(f"Queried FRED series {obs['series_id']}")
        return 0
    except Exception as e:
        print(f"Error querying FRED series: {e}", file=sys.stderr)
        return 1


def handle_portfolio_optimize(args) -> int:
    try:
        positions = load_portfolio()
        if not positions:
            print("No portfolio positions found to optimize. Add some positions first using 'finance portfolio add'.")
            return 1
        
        tickers = [p["symbol"] for p in positions]
        print(f"Fetching historical data for optimization: {tickers}...")
        price_dict = {}
        for sym in tickers:
            df = fetch_daily(sym)
            price_dict[sym] = df["adjusted_close"]

        price_matrix = pd.DataFrame(price_dict)
        opt = optimize_portfolio(price_matrix, risk_free_rate=args.rf)

        print("=== MPT Portfolio Optimization (Max Sharpe Ratio) ===")
        print(f"Expected Annual Return: {opt['expected_return']:.2f}%")
        print(f"Annualized Volatility:  {opt['volatility']:.2f}%")
        print(f"Sharpe Ratio:           {opt['sharpe_ratio']:.2f}")
        print("\nOptimal Asset Allocation Weights:")
        for t, w in opt["weights"].items():
            print(f"  {t}: {w * 100:.2f}%")

        push_context("Calculated optimal portfolio weights")
        return 0
    except Exception as e:
        print(f"Error optimizing portfolio: {e}", file=sys.stderr)
        return 1


def handle_strategy_backtest(args) -> int:
    try:
        print(f"Running SMA Crossover backtest for {args.symbol.upper()} ({args.fast}/{args.slow})...")
        df = fetch_daily(args.symbol)
        res = backtest_sma_crossover(df, fast_window=args.fast, slow_window=args.slow)

        print(f"=== Backtest Results: {args.symbol.upper()} ===")
        print(f"Strategy Return:     {res['total_strategy_return_pct']:+.2f}%")
        print(f"Buy & Hold Return:   {res['total_market_return_pct']:+.2f}%")
        print(f"Outperformance:      {res['outperformance_pct']:+.2f}%")
        print(f"Max Drawdown:        {res['max_drawdown_pct']:.2f}%")
        print(f"Sharpe Ratio:        {res['sharpe_ratio']:.2f}")

        push_context(f"Backtested {args.symbol.upper()} SMA crossover ({args.fast}/{args.slow})")
        return 0
    except Exception as e:
        print(f"Error running backtest: {e}", file=sys.stderr)
        return 1


def handle_stock_screen(args) -> int:
    try:
        watchlist = ["SPY", "DIA", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META"]
        print(f"Screening stock universe across {len(watchlist)} symbols...")
        stock_data = {}
        for sym in watchlist:
            try:
                stock_data[sym] = fetch_daily(sym)
            except Exception:
                pass

        results = score_stocks(stock_data)
        print("=== Multi-Factor Stock Screener (Momentum & Volatility) ===")
        print(f"{'Rank':<5} | {'Ticker':<8} | {'Price':<10} | {'3M Mom':<10} | {'1M Mom':<10} | {'Vol':<10} | {'Score'}")
        print("-" * 72)
        for i, item in enumerate(results, 1):
            print(f"{i:<5} | {item['ticker']:<8} | ${item['latest_price']:<9.2f} | {item['momentum_3m']:<+9.2f}% | {item['momentum_1m']:<+9.2f}% | {item['annualized_volatility']:<9.2f}% | {item['composite_score']:<.2f}")

        push_context("Ran multi-factor stock screener")
        return 0
    except Exception as e:
        print(f"Error running screener: {e}", file=sys.stderr)
        return 1


def handle_report_generate(args) -> int:
    try:
        print("Generating comprehensive market briefing report...")
        report = generate_market_briefing()

        print("\n=== AUTOMATED MARKET BRIEFING REPORT ===")
        print("\n--- 1. Macroeconomic Overview (FRED) ---")
        for k, v in report["macro_indicators"].items():
            if "error" not in v:
                print(f"  {k}: {v['value']} (Date: {v['date']}, Change: {v['change']})")

        print("\n--- 2. Market Tickers Analysis ---")
        for sym, m in report["market_analysis"].items():
            if "error" not in m:
                print(f"  {sym}: Close=${m['close']} | Trend={m['trend']} | RSI={m['rsi_14']} ({m['rsi_signal']})")

        if report["portfolio_summary"]:
            ps = report["portfolio_summary"]
            print("\n--- 3. Portfolio Performance ---")
            print(f"  Total Cost: ${ps['total_cost']:,.2f} | Value: ${ps['total_value']:,.2f} | P&L: ${ps['total_pnl']:,.2f} ({ps['total_pnl_pct']:+.2f}%)")

        if report["portfolio_optimization"]:
            opt = report["portfolio_optimization"]
            print("\n--- 4. Optimal Allocation Weights (MPT) ---")
            print(f"  Expected Return: {opt['expected_return']:.2f}% | Volatility: {opt['volatility']:.2f}% | Sharpe: {opt['sharpe_ratio']:.2f}")
            for t, w in opt["weights"].items():
                print(f"    {t}: {w * 100:.2f}%")

        # News & Sentiment section
        msent = report.get("market_sentiment")
        tsentiments = report.get("ticker_sentiments", [])
        catalysts = report.get("catalysts")

        print("\n--- 5. News & Sentiment ---")
        if msent and "error" not in msent:
            print(f"  Broad Market (RSS): score={msent.get('score', 0.0):+.3f} | label={msent.get('label', 'neutral')} | items={msent.get('items_scored', 0)}")
        elif msent and "error" in msent:
            print(f"  Broad Market (RSS): unavailable ({msent.get('error', 'unknown')})")
        else:
            print("  Broad Market (RSS): not loaded")

        if tsentiments:
            print("  Per-Ticker Sentiment:")
            for ts in tsentiments:
                score_str = f"{ts.get('score', 0.0):+.3f}" if ts.get("score") is not None else "N/A"
                print(f"    {ts['symbol']}: score={score_str} | label={ts.get('label', 'neutral')} | items={ts.get('items', 0)}")

        if catalysts:
            print("  Catalysts Detected:")
            for group, items in catalysts.items():
                if items:
                    titles = [it.get("title", "")[:60] for it in items[:3]]
                    print(f"    {group.upper()} ({len(items)}): {'; '.join(titles)}")

        push_context("Generated automated market briefing report with sentiment")
        return 0
    except Exception as e:
        print(f"Error generating report: {e}", file=sys.stderr)
        return 1


def handle_wrap_up(args) -> int:
    from datetime import datetime

    # 1. Transaction & Budget Review
    txs = load_transactions()
    total_income = sum(t["amount"] for t in txs if t["type"] == "income")
    total_expense = sum(t["amount"] for t in txs if t["type"] == "expense")
    balance = total_income - total_expense

    print("=" * 60)
    print("           FINANCE SESSION WRAP-UP")
    print("=" * 60)
    print(f"\n--- 1. Transaction Summary ---")
    print(f"  Total Income:   ${total_income:,.2f}")
    print(f"  Total Expenses: ${total_expense:,.2f}")
    print(f"  Net Balance:    ${balance:,.2f}")
    print(f"  Transactions:   {len(txs)}")

    # 2. Portfolio Check
    positions = load_portfolio()
    portfolio_val = None
    if positions:
        print(f"\n--- 2. Portfolio Holdings ---")
        print(f"  {'Symbol':<8} | {'Shares':<10} | {'Cost Basis':<12}")
        print("  " + "-" * 38)
        total_cost = 0.0
        for p in positions:
            cost = p["shares"] * p["cost_basis"]
            total_cost += cost
            print(f"  {p['symbol']:<8} | {p['shares']:<10.2f} | ${p['cost_basis']:<11.2f}")
        print(f"\n  Total Cost Basis: ${total_cost:,.2f}")
        portfolio_val = total_cost
    else:
        print(f"\n--- 2. Portfolio Holdings ---")
        print("  No positions tracked.")

    # 3. Dynamic "What's Next" Roadmap
    print(f"\n--- 3. What's Next ---")
    roadmap = []
    if len(txs) == 0:
        roadmap.append("  [ ] Record your first transaction: finance add income <amount> <category>")
    if not positions:
        roadmap.append("  [ ] Add your first stock position: finance portfolio add SPY 10 400.00")
    if positions:
        roadmap.append("  [ ] Optimize your portfolio allocation: finance optimize")
    roadmap.append("  [ ] Screen for top momentum stocks: finance screen")
    roadmap.append("  [ ] Check macroeconomic conditions: finance macro overview")
    roadmap.append("  [ ] Run a backtest on a strategy: finance backtest SPY --fast 20 --slow 50")
    roadmap.append("  [ ] Generate a full market briefing: finance report")
    if not roadmap:
        roadmap.append("  All tasks complete. Great session!")

    for item in roadmap:
        print(item)

    # 4. Update progress.md
    progress_path = Path("progress.md")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    progress_entry = f"""
## Session Wrap-Up ({now})
- **Transactions:** {len(txs)} recorded | Net Balance: ${balance:,.2f}
- **Portfolio:** {len(positions)} position(s) tracked
- **Actions Taken:**
  - Session wrap-up completed
  - Short-term memory cleared
- **Next Steps:**
"""
    for item in roadmap:
        progress_entry += f"  {item.strip()}\n"

    try:
        if progress_path.exists():
            with open(progress_path, "a", encoding="utf-8") as f:
                f.write(progress_entry)
        else:
            with open(progress_path, "w", encoding="utf-8") as f:
                f.write("# Progress Log\n" + progress_entry)
    except Exception as e:
        print(f"  Warning: Could not update progress.md: {e}")

    # 5. Memory archival & clear
    push_context(f"Session wrapped up on {now} | Balance: ${balance:,.2f} | Positions: {len(positions)}")
    clear_short_term_memory()

    print(f"\n--- 4. Session Status ---")
    print(f"  Session wrapped up at {now}")
    print(f"  Short-term memory cleared.")
    print(f"  progress.md updated.")
    print("=" * 60)
    return 0


# Memory CLI handlers
def handle_memory_show(args) -> int:
    long_mem = load_long_term_memory()
    short_mem = get_short_term_memory()
    print("=== Long-Term Memory (Persistent Goals, Rules & Preferences) ===")
    if not long_mem:
        print("  (No long-term memories stored. Use 'finance memory remember <key> <value>')")
    else:
        for k, v in long_mem.items():
            print(f"  {k}: {v}")

    print("\n=== Short-Term Memory (Recent Session Context) ===")
    if not short_mem:
        print("  (Short-term memory is empty)")
    else:
        for i, item in enumerate(short_mem, 1):
            print(f"  {i}. {item}")
    return 0


def handle_memory_remember(args) -> int:
    remember(args.key, args.value)
    print(f"Remembered in long-term memory: {args.key} = {args.value}")
    push_context(f"Stored long-term memory: '{args.key}'")
    return 0


def handle_memory_recall(args) -> int:
    if args.key:
        val = recall(args.key)
        if val is not None:
            print(f"{args.key}: {val}")
        else:
            print(f"Key '{args.key}' not found in long-term memory.")
    else:
        mem = recall()
        if not mem:
            print("Long-term memory is empty.")
        else:
            for k, v in mem.items():
                print(f"{k}: {v}")
    return 0


def handle_memory_forget(args) -> int:
    success = forget(args.key)
    if success:
        print(f"Forgot '{args.key}' from long-term memory.")
        push_context(f"Forgot long-term memory: '{args.key}'")
    else:
        print(f"Key '{args.key}' not found in long-term memory.")
    return 0


def handle_memory_push(args) -> int:
    push_context(args.item)
    print(f"Pushed to short-term memory: {args.item}")
    return 0


def handle_memory_clear(args) -> int:
    clear_short_term_memory()
    print("Cleared short-term memory.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finance & US Stock Market Tracking CLI")
    parser.add_argument(
        "--version", action="version", version="%(prog)s 0.2.0"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # add subcommand (transactions)
    add_parser = subparsers.add_parser("add", help="Add income or expense transaction")
    add_parser.add_argument("type", choices=["income", "expense"], help="Transaction type")
    add_parser.add_argument("amount", type=float, help="Transaction amount")
    add_parser.add_argument("category", help="Transaction category / description")
    add_parser.add_argument("--date", help="Date in YYYY-MM-DD format (defaults to today)")
    add_parser.set_defaults(func=handle_add)

    # list subcommand
    list_parser = subparsers.add_parser("list", help="List all transactions")
    list_parser.set_defaults(func=handle_list)

    # summary subcommand
    summary_parser = subparsers.add_parser("summary", help="Show financial summary")
    summary_parser.set_defaults(func=handle_summary)

    # market subcommand
    market_parser = subparsers.add_parser("market", help="Track and analyze US Stock Market (S&P 500, Dow Jones, Stocks)")
    market_subparsers = market_parser.add_subparsers(dest="market_command", required=True)

    quote_parser = market_subparsers.add_parser("quote", help="Get real-time quote for symbol (e.g., SPY, DIA, AAPL)")
    quote_parser.add_argument("symbol", help="Stock ticker symbol")
    quote_parser.set_defaults(func=handle_market_quote)

    analyze_parser = market_subparsers.add_parser("analyze", help="Run technical indicators & market analysis for symbol")
    analyze_parser.add_argument("symbol", help="Stock ticker symbol")
    analyze_parser.set_defaults(func=handle_market_analyze)

    # portfolio subcommand
    portfolio_parser = subparsers.add_parser("portfolio", help="Manage and track investment portfolio")
    portfolio_subparsers = portfolio_parser.add_subparsers(dest="portfolio_command", required=True)

    p_add_parser = portfolio_subparsers.add_parser("add", help="Add or update stock holding")
    p_add_parser.add_argument("symbol", help="Stock ticker symbol")
    p_add_parser.add_argument("shares", type=float, help="Number of shares")
    p_add_parser.add_argument("cost_basis", type=float, help="Cost basis per share")
    p_add_parser.set_defaults(func=handle_portfolio_add)

    p_list_parser = portfolio_subparsers.add_parser("list", help="List portfolio positions")
    p_list_parser.set_defaults(func=handle_portfolio_list)

    p_sum_parser = portfolio_subparsers.add_parser("summary", help="Show portfolio valuation and P&L summary")
    p_sum_parser.set_defaults(func=handle_portfolio_summary)

    p_analyze_parser = portfolio_subparsers.add_parser("analyze", help="Detailed portfolio analysis with beta, yield, and risk metrics")
    p_analyze_parser.set_defaults(func=handle_portfolio_analyze)

    # macro subcommand
    macro_parser = subparsers.add_parser("macro", help="Track US macroeconomic indicators (FRED)")
    macro_subparsers = macro_parser.add_subparsers(dest="macro_command", required=True)

    macro_overview_parser = macro_subparsers.add_parser("overview", help="Show core macroeconomic dashboard")
    macro_overview_parser.set_defaults(func=handle_macro_overview)

    macro_series_parser = macro_subparsers.add_parser("series", help="Query any specific FRED series ID")
    macro_series_parser.add_argument("series_id", help="FRED series ID (e.g., FEDFUNDS, DGS10, CPIAUCSL)")
    macro_series_parser.set_defaults(func=handle_macro_series)

    # optimize subcommand
    opt_parser = subparsers.add_parser("optimize", help="Optimize portfolio asset allocation weights (MPT)")
    opt_parser.add_argument("--rf", type=float, default=0.04, help="Risk-free rate (default 0.04)")
    opt_parser.set_defaults(func=handle_portfolio_optimize)

    # backtest subcommand
    bt_parser = subparsers.add_parser("backtest", help="Backtest SMA crossover strategy for symbol")
    bt_parser.add_argument("symbol", help="Stock ticker symbol")
    bt_parser.add_argument("--fast", type=int, default=20, help="Fast SMA window (default 20)")
    bt_parser.add_argument("--slow", type=int, default=50, help="Slow SMA window (default 50)")
    bt_parser.set_defaults(func=handle_strategy_backtest)

    # screen subcommand
    screen_parser = subparsers.add_parser("screen", help="Screen stock universe using multi-factor model (Momentum & Volatility)")
    screen_parser.set_defaults(func=handle_stock_screen)

    # report subcommand
    report_parser = subparsers.add_parser("report", help="Generate comprehensive automated market briefing report")
    report_parser.set_defaults(func=handle_report_generate)

    # wrap-up subcommand
    wrap_parser = subparsers.add_parser("wrap-up", help="Execute end-of-session financial wrap-up and clear session memory")
    wrap_parser.set_defaults(func=handle_wrap_up)

    # memory subcommand
    memory_parser = subparsers.add_parser("memory", help="Manage in-context short-term and long-term memory")
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command", required=True)

    show_parser = memory_subparsers.add_parser("show", help="Show short-term and long-term memory")
    show_parser.set_defaults(func=handle_memory_show)

    rem_parser = memory_subparsers.add_parser("remember", help="Store in long-term memory")
    rem_parser.add_argument("key", help="Memory key")
    rem_parser.add_argument("value", help="Memory value")
    rem_parser.set_defaults(func=handle_memory_remember)

    rec_parser = memory_subparsers.add_parser("recall", help="Recall from long-term memory")
    rec_parser.add_argument("key", nargs="?", help="Optional specific key")
    rec_parser.set_defaults(func=handle_memory_recall)

    fog_parser = memory_subparsers.add_parser("forget", help="Remove from long-term memory")
    fog_parser.add_argument("key", help="Memory key to remove")
    fog_parser.set_defaults(func=handle_memory_forget)

    push_parser = memory_subparsers.add_parser("push", help="Push item to short-term context")
    push_parser.add_argument("item", help="Context item / note")
    push_parser.set_defaults(func=handle_memory_push)

    clear_parser = memory_subparsers.add_parser("clear", help="Clear short-term context")
    clear_parser.set_defaults(func=handle_memory_clear)

    return parser


def main(argv=None) -> int:
    from dotenv import load_dotenv
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
