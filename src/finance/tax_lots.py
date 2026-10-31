"""Tax-lot & capital gains tracking module (FIFO/LIFO/Specific ID).

Provides secure JSON storage with file locking, audit trail, and capital gains
realization calculations.
"""

import math
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from finance.jsonstore import PROJECT_ROOT, FileLock, atomic_write_json, resolve_path

DEFAULT_TAX_LOTS_DB = PROJECT_ROOT / "tax_lots.json"


def load_tax_lots(db_path: Path | str | None = None) -> List[Dict[str, Any]]:
    """Load and validate tax lots from JSON file."""
    db_path = resolve_path(db_path, DEFAULT_TAX_LOTS_DB)
    if not Path(db_path).exists():
        return []
    try:
        import json

        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"Tax lots database '{db_path}' is corrupted: {e}") from e

    if not isinstance(data, list):
        raise ValueError(f"Tax lots database '{db_path}' must contain a list.")
    
    for lot in data:
        if not isinstance(lot, dict):
            raise ValueError("Invalid tax lot record format.")
        if not isinstance(lot.get("symbol"), str) or not lot["symbol"].strip():
            raise ValueError("Invalid symbol in tax lot.")
        shares = lot.get("shares")
        if not isinstance(shares, (int, float)) or not math.isfinite(float(shares)) or float(shares) < 0:
            raise ValueError("Invalid shares in tax lot.")
        price = lot.get("purchase_price")
        if not isinstance(price, (int, float)) or not math.isfinite(float(price)) or float(price) < 0:
            raise ValueError("Invalid purchase price in tax lot.")
    return data


def save_tax_lots(
    lots: List[Dict[str, Any]],
    db_path: Path | str | None = None,
    *,
    audit: bool = True,
    audit_action: str = "tax_lots_write",
    audit_detail: str = "",
) -> None:
    """Save tax lots atomically with audit trail."""
    db_path = resolve_path(db_path, DEFAULT_TAX_LOTS_DB)
    atomic_write_json(
        db_path,
        lots,
        audit=audit,
        audit_action=audit_action,
        audit_detail=audit_detail,
    )


def add_tax_lot(
    symbol: str,
    shares: float,
    purchase_price: float,
    purchase_date: Optional[str] = None,
    fees: float = 0.0,
    db_path: Path | str | None = None,
) -> Dict[str, Any]:
    """Add a new purchase tax lot."""
    symbol = symbol.upper().strip()
    try:
        shares = float(shares)
        purchase_price = float(purchase_price)
        fees = float(fees)
    except (TypeError, ValueError):
        raise ValueError("Shares, purchase price, and fees must be numbers.")

    if not math.isfinite(shares) or shares <= 0:
        raise ValueError("Shares must be greater than zero.")
    if not math.isfinite(purchase_price) or purchase_price < 0:
        raise ValueError("Purchase price cannot be negative.")
    if not math.isfinite(fees) or fees < 0:
        raise ValueError("Fees cannot be negative.")

    if not purchase_date:
        purchase_date = date.today().isoformat()
    else:
        try:
            date.fromisoformat(purchase_date)
        except (TypeError, ValueError):
            raise ValueError("Purchase date must be in YYYY-MM-DD format.")

    db_path = resolve_path(db_path, DEFAULT_TAX_LOTS_DB)
    lot = {
        "symbol": symbol,
        "shares": round(shares, 6),
        "purchase_price": round(purchase_price, 4),
        "purchase_date": purchase_date,
        "fees": round(fees, 2),
    }

    with FileLock(db_path):
        lots = load_tax_lots(db_path)
        lots.append(lot)
        save_tax_lots(
            lots,
            db_path,
            audit=True,
            audit_action="add_tax_lot",
            audit_detail=f"Bought {symbol}: {shares} sh @ ${purchase_price:.2f}",
        )
    return lot


def realize_tax_lots(
    symbol: str,
    shares_sold: float,
    sale_price: float,
    sale_date: Optional[str] = None,
    method: Literal["FIFO", "LIFO"] = "FIFO",
    db_path: Path | str | None = None,
) -> Dict[str, Any]:
    """Realize shares against open tax lots using FIFO or LIFO method.

    Returns summary of realized capital gains/losses and updated lots.
    """
    symbol = symbol.upper().strip()
    try:
        shares_sold = float(shares_sold)
        sale_price = float(sale_price)
    except (TypeError, ValueError):
        raise ValueError("Shares sold and sale price must be numbers.")

    if not math.isfinite(shares_sold) or shares_sold <= 0:
        raise ValueError("Shares sold must be greater than zero.")
    if not math.isfinite(sale_price) or sale_price < 0:
        raise ValueError("Sale price cannot be negative.")

    if not sale_date:
        sale_date = date.today().isoformat()

    db_path = resolve_path(db_path, DEFAULT_TAX_LOTS_DB)

    with FileLock(db_path):
        lots = load_tax_lots(db_path)
        symbol_lots = [l for l in lots if l["symbol"] == symbol and l["shares"] > 0]
        
        # Sort lots by date
        if method == "FIFO":
            symbol_lots.sort(key=lambda x: x["purchase_date"])
        elif method == "LIFO":
            symbol_lots.sort(key=lambda x: x["purchase_date"], reverse=True)
        else:
            raise ValueError("Method must be 'FIFO' or 'LIFO'.")

        total_open_shares = sum(l["shares"] for l in symbol_lots)
        if shares_sold > total_open_shares:
            raise ValueError(
                f"Cannot sell {shares_sold} shares of {symbol}: only {total_open_shares} open shares available."
            )

        remaining_to_sell = shares_sold
        realized_gains = 0.0
        total_cost_basis = 0.0
        lots_affected = []

        for lot in symbol_lots:
            if remaining_to_sell <= 0:
                break
            take_shares = min(lot["shares"], remaining_to_sell)
            cost = take_shares * lot["purchase_price"]
            proceeds = take_shares * sale_price
            gain = proceeds - cost

            realized_gains += gain
            total_cost_basis += cost
            remaining_to_sell -= take_shares

            lot["shares"] = round(lot["shares"] - take_shares, 6)
            lots_affected.append({
                "purchase_date": lot["purchase_date"],
                "purchase_price": lot["purchase_price"],
                "shares_realized": take_shares,
                "gain_loss": round(gain, 2),
            })

        # Remove fully depleted lots
        updated_lots = [l for l in lots if l["shares"] > 0]

        save_tax_lots(
            updated_lots,
            db_path,
            audit=True,
            audit_action="realize_tax_lots",
            audit_detail=f"Sold {symbol}: {shares_sold} sh @ ${sale_price:.2f} ({method}), gain: ${realized_gains:.2f}",
        )

    return {
        "symbol": symbol,
        "shares_sold": shares_sold,
        "sale_price": sale_price,
        "sale_date": sale_date,
        "method": method,
        "total_proceeds": round(shares_sold * sale_price, 2),
        "total_cost_basis": round(total_cost_basis, 2),
        "realized_gain_loss": round(realized_gains, 2),
        "lots_affected": lots_affected,
    }
