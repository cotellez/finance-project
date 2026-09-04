"""Portfolio tracking, performance valuation, and asset allocation optimization."""

import json
from pathlib import Path
import pandas as pd
import numpy as np

DEFAULT_PORTFOLIO_DB = Path("portfolio.json")


def load_portfolio(db_path: Path = DEFAULT_PORTFOLIO_DB) -> list:
    """Load portfolio positions from JSON file."""
    if not db_path.exists():
        return []
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def save_portfolio(positions: list, db_path: Path = DEFAULT_PORTFOLIO_DB) -> None:
    """Save portfolio positions to JSON file."""
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)


def add_position(symbol: str, shares: float, cost_basis: float, db_path: Path = DEFAULT_PORTFOLIO_DB) -> dict:
    """Add or update a stock position in the portfolio."""
    if shares <= 0:
        raise ValueError("Shares must be greater than zero.")
    if cost_basis < 0:
        raise ValueError("Cost basis cannot be negative.")

    positions = load_portfolio(db_path)
    symbol = symbol.upper()

    # Check if symbol already exists
    existing = next((p for p in positions if p["symbol"] == symbol), None)
    if existing:
        # Average up/down cost basis
        total_shares = existing["shares"] + shares
        total_cost = (existing["shares"] * existing["cost_basis"]) + (shares * cost_basis)
        existing["shares"] = total_shares
        existing["cost_basis"] = round(total_cost / total_shares, 2)
        pos = existing
    else:
        pos = {
            "symbol": symbol,
            "shares": float(shares),
            "cost_basis": round(float(cost_basis), 2),
        }
        positions.append(pos)

    save_portfolio(positions, db_path)
    return pos


def calculate_portfolio_metrics(positions: list, current_prices: dict) -> dict:
    """Calculate total value, cost basis, unrealized P&L, and portfolio risk metrics.
    
    Safety guardrail: Fail explicitly or emit prominent warnings rather than defaulting missing price data to zero.
    """
    total_cost = 0.0
    total_value = 0.0
    items = []

    for p in positions:
        sym = p["symbol"]
        shares = p["shares"]
        basis = p["cost_basis"]
        cost = shares * basis
        total_cost += cost

        if sym not in current_prices or current_prices[sym] is None:
            raise ValueError(f"Missing current price for portfolio holding '{sym}'. Price data is required; zero defaults are prohibited.")

        curr_price = float(current_prices[sym])
        val = shares * curr_price
        total_value += val
        pnl = val - cost
        pnl_pct = (pnl / cost) * 100 if cost > 0 else 0.0

        items.append({
            "symbol": sym,
            "shares": shares,
            "cost_basis": basis,
            "current_price": curr_price,
            "total_cost": round(cost, 2),
            "current_value": round(val, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        })

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost) * 100 if total_cost > 0 else 0.0

    return {
        "total_cost": round(total_cost, 2),
        "total_value": round(total_value, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "positions": items,
    }
