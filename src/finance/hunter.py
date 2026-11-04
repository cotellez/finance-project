"""Dark-horse discovery engine.

Screens the market for momentum/volume breakouts, applies GARP fundamental
gates and the core philosophy gate — a single name must beat its sector ETF
on BOTH Sharpe and growth to qualify. Pruned symbols are skipped entirely,
and qualified candidates graduate through paper trading before real capital.
"""

import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from finance.logging_setup import get_logger
from finance.pruner import (
    fetch_ticker_info,
    fundamental_veto_reasons,
    load_prune_list,
)
from finance.sector_rotation import rank_sectors
from finance.stock_data import fetch_daily

logger = get_logger(__name__)

SCREEN_TTL_HOURS = 24
VOLUME_SURGE_MULTIPLE = 2.0
VOLUME_AVG_WINDOW = 30
BREAKOUT_LOOKBACK = 252
BREAKOUT_TOLERANCE = 0.98
HISTORY_PERIOD = "1y"
MIN_CANDIDATE_BARS = 60
GARP_MIN_ROE = 0.15
GARP_MAX_PEG = 1.5
SHARPE_RF = 0.04
COMPARISON_WINDOW = 126

SECTOR_NAME_TO_ETF: Dict[str, str] = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Financials": "XLF",
    "Healthcare": "XLV",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Consumer Defensive": "XLP",
    "Consumer Cyclical": "XLY",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Basic Materials": "XLB",
    "Communication Services": "XLC",
}

FALLBACK_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA",
    "JPM", "BAC", "WFC", "GS",
    "UNH", "LLY", "JNJ", "PFE", "ABBV",
    "XOM", "CVX", "COP",
    "CAT", "DE", "HON", "UNP", "GE",
    "PG", "KO", "PEP", "COST", "WMT",
    "NEE", "DUK", "SO",
    "PLD", "AMT", "SPG",
    "LIN", "APD", "SHW",
    "DIS", "NFLX", "CMCSA",
]


def fetch_screen_candidates(size: int = 50, fallback: Optional[List[str]] = None) -> List[str]:
    """Pull momentum candidates via the Yahoo day-gainers screen.

    Falls back to a curated liquid multi-sector universe when the live
    screen is unavailable so the pipeline never hard-fails offline.
    """
    try:
        import yfinance as yf

        result = yf.screen("day_gainers", size=size)
        quotes = (result or {}).get("quotes") or []
        symbols = [q.get("symbol") for q in quotes if isinstance(q, dict) and q.get("symbol")]
        if symbols:
            return symbols[:size]
        logger.warning("Live screen returned no quotes; using fallback universe.")
    except Exception as e:
        logger.warning("Live screen unavailable (%s); using fallback universe.", e)
    return list(fallback or FALLBACK_UNIVERSE)[:size]


def compute_momentum_metrics(df: pd.DataFrame) -> Dict[str, Any]:
    """Trailing-only momentum metrics: volume surge and 52-week-high proximity."""
    if df is None or df.empty:
        raise ValueError("Price data required for momentum metrics.")
    required = {"adjusted_close", "volume"}
    if not required.issubset(df.columns):
        raise ValueError(f"Price data must include {required}.")

    close = float(df["adjusted_close"].iloc[-1])
    out: Dict[str, Any] = {"bars": int(len(df)), "close": close}

    tail = df.tail(BREAKOUT_LOOKBACK + 1)
    high_52w = float(tail["adjusted_close"].max())
    out["high_52w"] = round(high_52w, 2)
    out["pct_of_52w_high"] = round(close / high_52w, 6) if high_52w > 0 else None
    out["near_52w_high"] = (
        close >= high_52w * BREAKOUT_TOLERANCE if high_52w > 0 else False
    )

    if len(df) > VOLUME_AVG_WINDOW:
        prior = df["volume"].iloc[-(VOLUME_AVG_WINDOW + 1):-1]
        avg_vol = float(prior.mean()) if not prior.empty else 0.0
        last_vol = float(df["volume"].iloc[-1])
        out["volume_surge_ratio"] = round(last_vol / avg_vol, 3) if avg_vol > 0 else None
        out["volume_surge"] = (
            out["volume_surge_ratio"] is not None
            and out["volume_surge_ratio"] >= VOLUME_SURGE_MULTIPLE
        )
    else:
        out["volume_surge_ratio"] = None
        out["volume_surge"] = False

    for label, window in (("r_1m", 21), ("r_3m", 63)):
        if len(df) > window:
            start = float(df["adjusted_close"].iloc[-window - 1])
            out[label] = round(close / start - 1.0, 6) if start > 0 else None
        else:
            out[label] = None
    return out


