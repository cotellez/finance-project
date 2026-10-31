"""Forward-Looking Dividend & Cash Flow Engine.

Fetches dividend rate, ex-dividend dates, and payment history via yfinance
to project monthly/annual cash flows and yield-on-cost across portfolio holdings.
"""

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from finance.cache import cache_response, get_cached_response
from finance.portfolio import load_portfolio

DIVIDEND_CACHE_TTL_HOURS = 12

_EMPTY_DIV_INFO = {
    "dividend_rate": 0.0,
    "dividend_yield": 0.0,
    "ex_dividend_date": "N/A",
    "payout_ratio": 0.0,
}


def _parse_dividend_info(symbol: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw yfinance info dict into dividend metrics."""
    rate = info.get("dividendRate") or info.get("trailingAnnualDividendRate") or 0.0
    div_yield = info.get("dividendYield") or info.get("trailingAnnualDividendYield") or 0.0
    if div_yield and div_yield > 1.0:  # e.g., 3.16 means 3.16%
        div_yield = div_yield / 100.0

    ex_date = info.get("exDividendDate")
    if isinstance(ex_date, (int, float)):
        ex_date_str = datetime.fromtimestamp(ex_date, tz=timezone.utc).strftime("%Y-%m-%d")
    elif isinstance(ex_date, str):
        ex_date_str = ex_date[:10]
    else:
        ex_date_str = "N/A"

    payout_ratio = info.get("payoutRatio") or 0.0

    return {
        "symbol": symbol,
        "dividend_rate": round(float(rate), 4) if math.isfinite(float(rate)) else 0.0,
        "dividend_yield": round(float(div_yield), 4) if math.isfinite(float(div_yield)) else 0.0,
        "ex_dividend_date": ex_date_str,
        "payout_ratio": round(float(payout_ratio), 4) if math.isfinite(float(payout_ratio)) else 0.0,
    }


def fetch_symbol_dividend_info(symbol: str, use_cache: bool = True) -> Dict[str, Any]:
    """Fetch dividend metrics for a single ticker symbol via yfinance.

    Results are cached in the shared SQLite TTL cache to avoid the slow
    per-call yfinance handshake on repeated runs.
    """
    symbol = symbol.upper().strip()
    cache_key = f"dividend_info:{symbol}"
    if use_cache:
        cached = get_cached_response(cache_key, ttl_hours=DIVIDEND_CACHE_TTL_HOURS)
        if cached:
            return cached
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).info or {}
        result = _parse_dividend_info(symbol, info)
        if use_cache:
            cache_response(cache_key, result)
        return result
    except Exception:
        # Robust fallback for offline/testing or API failure
        return {"symbol": symbol, **_EMPTY_DIV_INFO}


def fetch_dividend_info_batch(symbols: List[str], use_cache: bool = True) -> Dict[str, Dict[str, Any]]:
    """Fetch dividend metrics for multiple symbols, sharing one yfinance session.

    Batching amortizes yfinance's slow cookie/crumb handshake across all symbols.
    Cache hits are served first and only cache misses are fetched.
    """
    results: Dict[str, Dict[str, Any]] = {}
    misses: List[str] = []

    for raw in symbols:
        sym = raw.upper().strip()
        cached = get_cached_response(f"dividend_info:{sym}", ttl_hours=DIVIDEND_CACHE_TTL_HOURS) if use_cache else None
        if cached:
            results[sym] = cached
        else:
            misses.append(sym)

    if not misses:
        return results

    try:
        import yfinance as yf

        tickers = yf.Tickers(" ".join(misses))
        for sym in misses:
            try:
                info = tickers.tickers[sym].info or {}
                parsed = _parse_dividend_info(sym, info)
            except Exception:
                parsed = {"symbol": sym, **_EMPTY_DIV_INFO}
            if use_cache:
                cache_response(f"dividend_info:{sym}", parsed)
            results[sym] = parsed
    except Exception:
        for sym in misses:
            results.setdefault(sym, {"symbol": sym, **_EMPTY_DIV_INFO})

    return results


def analyze_portfolio_dividends(
    positions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Analyze forward-looking dividend cash flows and yield metrics for portfolio."""
    if positions is None:
        positions = load_portfolio()

    holding_metrics = []
    total_market_val = 0.0
    total_cost_basis = 0.0
    total_annual_income = 0.0

    div_info_map = fetch_dividend_info_batch([p["symbol"] for p in positions])

    for pos in positions:
        sym = pos["symbol"]
        shares = float(pos["shares"])
        basis = float(pos["cost_basis"])
        cost = shares * basis

        div_info = div_info_map.get(sym.upper().strip(), {"symbol": sym, **_EMPTY_DIV_INFO})
        rate = div_info["dividend_rate"]
        
        # Estimate current market price
        current_price = pos.get("current_price") or basis
        mkt_val = shares * current_price

        annual_income = shares * rate
        yield_on_cost = (annual_income / cost * 100.0) if cost > 0 else 0.0
        current_yield = (annual_income / mkt_val * 100.0) if mkt_val > 0 else 0.0

        total_cost_basis += cost
        total_market_val += mkt_val
        total_annual_income += annual_income

        holding_metrics.append({
            "symbol": sym,
            "shares": shares,
            "cost_basis": basis,
            "current_price": current_price,
            "market_value": round(mkt_val, 2),
            "dividend_rate": rate,
            "annual_income": round(annual_income, 2),
            "yield_on_cost": round(yield_on_cost, 2),
            "current_yield": round(current_yield, 2),
            "ex_dividend_date": div_info["ex_dividend_date"],
        })

    portfolio_yield_on_cost = (
        (total_annual_income / total_cost_basis * 100.0) if total_cost_basis > 0 else 0.0
    )
    portfolio_current_yield = (
        (total_annual_income / total_market_val * 100.0) if total_market_val > 0 else 0.0
    )

    # Monthly breakdown estimate (quarterly payout assumed)
    monthly_estimated_income = round(total_annual_income / 12.0, 2)

    return {
        "holdings": holding_metrics,
        "total_cost_basis": round(total_cost_basis, 2),
        "total_market_value": round(total_market_val, 2),
        "total_annual_income": round(total_annual_income, 2),
        "monthly_estimated_income": monthly_estimated_income,
        "portfolio_yield_on_cost": round(portfolio_yield_on_cost, 2),
        "portfolio_current_yield": round(portfolio_current_yield, 2),
    }
