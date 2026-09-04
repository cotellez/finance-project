"""Multi-factor stock screening and scoring engine."""

import pandas as pd
import numpy as np


def score_stocks(stock_data_dict: dict) -> list:
    """Score a dictionary of stock DataFrames based on Momentum and Volatility.
    
    Args:
        stock_data_dict: Dict mapping ticker symbols to their historical DataFrames.
    """
    scores = []

    for ticker, df in stock_data_dict.items():
        if df.empty or len(df) < 60:
            continue

        prices = df["adjusted_close"]
        
        # Momentum: 3-month (approx 63 trading days) return
        mom_63 = float((prices.iloc[-1] / prices.iloc[-63]) - 1) * 100 if len(prices) >= 63 else 0.0
        
        # 1-month (approx 21 trading days) return
        mom_21 = float((prices.iloc[-1] / prices.iloc[-21]) - 1) * 100 if len(prices) >= 21 else 0.0

        # Volatility: annualized volatility over last 60 days
        log_rets = np.log(prices / prices.shift(1)).dropna()
        vol_60 = float(log_rets.iloc[-60:].std() * np.sqrt(252) * 100) if len(log_rets) >= 60 else 0.0

        # Composite score (higher momentum, lower volatility is better)
        # e.g., Composite = (0.6 * Mom63) + (0.4 * Mom21) - (0.2 * Vol60)
        composite_score = (0.6 * mom_63) + (0.4 * mom_21) - (0.2 * vol_60)

        scores.append({
            "ticker": ticker.upper(),
            "latest_price": round(float(prices.iloc[-1]), 2),
            "momentum_3m": round(mom_63, 2),
            "momentum_1m": round(mom_21, 2),
            "annualized_volatility": round(vol_60, 2),
            "composite_score": round(composite_score, 2),
        })

    # Sort by composite score descending
    scores.sort(key=lambda x: x["composite_score"], reverse=True)
    return scores
