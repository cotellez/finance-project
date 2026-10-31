"""Target-Weight Rebalance & Trade Generation Engine.

Computes portfolio allocation drift against target weights and generates
guardrail-compliant buy/sell trade recommendations respecting concentration caps.
"""

import math
from typing import Any, Dict, List, Optional

from finance.portfolio import load_portfolio
from finance.risk_guardrails import validate_position_size

# Known diversified index ETF tickers for cap classification
ETF_SYMBOLS = {"SCHD", "SPY", "SCHB", "ITOT", "VTI", "VOO", "QQQ", "XLRE", "XLB", "XLU", "VXUS"}


def calculate_portfolio_drift(
    positions: List[Dict[str, Any]],
    target_weights: Dict[str, float],
) -> List[Dict[str, Any]]:
    """Calculate allocation drift percentage for each holding vs target weights."""
    total_val = sum(
        p["shares"] * (p.get("current_price") or p["cost_basis"]) for p in positions
    )
    if total_val <= 0:
        return []

    drift_results = []
    # Process existing positions
    for pos in positions:
        sym = pos["symbol"].upper()
        mkt_val = pos["shares"] * (pos.get("current_price") or pos["cost_basis"])
        current_weight = (mkt_val / total_val) * 100.0
        target_pct = target_weights.get(sym, 0.0) * 100.0 if target_weights.get(sym, 0.0) <= 1.0 else target_weights.get(sym, 0.0)
        drift = current_weight - target_pct

        drift_results.append({
            "symbol": sym,
            "shares": pos["shares"],
            "current_value": round(mkt_val, 2),
            "current_weight": round(current_weight, 2),
            "target_weight": round(target_pct, 2),
            "drift_pct": round(drift, 2),
        })

    # Process target symbols not currently held
    existing_syms = {p["symbol"].upper() for p in positions}
    for sym, weight in target_weights.items():
        sym_upper = sym.upper()
        if sym_upper not in existing_syms:
            target_pct = weight * 100.0 if weight <= 1.0 else weight
            drift_results.append({
                "symbol": sym_upper,
                "shares": 0.0,
                "current_value": 0.0,
                "current_weight": 0.0,
                "target_weight": round(target_pct, 2),
                "drift_pct": round(-target_pct, 2),
            })

    return drift_results


def generate_rebalance_orders(
    positions: List[Dict[str, Any]],
    target_weights: Dict[str, float],
    available_cash: float = 0.0,
    max_position_pct: float = 25.0,
    max_etf_position_pct: float = 90.0,
) -> Dict[str, Any]:
    """Generate guardrail-compliant buy/sell trade recommendations to rebalance portfolio."""
    # Normalize target weights to sum to 1.0 if provided in percentages
    total_target_raw = sum(target_weights.values())
    if total_target_raw > 1.01:
        normalized_targets = {k: v / 100.0 for k, v in target_weights.items()}
    else:
        normalized_targets = {k: float(v) for k, v in target_weights.items()}

    # Calculate current portfolio market value
    positions_value = 0.0
    prices = {}
    for p in positions:
        sym = p["symbol"].upper()
        price = p.get("current_price") or p["cost_basis"]
        prices[sym] = price
        positions_value += p["shares"] * price

    projected_total_value = positions_value + available_cash
    if projected_total_value <= 0:
        return {"orders": [], "cash_remaining": available_cash, "warnings": ["Portfolio total value is 0."]}

    orders = []
    warnings = []

    # Calculate ideal target values
    for sym, target_weight in normalized_targets.items():
        sym = sym.upper()
        price = prices.get(sym, 100.0)  # Fallback price if new symbol
        is_etf = sym in ETF_SYMBOLS

        target_value = projected_total_value * target_weight
        
        # Enforce concentration caps via risk guardrails
        limit_pct = max_etf_position_pct if (is_etf and max_etf_position_pct is not None) else max_position_pct
        cap = projected_total_value * (limit_pct / 100.0)
        if target_value > cap:
            warnings.append(f"Cap adjusted for {sym}: target value exceeds {limit_pct}% cap.")
            target_value = cap

        # Calculate current value held
        existing_pos = next((p for p in positions if p["symbol"].upper() == sym), None)
        current_value = existing_pos["shares"] * prices[sym] if existing_pos else 0.0
        
        diff_value = target_value - current_value

        if abs(diff_value) < 1.0:  # Skip trivial adjustments < $1
            continue

        if diff_value > 0:
            action = "BUY"
            shares_delta = math.floor(diff_value / price)
            notional = shares_delta * price
        else:
            action = "SELL"
            shares_delta = math.floor(abs(diff_value) / price)
            notional = shares_delta * price

        if shares_delta > 0:
            orders.append({
                "symbol": sym,
                "action": action,
                "shares": shares_delta,
                "estimated_price": round(price, 2),
                "estimated_notional": round(notional, 2),
                "target_weight_pct": round(target_weight * 100.0, 2),
            })

    return {
        "projected_portfolio_value": round(projected_total_value, 2),
        "available_cash": round(available_cash, 2),
        "orders": orders,
        "warnings": warnings,
    }
