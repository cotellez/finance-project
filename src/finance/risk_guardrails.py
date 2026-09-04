"""Deterministic risk guardrails / circuit breakers.

These are HARD programmatic checks that override LLM/agent discretion to
prevent runaway algorithmic losses. They are pure functions operating on
numeric inputs so they can be unit-tested deterministically and enforced in
any execution path (including autonomous agent workflows).
"""

import numpy as np
import pandas as pd
from datetime import date, datetime


def calculate_atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average True Range over the provided OHLC dataframe."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(window=window).mean()


def atr_trailing_stop(
    df: pd.DataFrame,
    atr_multiple: float = 3.0,
    atr_window: int = 14,
    price_col: str = "adjusted_close",
) -> pd.DataFrame:
    """Compute an ATR-based trailing stop for a long position.

    Returns a DataFrame with 'price', 'atr', and 'trailing_stop' columns. The
    stop ratchets up with price highs minus `atr_multiple * ATR`, locking in
    profits during runs while giving room amid normal noise.
    """
    if atr_multiple <= 0:
        raise ValueError("atr_multiple must be positive.")

    out = df.copy()
    out["price"] = out[price_col]
    out["atr"] = calculate_atr(out, window=atr_window)

    n = len(out)
    stop = np.full(n, np.nan)
    highest = np.full(n, np.nan)
    current_high = 0.0
    current_stop = 0.0

    for i in range(n):
        price = out["price"].iloc[i]
        atr = out["atr"].iloc[i]
        if pd.isna(atr) or pd.isna(price):
            highest[i] = current_high
            stop[i] = current_stop
            continue

        # Track running highest price since entry (or since coverage began).
        current_high = max(current_high, float(price))
        candidate_stop = current_high - atr_multiple * float(atr)
        # Ratchet: stop only moves up (for longs), never down.
        current_stop = max(current_stop, candidate_stop)
        highest[i] = current_high
        stop[i] = current_stop

    out["atr_high"] = highest
    out["trailing_stop"] = stop
    return out


def max_drawdown_from_equity(equity_curve: list) -> float:
    """Compute maximum drawdown (negative fraction) from an equity curve."""
    if not equity_curve or len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        peak = max(peak, val)
        if peak > 0:
            dd = (val - peak) / peak
            max_dd = min(max_dd, dd)
    return float(max_dd)


def check_circuit_breakers(portfolio_metrics: dict, config: dict) -> dict:
    """Evaluate hard risk guardrails and report whether to halt trading.

    Args:
        portfolio_metrics: dict from portfolio.calculate_portfolio_metrics or a
            compatible shape with total_value / total_pnl_pct.
        config: dict with optional thresholds:
            - max_drawdown_pct (e.g., 20.0): halt if P&L drawdown exceeds this
            - max_position_pct (e.g., 25.0): max single-position concentration
            - max_volatility_annualized (e.g., 50.0): halt if portfolio vol too high

    Returns:
        dict with `halt` (bool), `blocked_reasons` (list), and booleans per check.
    """
    halt = False
    blocked_reasons = []

    pnl_pct = portfolio_metrics.get("total_pnl_pct", 0.0)
    max_drawdown_pct = config.get("max_drawdown_pct", 20.0)
    if pnl_pct <= -abs(max_drawdown_pct):
        halt = True
        blocked_reasons.append(
            f"MAX DRAWDOWN EXCEEDED: portfolio P&L is {pnl_pct:.1f}% vs limit -{max_drawdown_pct:.0f}%. Halting trading."
        )

    # Position concentration check.
    max_position_pct = config.get("max_position_pct", 25.0)
    positions = portfolio_metrics.get("positions", [])
    total_value = portfolio_metrics.get("total_value", 0.0)
    concentration_ok = True
    for pos in positions:
        if total_value > 0:
            weight = (pos.get("current_value", 0.0) / total_value) * 100
            if weight > max_position_pct:
                halt = True
                concentration_ok = False
                blocked_reasons.append(
                    f"POSITION CONCENTRATION: {pos.get('symbol')} is {weight:.1f}% of portfolio "
                    f"(limit {max_position_pct:.0f}%). Halting new concentration."
                )

    # Annualized volatility check.
    max_volatility = config.get("max_volatility_annualized")
    volatility_ok = True
    if max_volatility is not None:
        portfolio_vol = portfolio_metrics.get("total_volatility_annualized")
        if portfolio_vol is not None and portfolio_vol > max_volatility:
            halt = True
            volatility_ok = False
            blocked_reasons.append(
                f"HIGH VOLATILITY: portfolio annualized vol is {portfolio_vol:.1f}% vs limit {max_volatility:.0f}%. Halting trading."
            )

    return {
        "halt": halt,
        "blocked_reasons": blocked_reasons,
        "max_drawdown_pct_limit": max_drawdown_pct,
        "max_position_pct_limit": max_position_pct,
        "checks": {
            "drawdown_ok": pnl_pct > -abs(max_drawdown_pct),
            "concentration_ok": concentration_ok,
            "volatility_ok": volatility_ok,
        },
    }