def normalize_roe(value: Any) -> Optional[float]:
    """Normalize ROE to a decimal (yfinance serves either 0.15 or 15)."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v / 100.0 if v > 1.5 else v


def garp_gate(info: Dict[str, Any]) -> Dict[str, Any]:
    """Growth-at-reasonable-price gate: ROE >= 15%, PEG <= 1.5, growth > 0."""
    roe = normalize_roe((info or {}).get("returnOnEquity"))
    peg = None
    peg_raw = (info or {}).get("pegRatio")
    if peg_raw is not None:
        try:
            peg = float(peg_raw)
        except (TypeError, ValueError):
            peg = None
    growth = (info or {}).get("earningsGrowth")
    if growth is None:
        growth = (info or {}).get("earningsQuarterlyGrowth")
    try:
        growth_f = float(growth) if growth is not None else None
    except (TypeError, ValueError):
        growth_f = None

    failures: List[str] = []
    if roe is None or roe < GARP_MIN_ROE:
        failures.append("roe_below_15pct")
    if peg is None or peg <= 0 or peg > GARP_MAX_PEG:
        failures.append("peg_above_1_5")
    if growth_f is None or growth_f <= 0:
        failures.append("non_positive_growth")

    return {
        "return_on_equity": round(roe, 4) if roe is not None else None,
        "peg_ratio": round(peg, 3) if peg is not None else None,
        "earnings_growth": round(growth_f, 4) if growth_f is not None else None,
        "pass": not failures,
        "failures": failures,
    }


def sharpe_and_cagr(df: pd.DataFrame, rf: float = SHARPE_RF) -> Tuple[Optional[float], Optional[float]]:
    """Annualized Sharpe and CAGR over the frame's trailing history."""
    if df is None or df.empty or len(df) < 30:
        return None, None
    close = df["adjusted_close"].astype(float)
    rets = close.pct_change().dropna()
    if rets.empty or float(rets.std()) <= 0:
        return None, None
    ann_sharpe = (float(rets.mean()) * 252 - rf) / (float(rets.std()) * math.sqrt(252))
    start = float(close.iloc[0])
    end = float(close.iloc[-1])
    if start <= 0 or end <= 0:
        return ann_sharpe, None
    years = len(close) / 252.0
    cagr = (end / start) ** (1.0 / years) - 1.0 if years > 0 else None
    return round(ann_sharpe, 4), (round(cagr, 6) if cagr is not None else None)


