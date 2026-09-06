"""Portfolio tracking, performance valuation, and asset allocation optimization."""

import json
import math
from pathlib import Path
import pandas as pd
import numpy as np
from finance.jsonstore import (
    PROJECT_ROOT,
    FileLock,
    atomic_write_json,
    resolve_path,
)

DEFAULT_PORTFOLIO_DB = PROJECT_ROOT / "portfolio.json"


def load_portfolio(db_path: Path | None = None) -> list:
    """Load and schema-validate portfolio positions from JSON file."""
    db_path = resolve_path(db_path, DEFAULT_PORTFOLIO_DB)
    if not db_path.exists():
        return []
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Portfolio database '{db_path}' is corrupted (invalid JSON): {e}") from e
    if not isinstance(data, list):
        raise ValueError(f"Portfolio database '{db_path}' must contain a JSON list of positions.")
    for p in data:
        if not isinstance(p, dict):
            raise ValueError(f"Portfolio database '{db_path}' contains a non-object position.")
        if not isinstance(p.get("symbol"), str) or not p["symbol"].strip():
            raise ValueError(f"Portfolio database '{db_path}' contains a position with an invalid 'symbol'.")
        shares = p.get("shares")
        if not isinstance(shares, (int, float)) or not math.isfinite(float(shares)) or float(shares) <= 0:
            raise ValueError(f"Portfolio database '{db_path}' contains a position with invalid 'shares': {shares!r}.")
        basis = p.get("cost_basis")
        if not isinstance(basis, (int, float)) or not math.isfinite(float(basis)) or float(basis) < 0:
            raise ValueError(f"Portfolio database '{db_path}' contains a position with invalid 'cost_basis': {basis!r}.")
    return data


def save_portfolio(
    positions: list,
    db_path: Path | None = None,
    *,
    audit: bool = False,
    audit_action: str = "portfolio_write",
    audit_detail: str = "",
) -> None:
    """Save portfolio positions to JSON file (atomic write)."""
    db_path = resolve_path(db_path, DEFAULT_PORTFOLIO_DB)
    atomic_write_json(
        db_path,
        positions,
        audit=audit,
        audit_action=audit_action,
        audit_detail=audit_detail,
    )


def add_position(symbol: str, shares: float, cost_basis: float, db_path: Path | None = None) -> dict:
    """Add or update a stock position in the portfolio."""
    db_path = resolve_path(db_path, DEFAULT_PORTFOLIO_DB)
    try:
        shares = float(shares)
        cost_basis = float(cost_basis)
    except (TypeError, ValueError):
        raise ValueError("Shares and cost basis must be numbers.")
    if not math.isfinite(shares) or shares <= 0:
        raise ValueError("Shares must be a finite number greater than zero.")
    if not math.isfinite(cost_basis) or cost_basis < 0:
        raise ValueError("Cost basis must be a finite, non-negative number.")
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("Symbol must be a non-empty string.")

    symbol = symbol.upper()

    with FileLock(db_path):
        positions = load_portfolio(db_path)

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
                "shares": shares,
                "cost_basis": round(cost_basis, 2),
            }
            positions.append(pos)

        save_portfolio(
            positions,
            db_path,
            audit=True,
            audit_action="portfolio_position",
            audit_detail=f"{symbol} {shares} shares @ ${cost_basis:.2f}",
        )
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