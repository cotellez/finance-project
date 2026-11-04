"""Sector rotation & macro-regime engine.

Ranks the 11 SPDR sector ETFs against SPY on multi-horizon relative
strength, classifies each sector's trend state, and overlays a FRED-based
macro regime — the top-down lens used to decide where in the market to
look for portfolio gaps and dark-horse candidates.
"""

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from finance.indicators import calculate_sma
from finance.logging_setup import get_logger
from finance.stock_data import fetch_daily

logger = get_logger(__name__)

BENCHMARK = "SPY"
HISTORY_PERIOD = "2y"
MIN_RS_BARS = 63
SECTOR_ETFS: Dict[str, str] = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Healthcare",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLP": "Consumer Staples",
    "XLY": "Consumer Discretionary",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLB": "Basic Materials",
    "XLC": "Communication Services",
}
RS_WINDOWS = {"1m": 21, "3m": 63, "6m": 126}
STRONG_BULLISH_RS = 0.03
BEARISH_RS = -0.03
FRED_CURVE_SERIES = "T10Y2Y"
FRED_TEN_YEAR = "DGS10"


def _period_return(df: pd.DataFrame, window: int, price_col: str = "adjusted_close") -> Optional[float]:
    """Trailing `window`-day price return; None when history is too short."""
    if df is None or df.empty or len(df) < window + 1:
        return None
    start = float(df[price_col].iloc[-window - 1])
    end = float(df[price_col].iloc[-1])
    if start <= 0 or not math.isfinite(start) or not math.isfinite(end):
        return None
    return end / start - 1.0


def compute_relative_strength(
    df: pd.DataFrame, benchmark_df: pd.DataFrame
) -> Dict[str, Optional[float]]:
    """Sector return minus benchmark return over each RS horizon."""
    rs: Dict[str, Optional[float]] = {}
    for name, window in RS_WINDOWS.items():
        s = _period_return(df, window)
        b = _period_return(benchmark_df, window)
        rs[f"rs_{name}"] = (s - b) if s is not None and b is not None else None
    return rs


def compute_trend_state(df: pd.DataFrame) -> Dict[str, Any]:
    """Distance-to-SMA trend classification for a price frame."""
    if df is None or df.empty or "adjusted_close" not in df.columns:
        raise ValueError("Price data with adjusted_close required for trend state.")

    close = float(df["adjusted_close"].iloc[-1])
    sma_50 = calculate_sma(df, 50).iloc[-1] if len(df) >= 50 else float("nan")
    sma_200 = calculate_sma(df, 200).iloc[-1] if len(df) >= 200 else float("nan")
    sma_50_v = None if pd.isna(sma_50) else float(sma_50)
    sma_200_v = None if pd.isna(sma_200) else float(sma_200)

    above_50 = close > sma_50_v if sma_50_v is not None else None
    above_200 = close > sma_200_v if sma_200_v is not None else None
    death_cross = (
        sma_50_v is not None and sma_200_v is not None and sma_50_v < sma_200_v
    )

    if above_200 is False and death_cross:
        trend = "Strong Bearish"
    elif above_50 and above_200 and not death_cross:
        trend = "Strong Bullish"
    elif above_50:
        trend = "Bullish"
    elif above_50 is False:
        trend = "Bearish"
    else:
        trend = "Neutral"

    return {
        "close": round(close, 2),
        "sma_50": round(sma_50_v, 2) if sma_50_v is not None else None,
        "sma_200": round(sma_200_v, 2) if sma_200_v is not None else None,
        "above_sma_50": above_50,
        "above_sma_200": above_200,
        "death_cross": death_cross,
        "trend": trend,
    }


def classify_sector(rs_composite: Optional[float], trend: Dict[str, Any]) -> str:
    """Map composite relative strength + trend state to a rotation label."""
    if rs_composite is None:
        return "Unknown"
    if trend.get("death_cross") and trend.get("above_sma_200") is False:
        return "Bearish Rotation"
    if rs_composite >= STRONG_BULLISH_RS and trend.get("above_sma_200"):
        return "Strong Bullish"
    if rs_composite > 0:
        return "Bullish"
    if rs_composite <= BEARISH_RS:
        return "Bearish Rotation"
    return "Neutral"