def beats_sector_etf(
    symbol: str,
    etf_symbol: str,
    window: int = COMPARISON_WINDOW,
    df_sym: Optional[pd.DataFrame] = None,
    df_etf: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Core philosophy gate: symbol must beat its sector ETF on Sharpe AND CAGR."""
    sym_df = df_sym if df_sym is not None else fetch_daily(symbol, period=HISTORY_PERIOD)
    etf_df = df_etf if df_etf is not None else fetch_daily(etf_symbol, period=HISTORY_PERIOD)
    if sym_df is None or sym_df.empty or etf_df is None or etf_df.empty:
        return {"symbol": symbol, "etf": etf_symbol, "pass": False, "flag": "no_data"}
    if len(sym_df) < window or len(etf_df) < window:
        return {"symbol": symbol, "etf": etf_symbol, "pass": False, "flag": "insufficient_history"}

    sym_sharpe, sym_cagr = sharpe_and_cagr(sym_df.tail(window))
    etf_sharpe, etf_cagr = sharpe_and_cagr(etf_df.tail(window))
    if None in (sym_sharpe, sym_cagr, etf_sharpe, etf_cagr):
        return {"symbol": symbol, "etf": etf_symbol, "pass": False, "flag": "metric_unavailable"}

    pass_gate = sym_sharpe > etf_sharpe and sym_cagr > etf_cagr
    return {
        "symbol": symbol,
        "etf": etf_symbol,
        "pass": pass_gate,
        "symbol_sharpe": sym_sharpe,
        "etf_sharpe": etf_sharpe,
        "symbol_cagr": sym_cagr,
        "etf_cagr": etf_cagr,
    }


def evaluate_candidate(
    symbol: str,
    info: Optional[Dict[str, Any]] = None,
    df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Full candidate evaluation: momentum, fundamentals veto, GARP, ETF gate."""
    symbol = symbol.upper().strip()
    price_df = df if df is not None else fetch_daily(symbol, period=HISTORY_PERIOD)
    if price_df is None or price_df.empty or len(price_df) < MIN_CANDIDATE_BARS:
        return {"symbol": symbol, "qualified": False, "flag": "no_data"}

    momentum = compute_momentum_metrics(price_df)
    signals = []
    if momentum["near_52w_high"]:
        signals.append("52w_high_breakout")
    if momentum["volume_surge"]:
        signals.append("volume_surge")
    if not signals:
        return {
            "symbol": symbol,
            "qualified": False,
            "flag": "no_momentum_signal",
            "momentum": momentum,
        }

    fundamentals = info if info is not None else fetch_ticker_info(symbol)
    veto = fundamental_veto_reasons(fundamentals)
    if veto:
        return {
            "symbol": symbol,
            "qualified": False,
            "flag": "fundamental_veto",
            "veto_reasons": veto,
            "momentum": momentum,
        }

    garp = garp_gate(fundamentals)
    sector_name = (fundamentals or {}).get("sector")
    etf = SECTOR_NAME_TO_ETF.get(sector_name or "")
    if not etf:
        return {
            "symbol": symbol,
            "qualified": False,
            "flag": "unknown_sector",
            "garp": garp,
            "momentum": momentum,
        }

    gate = beats_sector_etf(symbol, etf, df_sym=price_df)
    qualified = bool(garp["pass"] and gate.get("pass"))
    return {
        "symbol": symbol,
        "qualified": qualified,
        "signals": signals,
        "momentum": momentum,
        "garp": garp,
        "etf_gate": gate,
        "sector": sector_name,
        "etf": etf,
        "flag": None if qualified else ("garp_fail" if not garp["pass"] else "etf_gate_fail"),
    }


def run_hunt(
    top_n: int = 3,
    size: int = 50,
    exclude_pruned: bool = True,
) -> Dict[str, Any]:
    """Orchestrated dark-horse hunt.

    1. Rank sectors; keep the top N by relative strength.
    2. Screen candidates; drop anything mathematically pruned.
    3. Two-stage gate: momentum signal first, then fundamentals (veto +
       GARP) and the beats-sector-ETF philosophy gate.
    """
    ranked = rank_sectors()
    top_sectors = [
        {"symbol": r["symbol"], "sector": r["sector"], "classification": r["classification"]}
        for r in ranked[:top_n]
    ]

    pruned_symbols = set()
    if exclude_pruned:
        pruned_symbols = set(load_prune_list().get("pruned", {}).keys())

    raw_candidates = fetch_screen_candidates(size=size)
    candidates = [s for s in raw_candidates if s.upper().strip() not in pruned_symbols]

    qualified: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for symbol in candidates:
        try:
            result = evaluate_candidate(symbol)
        except Exception as e:
            rejected.append({"symbol": symbol.upper().strip(), "flag": f"error: {e}"})
            continue
        (qualified if result.get("qualified") else rejected).append(result)

    return {
        "generated_at": datetime.now().isoformat(),
        "top_sectors": top_sectors,
        "candidates_screened": len(raw_candidates),
        "candidates_after_prune_filter": len(candidates),
        "qualified": qualified,
        "rejected_count": len(rejected),
        "rejected_sample": rejected[:10],
        "next_action": (
            "Graduate qualified candidates through paper trading "
            "(finance hunt --stage-paper) before allocating real capital."
        ),
    }


def stage_for_paper_trade(
    symbol: str,
    price: float,
    dollars: float = 100.0,
    db_path=None,
) -> Dict[str, Any]:
    """Stage a qualified candidate into the paper-trading ledger (2A gate)."""
    if price <= 0 or dollars <= 0:
        raise ValueError("Price and dollars must be positive.")
    shares = round(dollars / price, 6)
    from finance.paper_trading import paper_buy

    return paper_buy(symbol.upper().strip(), float(price), shares, db_path=db_path)
