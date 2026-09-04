"""Vectorized strategy backtesting engine.

Includes look-ahead bias prevention and market-friction modeling (transaction
costs, slippage) so backtest results reflect realistic, tradeable outcomes
rather than optimistic curve-fit numbers.
"""

import pandas as pd
import numpy as np

from finance.bias_guard import assert_no_lookahead, shift_signal_to_position


def backtest_sma_crossover(
    df: pd.DataFrame,
    fast_window: int = 20,
    slow_window: int = 50,
    price_col: str = "adjusted_close",
    transaction_cost_pct: float = 0.05,
    slippage_pct: float = 0.05,
) -> dict:
    """Backtest a Simple Moving Average (SMA) crossover strategy.

    Buy/Long when fast SMA > slow SMA, sell/flat when fast SMA < slow SMA.

    Look-ahead safety: the raw signal is shifted one bar so today's position
    only uses yesterday's (or earlier) data.

    Friction: transaction costs and slippage are charged on each position
    change (turnover), modeling realistic execution.
    """
    if len(df) < slow_window:
        raise ValueError(f"Data length ({len(df)}) is less than slow window ({slow_window}).")

    data = df.copy()
    data["fast_sma"] = data[price_col].rolling(window=fast_window).mean()
    data["slow_sma"] = data[price_col].rolling(window=slow_window).mean()

    # Signal: 1 when fast > slow else 0
    data["signal"] = 0
    data.loc[data["fast_sma"] > data["slow_sma"], "signal"] = 1

    # Prevent look-ahead bias: position uses prior bar's signal (via shift).
    data["position"] = shift_signal_to_position(data, signal_col="signal", fill=0.0)

    # Turnover: absolute change in position (0 -> 1 buys; 1 -> 0 sells).
    data["turnover"] = data["position"].diff().abs().fillna(data["position"].abs())

    # Daily returns of underlying asset.
    data["market_return"] = data[price_col].pct_change().fillna(0)

    # Strategy gross return.
    data["strategy_return"] = data["position"] * data["market_return"]

    # Friction: cost = turnover * (transaction_cost + slippage) as % of value.
    cost_rate = (transaction_cost_pct + slippage_pct) / 100.0
    data["cost"] = data["turnover"] * cost_rate
    data["strategy_return_net"] = data["strategy_return"] - data["cost"]

    # Cumulative returns.
    data["cumulative_market"] = (1 + data["market_return"]).cumprod()
    data["cumulative_strategy"] = (1 + data["strategy_return_net"]).cumprod()

    total_market_return = float(data["cumulative_market"].iloc[-1] - 1) * 100
    total_strategy_return = float(data["cumulative_strategy"].iloc[-1] - 1) * 100

    # Max Drawdown.
    rolling_max = data["cumulative_strategy"].cummax()
    drawdown = (data["cumulative_strategy"] - rolling_max) / rolling_max
    max_drawdown = float(drawdown.min()) * 100

    # Sharpe ratio (net of costs, 0% risk-free for simplicity).
    strat_daily_returns = data["strategy_return_net"]
    sharpe = (
        float((strat_daily_returns.mean() / strat_daily_returns.std()) * np.sqrt(252))
        if strat_daily_returns.std() > 0
        else 0.0
    )

    total_turnover = float(data["turnover"].sum())
    total_costs = float(data["cost"].sum())

    return {
        "fast_window": fast_window,
        "slow_window": slow_window,
        "total_market_return_pct": round(total_market_return, 2),
        "total_strategy_return_pct": round(total_strategy_return, 2),
        "gross_strategy_return_pct": round(float((1 + data["strategy_return"]).cumprod().iloc[-1] - 1) * 100, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe, 2),
        "outperformance_pct": round(total_strategy_return - total_market_return, 2),
        "total_turnover": round(total_turnover, 2),
        "total_costs_pct": round(total_costs * 100, 2),
        "transaction_cost_pct": transaction_cost_pct,
        "slippage_pct": slippage_pct,
    }