def calculate_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Compute historical Value-at-Risk (VaR) as a positive loss fraction."""
    if returns is None or returns.empty:
        return 0.0
    var = float(-np.percentile(returns.dropna(), (1 - confidence) * 100))
    return max(0.0, min(var, 1.0))


def validate_position_size(notional: float, portfolio_value: float, max_position_pct: float = 25.0) -> float:
    """Return the maximum allowed position notional given a portfolio cap."""
    cap = portfolio_value * (max_position_pct / 100.0)
    return min(notional, cap)


def check_sentiment_veto(symbol: str, news_items: list, sentiment_threshold: float = -0.3) -> dict:
    """Evaluate whether recent news/sentiment warrants an asymmetric veto/halt for a symbol.

    Args:
        symbol: Stock ticker symbol.
        news_items: List of news dicts with title/summary or text.
        sentiment_threshold: Threshold below which sentiment triggers a veto (default -0.3).

    Returns:
        dict with `veto` (bool), `reason` (str|None), and sentiment score metrics.
    """
    from finance.sentiment import score_news_items
    res = score_news_items(news_items)
    score = res.get("score", 0.0)
    label = res.get("label", "neutral")
    
    veto = False
    reason = None

    if score <= sentiment_threshold:
        veto = True
        reason = f"SENTIMENT VETO for {symbol.upper()}: aggregate sentiment score {score:.2f} is below threshold {sentiment_threshold} (label: {label})."

    # Also check for severe catalyst keywords
    severe_keywords = {"lawsuit", "investigation", "fraud", "scandal", "bankruptcy", "recall"}
    for item in news_items:
        text = str(item.get("title", "")) + " " + str(item.get("summary", ""))
        text_lower = text.lower()
        found_kw = [kw for kw in severe_keywords if kw in text_lower]
        if found_kw:
            veto = True
            reason = f"CATALYST VETO for {symbol.upper()}: severe keywords detected {found_kw} in news."
            break

    return {
        "symbol": symbol.upper(),
        "veto": veto,
        "reason": reason,
        "sentiment_score": score,
        "sentiment_label": label,
    }


def check_earnings_blackout(symbol: str, earnings_date: str | date | datetime, as_of_date: str | date | datetime = None, blackout_days: int = 5) -> dict:
    """Check whether a symbol is within an upcoming earnings blackout window.

    Args:
        symbol: Stock ticker symbol.
        earnings_date: Upcoming earnings release date.
        as_of_date: Reference date for comparison (defaults to today).
        blackout_days: Number of days before earnings to trigger blackout (default 5).

    Returns:
        dict with `in_blackout` (bool), `days_until_earnings` (int), and `reason` (str|None).
    """
    if isinstance(earnings_date, str):
        earn_dt = date.fromisoformat(earnings_date)
    elif isinstance(earnings_date, datetime):
        earn_dt = earnings_date.date()
    else:
        earn_dt = earnings_date

    if as_of_date is None:
        ref_dt = date.today()
    elif isinstance(as_of_date, str):
        ref_dt = date.fromisoformat(as_of_date)
    elif isinstance(as_of_date, datetime):
        ref_dt = as_of_date.date()
    else:
        ref_dt = as_of_date

    delta = (earn_dt - ref_dt).days
    in_blackout = 0 <= delta <= blackout_days
    reason = None

    if in_blackout:
        reason = f"EARNINGS BLACKOUT for {symbol.upper()}: earnings scheduled on {earn_dt.isoformat()} ({delta} days away, within {blackout_days}-day window)."
    elif delta < 0:
        reason = f"Earnings date {earn_dt.isoformat()} has already passed ({abs(delta)} days ago)."

    return {
        "symbol": symbol.upper(),
        "earnings_date": earn_dt.isoformat(),
        "as_of_date": ref_dt.isoformat(),
        "days_until_earnings": delta,
        "in_blackout": in_blackout,
        "reason": reason,
    }


def fetch_earnings_date(symbol: str) -> str | None:
    """Fetch the next upcoming earnings date for a symbol from yfinance.

    Returns the date as an ISO string (YYYY-MM-DD) or None if unavailable.
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        cal = ticker.calendar
        if cal is None:
            return None
        # yfinance returns calendar as dict or DataFrame; handle both shapes
        if hasattr(cal, "iloc"):
            # DataFrame with 'Earnings Date' column
            if "Earnings Date" in cal.columns:
                dt = cal["Earnings Date"].iloc[0]
                return dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)
            return None
        if isinstance(cal, dict):
            # Dict with 'Earnings Date' key (list of dates or single date)
            ed = cal.get("Earnings Date")
            if not ed:
                return None
            if isinstance(ed, list):
                dt = ed[0] if ed else None
            else:
                dt = ed
            return dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)
    except Exception:
        return None
    return None


def check_earnings_blackout_for_symbol(symbol: str, as_of_date: str | date | datetime = None, blackout_days: int = 5) -> dict:
    """Convenience: fetch earnings date from yfinance and check blackout in one call.

    Returns the same shape as check_earnings_blackout, with an added
    `earnings_date_found` flag if the date was successfully retrieved.
    """
    earnings_date_str = fetch_earnings_date(symbol)
    if earnings_date_str is None:
        return {
            "symbol": symbol.upper(),
            "earnings_date": None,
            "as_of_date": (date.today() if as_of_date is None else (
                date.fromisoformat(as_of_date) if isinstance(as_of_date, str) else
                (as_of_date.date() if isinstance(as_of_date, datetime) else as_of_date)
            )).isoformat() if not isinstance(as_of_date, date) else as_of_date.isoformat(),
            "days_until_earnings": None,
            "in_blackout": False,
            "reason": f"Could not retrieve earnings date for {symbol.upper()}. No blackout check possible.",
            "earnings_date_found": False,
        }

    result = check_earnings_blackout(symbol, earnings_date_str, as_of_date=as_of_date, blackout_days=blackout_days)
    result["earnings_date_found"] = True
    return result
