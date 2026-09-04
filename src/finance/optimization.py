"""Portfolio Optimization module using Modern Portfolio Theory (Mean-Variance Optimization)."""

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def optimize_portfolio(price_df: pd.DataFrame, risk_free_rate: float = 0.04) -> dict:
    """Optimize portfolio weights to maximize the Sharpe Ratio.
    
    Args:
        price_df: DataFrame where each column is a ticker and rows are dates of adjusted close prices.
        risk_free_rate: Annualized risk-free rate (default 4%).
    """
    if price_df.empty or len(price_df.columns) < 1:
        raise ValueError("Price DataFrame must contain at least one asset.")

    # Drop columns with NaN values
    price_df = price_df.dropna(axis=1, how="any")
    if price_df.empty:
        raise ValueError("No assets remaining after dropping NaN values.")

    tickers = list(price_df.columns)
    num_assets = len(tickers)

    if num_assets == 1:
        return {
            "tickers": tickers,
            "weights": {tickers[0]: 1.0},
            "expected_return": 0.0,
            "volatility": 0.0,
            "sharpe_ratio": 0.0,
        }

    # Calculate daily log returns
    returns = np.log(price_df / price_df.shift(1)).dropna()
    mean_returns = returns.mean() * 252  # Annualized expected returns
    cov_matrix = returns.cov() * 252    # Annualized covariance matrix

    def portfolio_performance(weights):
        port_return = np.sum(mean_returns * weights)
        port_volatility = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        return port_return, port_volatility

    def negative_sharpe_ratio(weights):
        p_ret, p_vol = portfolio_performance(weights)
        if p_vol == 0:
            return 0
        return -(p_ret - risk_free_rate) / p_vol

    # Constraints and bounds
    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
    bounds = tuple((0.0, 1.0) for _ in range(num_assets))
    init_guess = num_assets * [1.0 / num_assets]

    result = minimize(
        negative_sharpe_ratio,
        init_guess,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
    )

    if not result.success:
        raise RuntimeError(f"Portfolio optimization failed: {result.message}")

    optimal_weights = result.x
    opt_return, opt_volatility = portfolio_performance(optimal_weights)
    sharpe = (opt_return - risk_free_rate) / opt_volatility if opt_volatility > 0 else 0.0

    weight_dict = {tickers[i]: round(float(optimal_weights[i]), 4) for i in range(num_assets)}

    return {
        "tickers": tickers,
        "weights": weight_dict,
        "expected_return": round(float(opt_return) * 100, 2),
        "volatility": round(float(opt_volatility) * 100, 2),
        "sharpe_ratio": round(float(sharpe), 2),
    }
