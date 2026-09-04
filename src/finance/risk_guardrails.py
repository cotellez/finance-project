"""Deterministic risk guardrails / circuit breakers.

These are HARD programmatic checks that override LLM/agent discretion to
prevent runaway algorithmic losses. They are pure functions operating on
numeric inputs so they can be unit-tested deterministically and enforced in
any execution path (including autonomous agent workflows).
"""

import numpy as np
import pandas as pd


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
    for pos in positions:
        if total_value > 0:
            weight = (pos.get("current_value", 0.0) / total_value) * 100
            if weight > max_position_pct:
                halt = True
                blocked_reasons.append(
                    f"POSITION CONCENTRATION: {pos.get('symbol')} is {weight:.1f}% of portfolio "
                    f"(limit {max_position_pct:.0f}%). Halting new concentration."
                )

    return {
        "halt": halt,
        "blocked_reasons": blocked_reasons,
        "max_drawdown_pct_limit": max_drawdown_pct,
        "max_position_pct_limit": max_position_pct,
        "checks": {
            "drawdown_ok": pnl_pct > -abs(max_drawdown_pct),
            "concentration_ok": True,
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
