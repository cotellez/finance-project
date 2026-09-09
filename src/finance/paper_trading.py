"""Forward paper-trading / shadow portfolio simulation.

Runs agent-generated buy/sell signals in real time WITHOUT risking live
capital, validating strategy robustness and eliminating curve-fitting that
plagues historical backtests. State is persisted to a JSON shadow ledger.
"""

import json
import math
from pathlib import Path
from datetime import datetime, timezone
from finance.jsonstore import (
    PROJECT_ROOT,
    FileLock,
    atomic_write_json,
    resolve_path,
)

DEFAULT_LEDGER = PROJECT_ROOT / "paper_trading.json"
DEFAULT_STARTING_CAPITAL = 2000.0


def _now():
    return datetime.now(timezone.utc).isoformat()


def initialize_ledger(
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
    db_path: Path | None = None,
) -> dict:
    """Reset the shadow ledger to a fresh account with the given starting capital.

    Defaults to $2,000 so small-account realities (fees, position sizing,
    concentration risk) are forced into decisions rather than the detached
    $100,000 psychology of a default sim.
    """
    db_path = resolve_path(db_path, DEFAULT_LEDGER)
    try:
        starting_capital = float(starting_capital)
    except (TypeError, ValueError):
        raise ValueError("Starting capital must be a number.")
    if not math.isfinite(starting_capital) or starting_capital <= 0:
        raise ValueError("Starting capital must be a finite number greater than zero.")
    ledger = {"cash": float(starting_capital), "positions": {}, "fills": []}
    save_ledger(
        ledger,
        db_path,
        audit=True,
        audit_action="paper_reset",
        audit_detail=f"Reset paper account to ${starting_capital:,.2f}",
    )
    return ledger


def load_ledger(db_path: Path | None = None) -> dict:
    """Load and schema-validate the shadow ledger.

    Fails loudly on a corrupt or malformed ledger instead of silently
    resetting the shadow account to a fresh one (which could make a
    mid-session wrap-up read the wrong state as if it were real).
    """
    db_path = resolve_path(db_path, DEFAULT_LEDGER)
    if not db_path.exists():
        return {"cash": DEFAULT_STARTING_CAPITAL, "positions": {}, "fills": []}
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Paper ledger '{db_path}' is corrupted (invalid JSON): {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"Paper ledger '{db_path}' must contain a JSON object.")
    cash = data.get("cash", 0.0)
    if not isinstance(cash, (int, float)) or not math.isfinite(float(cash)):
        raise ValueError(f"Paper ledger '{db_path}' has an invalid 'cash' value: {cash!r}.")
    positions = data.get("positions", {})
    if not isinstance(positions, dict):
        raise ValueError(f"Paper ledger '{db_path}' has an invalid 'positions' value.")
    for sym, pos in positions.items():
        if not isinstance(pos, dict):
            raise ValueError(f"Paper ledger '{db_path}' has a non-object position for '{sym}'.")
        shares = pos.get("shares")
        avg = pos.get("avg_price")
        if not isinstance(shares, (int, float)) or not math.isfinite(float(shares)) or float(shares) < 0:
            raise ValueError(f"Paper ledger '{db_path}' has an invalid 'shares' for position '{sym}'.")
        if not isinstance(avg, (int, float)) or not math.isfinite(float(avg)) or float(avg) < 0:
            raise ValueError(f"Paper ledger '{db_path}' has an invalid 'avg_price' for position '{sym}'.")
    fills = data.get("fills", [])
    if not isinstance(fills, list):
        raise ValueError(f"Paper ledger '{db_path}' has an invalid 'fills' value.")
    return {"cash": float(cash), "positions": positions, "fills": fills}


def save_ledger(
    ledger: dict,
    db_path: Path | None = None,
    *,
    audit: bool = False,
    audit_action: str = "paper_write",
    audit_detail: str = "",
) -> None:
    db_path = resolve_path(db_path, DEFAULT_LEDGER)
    atomic_write_json(
        db_path,
        ledger,
        audit=audit,
        audit_action=audit_action,
        audit_detail=audit_detail,
    )


