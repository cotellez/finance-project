"""Sandbox and Prediction Watchlist module.

Strictly separated from core portfolio and paper trading systems.
Used exclusively as an intuition-training sandbox for logging future stock predictions
and tracking their performance over time against current prices and the S&P 500 benchmark.
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from finance.jsonstore import (
    PROJECT_ROOT,
    FileLock,
    atomic_write_json,
    resolve_path,
)
from finance.stock_data import fetch_daily_with_fallback

DEFAULT_WATCHLIST = PROJECT_ROOT / "sandbox_predictions.json"
_VALID_TYPES = ("winner", "loser")


def load_watchlist(db_path: Path | None = None) -> list:
    """Load sandbox prediction watchlist from JSON file."""
    db_path = resolve_path(db_path, DEFAULT_WATCHLIST)
    if not db_path.exists():
        return []
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Watchlist database '{db_path}' is corrupted (invalid JSON): {e}") from e
    if not isinstance(data, list):
        raise ValueError(f"Watchlist database '{db_path}' must contain a JSON list.")
    return data


def save_watchlist(watchlist: list, db_path: Path | None = None) -> None:
    """Save sandbox prediction watchlist atomically."""
    db_path = resolve_path(db_path, DEFAULT_WATCHLIST)
    atomic_write_json(db_path, watchlist, audit=True, audit_action="watchlist_write", audit_detail="Update sandbox watchlist")


def add_prediction(
    symbol: str,
    pred_type: str,
    hypothesis: str,
    horizon_days: int = 30,
    db_path: Path | None = None,
) -> dict:
    """Add a prediction to the sandbox watchlist."""
    db_path = resolve_path(db_path, DEFAULT_WATCHLIST)
    symbol = symbol.upper().strip()
    pred_type = pred_type.lower().strip()
    if pred_type not in _VALID_TYPES:
        raise ValueError(f"Prediction type must be one of {_VALID_TYPES}, got '{pred_type}'.")
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        raise ValueError("Hypothesis must be a non-empty string.")
    try:
        horizon_days = int(horizon_days)
    except (TypeError, ValueError):
        raise ValueError("Horizon days must be an integer.")
    if horizon_days <= 0:
        raise ValueError("Horizon days must be greater than zero.")

    # Fetch initial price for symbol and SPY benchmark
    df_sym = fetch_daily_with_fallback(symbol, period="5d")
    if df_sym.empty or "adjusted_close" not in df_sym.columns:
        raise ValueError(f"Could not fetch initial price data for symbol '{symbol}'.")
    initial_price = float(df_sym["adjusted_close"].iloc[-1])

    df_spy = fetch_daily_with_fallback("SPY", period="5d")
    initial_spy_price = float(df_spy["adjusted_close"].iloc[-1]) if not df_spy.empty and "adjusted_close" in df_spy.columns else 0.0

    pred_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "_" + symbol

    record = {
        "id": pred_id,
        "symbol": symbol,
        "type": pred_type,
        "hypothesis": hypothesis.strip(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "initial_price": initial_price,
        "initial_spy_price": initial_spy_price,
        "horizon_days": horizon_days,
        "status": "active",
    }

    with FileLock(db_path):
        watchlist = load_watchlist(db_path)
        watchlist.append(record)
        save_watchlist(watchlist, db_path)

    return record


def evaluate_watchlist(db_path: Path | None = None) -> list:
    """Evaluate all sandbox predictions against current market prices and SPY."""
    db_path = resolve_path(db_path, DEFAULT_WATCHLIST)
    watchlist = load_watchlist(db_path)
    if not watchlist:
        return []

    # Cache SPY current price if possible
    df_spy = fetch_daily_with_fallback("SPY", period="5d")
    current_spy_price = float(df_spy["adjusted_close"].iloc[-1]) if not df_spy.empty and "adjusted_close" in df_spy.columns else None

    evaluations = []
    for item in watchlist:
        symbol = item["symbol"]
        initial_price = item["initial_price"]
        initial_spy = item["initial_spy_price"]
        pred_type = item["type"]
        timestamp_str = item["timestamp"]

        # Calculate days elapsed
        try:
            dt = datetime.fromisoformat(timestamp_str)
            days_elapsed = (datetime.now(timezone.utc) - dt).days
        except Exception:
            days_elapsed = 0

        # Fetch current price
        df_sym = fetch_daily_with_fallback(symbol, period="5d")
        current_price = float(df_sym["adjusted_close"].iloc[-1]) if not df_sym.empty and "adjusted_close" in df_sym.columns else initial_price

        # Price change pct
        price_change_pct = ((current_price - initial_price) / initial_price) * 100 if initial_price > 0 else 0.0

        # SPY change pct
        spy_change_pct = 0.0
        if current_spy_price is not None and initial_spy > 0:
            spy_change_pct = ((current_spy_price - initial_spy) / initial_spy) * 100

        relative_return_pct = price_change_pct - spy_change_pct

        # Check correctness based on prediction type
        if pred_type == "winner":
            is_correct = price_change_pct > 0
        else:
            is_correct = price_change_pct < 0

        evaluations.append({
            "id": item["id"],
            "symbol": symbol,
            "type": pred_type,
            "hypothesis": item["hypothesis"],
            "timestamp": timestamp_str,
            "days_elapsed": days_elapsed,
            "horizon_days": item["horizon_days"],
            "initial_price": round(initial_price, 2),
            "current_price": round(current_price, 2),
            "price_change_pct": round(price_change_pct, 2),
            "spy_change_pct": round(spy_change_pct, 2),
            "relative_return_pct": round(relative_return_pct, 2),
            "is_correct": is_correct,
            "status": "expired" if days_elapsed > item["horizon_days"] else "active",
        })

    return evaluations
