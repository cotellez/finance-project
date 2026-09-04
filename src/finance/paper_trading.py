"""Forward paper-trading / shadow portfolio simulation.

Runs agent-generated buy/sell signals in real time WITHOUT risking live
capital, validating strategy robustness and eliminating curve-fitting that
plagues historical backtests. State is persisted to a JSON shadow ledger.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

DEFAULT_LEDGER = Path("paper_trading.json")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _to_path(p):
    return p if isinstance(p, Path) else Path(p)


def load_ledger(db_path: Path = DEFAULT_LEDGER) -> dict:
    db_path = _to_path(db_path)
    if not db_path.exists():
        return {"cash": 100_000.0, "positions": {}, "fills": []}
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "cash": float(data.get("cash", 0.0)),
            "positions": data.get("positions", {}),
            "fills": data.get("fills", []),
        }
    except (json.JSONDecodeError, ValueError):
        return {"cash": 100_000.0, "positions": {}, "fills": []}


def save_ledger(ledger: dict, db_path: Path = DEFAULT_LEDGER) -> None:
    db_path = _to_path(db_path)
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)


def paper_buy(symbol: str, price: float, shares: float, db_path: Path = DEFAULT_LEDGER, max_position_pct: float = 25.0) -> dict:
    """Execute a simulated buy, enforcing position concentration limits."""
    ledger = load_ledger(db_path)
    symbol = symbol.upper()
    cost = price * shares
    portfolio_value = ledger["cash"] + sum(
        p["shares"] * p["avg_price"] for p in ledger["positions"].values()
    )

    # Circuit breaker: cap position notional.
    from finance.risk_guardrails import validate_position_size
    allowed = validate_position_size(cost, portfolio_value, max_position_pct)
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
        "price": round(float(price), 4),
        "shares": round(float(shares), 4),
    }
    ledger["fills"].append(fill)
    save_ledger(ledger, db_path)
    return fill


def paper_sell(symbol: str, price: float, shares: float | None = None, db_path: Path = DEFAULT_LEDGER) -> dict:
    """Execute a simulated sell (all shares if shares is None)."""
    ledger = load_ledger(db_path)
    symbol = symbol.upper()
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
        "price": round(float(price), 4),
        "shares": round(float(shares), 4),
    }
    ledger["fills"].append(fill)
    save_ledger(ledger, db_path)
    return fill


def paper_mark_to_market(prices: dict, db_path: Path = DEFAULT_LEDGER) -> dict:
    """Value the shadow portfolio at current prices."""
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