def paper_buy(symbol: str, price: float, shares: float, db_path: Path | None = None, max_position_pct: float = 25.0,
              max_etf_position_pct: float | None = None, is_etf: bool = False) -> dict:
    """Execute a simulated buy, enforcing position concentration limits."""
    db_path = resolve_path(db_path, DEFAULT_LEDGER)
    try:
        price = float(price)
        shares = float(shares)
    except (TypeError, ValueError):
        raise ValueError("Price and shares must be numbers.")
    if not math.isfinite(price) or price <= 0:
        raise ValueError("Price must be a finite number greater than zero.")
    if not math.isfinite(shares) or shares <= 0:
        raise ValueError("Shares must be a finite number greater than zero.")

    symbol = symbol.upper()

    with FileLock(db_path):
        ledger = load_ledger(db_path)
        cost = price * shares
        portfolio_value = ledger["cash"] + sum(
            p["shares"] * p["avg_price"] for p in ledger["positions"].values()
        )

        # Circuit breaker: cap position notional (asymmetric ETF cap supported).
        from finance.risk_guardrails import validate_position_size
        allowed = validate_position_size(cost, portfolio_value, max_position_pct,
                                         max_etf_position_pct=max_etf_position_pct, is_etf=is_etf)
        if allowed < cost:
            shares = allowed / price if price > 0 else 0.0
            cost = price * shares

        if cost > ledger["cash"]:
            shares = ledger["cash"] / price if price > 0 else 0.0
            cost = price * shares

        ledger["cash"] -= cost
        if symbol in ledger["positions"]:
            pos = ledger["positions"][symbol]
            total_shares = pos["shares"] + shares
            total_cost = pos["shares"] * pos["avg_price"] + cost
            pos["shares"] = total_shares
            pos["avg_price"] = total_cost / total_shares if total_shares > 0 else 0.0
        else:
            ledger["positions"][symbol] = {"shares": shares, "avg_price": price}

        fill = {
            "ts": _now(),
            "action": "BUY",
            "symbol": symbol,
            "price": round(price, 4),
            "shares": round(shares, 4),
        }
        ledger["fills"].append(fill)
        save_ledger(
            ledger,
            db_path,
            audit=True,
            audit_action="paper_buy",
            audit_detail=f"BUY {symbol} {shares:.4f} @ {price:.4f}",
        )
    return fill


def paper_sell(symbol: str, price: float, shares: float | None = None, db_path: Path | None = None) -> dict:
    """Execute a simulated sell (all shares if shares is None)."""
    db_path = resolve_path(db_path, DEFAULT_LEDGER)
    try:
        price = float(price)
    except (TypeError, ValueError):
        raise ValueError("Price must be a number.")
    if not math.isfinite(price) or price <= 0:
        raise ValueError("Price must be a finite number greater than zero.")
    if shares is not None:
        try:
            shares = float(shares)
        except (TypeError, ValueError):
            raise ValueError("Shares must be a number.")
        if not math.isfinite(shares) or shares <= 0:
            raise ValueError("Shares must be a finite number greater than zero.")

    symbol = symbol.upper()

    with FileLock(db_path):
        ledger = load_ledger(db_path)
        pos = ledger["positions"].get(symbol)
        if not pos:
            return {"ts": _now(), "action": "SELL", "symbol": symbol, "price": 0.0, "shares": 0.0, "error": "no position"}

        shares = pos["shares"] if shares is None else min(shares, pos["shares"])
        proceeds = price * shares
        ledger["cash"] += proceeds
        pos["shares"] -= shares
        if pos["shares"] <= 1e-9:
            del ledger["positions"][symbol]

        fill = {
            "ts": _now(),
            "action": "SELL",
            "symbol": symbol,
            "price": round(price, 4),
            "shares": round(shares, 4),
        }
        ledger["fills"].append(fill)
        save_ledger(
            ledger,
            db_path,
            audit=True,
            audit_action="paper_sell",
            audit_detail=f"SELL {symbol} {shares:.4f} @ {price:.4f}",
        )
    return fill


def paper_mark_to_market(prices: dict, db_path: Path | None = None) -> dict:
    """Value the shadow portfolio at current prices."""
    db_path = resolve_path(db_path, DEFAULT_LEDGER)
    ledger = load_ledger(db_path)
    total_equity = ledger["cash"]
    positions_out = []

    for symbol, pos in ledger["positions"].items():
        if symbol not in prices:
            raise ValueError(f"Missing current price for paper position '{symbol}'.")
        price = prices[symbol]
        mv = pos["shares"] * price
        total_equity += mv
        cost = pos["shares"] * pos["avg_price"]
        positions_out.append(
            {
                "symbol": symbol,
                "shares": pos["shares"],
                "avg_price": pos["avg_price"],
                "current_price": price,
                "market_value": round(mv, 2),
                "pnl": round(mv - cost, 2),
                "pnl_pct": round((mv - cost) / cost * 100, 2) if cost > 0 else 0.0,
            }
        )

    return {
        "cash": round(ledger["cash"], 2),
        "positions_value": round(total_equity - ledger["cash"], 2),
        "total_equity": round(total_equity, 2),
        "positions": positions_out,
    }