def rank_sectors(period: str = HISTORY_PERIOD) -> List[Dict[str, Any]]:
    """Rank all sector ETFs by multi-horizon relative strength vs SPY."""
    benchmark_df = fetch_daily(BENCHMARK, period=period)
    if benchmark_df is None or benchmark_df.empty:
        raise ValueError("Benchmark SPY data unavailable; cannot rank sectors.")

    rows: List[Dict[str, Any]] = []
    for symbol, name in SECTOR_ETFS.items():
        df = fetch_daily(symbol, period=period)
        if df is None or df.empty or len(df) < MIN_RS_BARS:
            logger.warning("Skipping %s (%s): insufficient history.", symbol, name)
            continue
        try:
            rs = compute_relative_strength(df, benchmark_df)
            trend = compute_trend_state(df)
        except ValueError as e:
            logger.warning("Skipping %s: %s", symbol, e)
            continue

        values = [v for v in rs.values() if v is not None]
        rs_composite = round(sum(values) / len(values), 6) if values else None
        score = rs_composite if rs_composite is not None else 0.0
        if trend["above_sma_200"]:
            score += 0.02
        if trend["death_cross"]:
            score -= 0.02

        rows.append(
            {
                "symbol": symbol,
                "sector": name,
                "rs": {k: (round(v, 6) if v is not None else None) for k, v in rs.items()},
                "rs_composite": rs_composite,
                "trend": trend,
                "score": round(score, 6),
                "classification": classify_sector(rs_composite, trend),
            }
        )

    rows.sort(key=lambda r: r["score"], reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


def classify_macro_regime(db_path=None) -> Dict[str, Any]:
    """Classify the macro regime from FRED yield-curve + rate direction.

    Degrades to regime='Unknown' when FRED is unreachable so sector
    ranking never hard-fails on macro availability.
    """
    out: Dict[str, Any] = {"regime": "Unknown", "details": {}, "source": "fred"}
    try:
        from finance.fred import get_latest_observation

        # Only forward db_path when provided: passing None explicitly would
        # override fred's DEFAULT_CACHE_DB and crash the SQLite cache lookup.
        fred_kwargs = {"db_path": db_path} if db_path is not None else {}

        curve = get_latest_observation(FRED_CURVE_SERIES, **fred_kwargs)
        curve_val = float(curve["value"])
        out["details"]["yield_curve_2s10s"] = {
            "value": curve_val,
            "date": curve.get("date"),
            "change": curve.get("change"),
        }

        try:
            ten = get_latest_observation(FRED_TEN_YEAR, **fred_kwargs)
            ten_change = ten.get("change")
            out["details"]["ten_year"] = {
                "value": float(ten["value"]),
                "date": ten.get("date"),
                "change": ten_change,
            }
            rate_tone = (
                "rising"
                if ten_change is not None and float(ten_change) > 0.15
                else "falling"
                if ten_change is not None and float(ten_change) < -0.15
                else "stable"
            )
        except Exception:
            rate_tone = "unknown"

        if curve_val < 0:
            regime = "Inverted Curve (Restrictive)"
            risk_tone = "Risk-Off"
        elif curve_val < 0.25:
            regime = "Flat Curve (Late Cycle)"
            risk_tone = "Cautious"
        else:
            regime = "Positive Curve (Expansion)"
            risk_tone = "Risk-On"

        out["regime"] = regime
        out["details"]["rate_tone"] = rate_tone
        out["details"]["risk_tone"] = risk_tone
    except Exception as e:
        out["regime"] = "Unknown"
        out["note"] = f"FRED unavailable: {e}"
    return out


def build_sector_report(
    period: str = HISTORY_PERIOD,
    include_macro: bool = True,
    db_path=None,
) -> Dict[str, Any]:
    """Full top-down report: macro regime + ranked sectors."""
    ranked = rank_sectors(period=period)
    regime = classify_macro_regime(db_path=db_path) if include_macro else {"regime": "Skipped"}
    return {
        "generated_at": datetime.now().isoformat(),
        "benchmark": BENCHMARK,
        "macro_regime": regime,
        "sectors": ranked,
    }
