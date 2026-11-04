"""Mathematical pruning engine with tiered amnesty review.

Hard-veto rules eliminate structurally impaired assets from deep research
so time is only spent where the math says an asset can win. Two veto tiers:

  - Fast (price/trend): death cross, 6M relative-strength underperformance.
    Re-checked weekly (``mode="light"``) because trend signals decay in weeks.
  - Slow (fundamental): PEG > 3.5, debt traps, growth decay.
    Re-checked monthly/quarterly (``mode="deep"``) on the earnings cycle.

Veto policy: pruned symbols block NEW capital only. Existing positions are
alerted but remain governed by ATR trailing stops and tax-lot awareness.
"""

import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from finance.cache import cache_response, get_cached_response
from finance.indicators import calculate_sma
from finance.jsonstore import PROJECT_ROOT, FileLock, atomic_write_json, resolve_path
from finance.logging_setup import get_logger
from finance.stock_data import fetch_daily

logger = get_logger(__name__)

DEFAULT_PRUNE_DB = PROJECT_ROOT / "prune_list.json"
BENCHMARK = "SPY"
FUNDAMENTAL_TTL_HOURS = 48
RS_6M_UNDERPERFORM = -0.10
RS_6M_BOTTOM_PCT = 20.0
PEG_EXPENSIVE = 3.5
DANGER_DEBT_TO_EQUITY = 2.0
EXPENSIVE_FWD_PE = 25.0
MIN_FAST_BARS = 60
FAST_WINDOWS = {"1m": 21, "3m": 63, "6m": 126}
DEFAULT_BACKTEST_SYMBOLS = ["AAPL", "MSFT", "NVDA", "UNH", "PG", "XOM", "JPM", "CAT"]


def _num(value: Any) -> Optional[float]:
    """Coerce a raw metric value to float, returning None for junk/missing."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def load_prune_list(db_path: Path | str | None = None) -> Dict[str, Any]:
    """Load and validate the prune list from JSON storage."""
    db_path = resolve_path(db_path, DEFAULT_PRUNE_DB)
    if not Path(db_path).exists():
        return {"pruned": {}}
    try:
        import json

        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"Prune list '{db_path}' is corrupted: {e}") from e

    if not isinstance(data, dict) or not isinstance(data.get("pruned"), dict):
        raise ValueError(f"Prune list '{db_path}' must be a dict with a 'pruned' mapping.")
    for symbol, entry in data["pruned"].items():
        if not isinstance(entry, dict) or not isinstance(entry.get("reasons"), list):
            raise ValueError(f"Prune entry for {symbol} is malformed.")
    return data


def save_prune_list(
    data: Dict[str, Any],
    db_path: Path | str | None = None,
    *,
    audit: bool = True,
    audit_action: str = "prune_list_write",
    audit_detail: str = "",
) -> None:
    """Persist the prune list atomically with an audit-trail entry."""
    db_path = resolve_path(db_path, DEFAULT_PRUNE_DB)
    atomic_write_json(
        db_path,
        data,
        audit=audit,
        audit_action=audit_action,
        audit_detail=audit_detail,
    )


def add_prune(
    symbol: str,
    reasons: List[str],
    db_path: Path | str | None = None,
) -> Dict[str, Any]:
    """Record a symbol on the prune list with its veto reasons."""
    symbol = symbol.upper().strip()
    if not symbol:
        raise ValueError("Symbol is required.")
    reasons = [str(r) for r in (reasons or []) if str(r).strip()]
    if not reasons:
        raise ValueError("At least one veto reason is required to prune a symbol.")
    tier = "both" if len(set(reasons)) > 1 else "fast"
    now = datetime.now().isoformat()

    db_path = resolve_path(db_path, DEFAULT_PRUNE_DB)
    with FileLock(db_path):
        data = load_prune_list(db_path)
        existing = data["pruned"].get(symbol, {})
        merged = sorted(set(existing.get("reasons", [])) | set(reasons))
        entry = {
            "reasons": merged,
            "tier": "both" if len(merged) > 1 else tier,
            "pruned_at": existing.get("pruned_at", now),
            "last_reviewed": now,
        }
        data["pruned"][symbol] = entry
        save_prune_list(
            data,
            db_path,
            audit=True,
            audit_action="add_prune",
            audit_detail=f"Vetoed {symbol}: {', '.join(merged)}",
        )
    return entry


def graduate_prune(symbol: str, note: str = "", db_path: Path | str | None = None) -> bool:
    """Remove a symbol from the prune list (amnesty graduation)."""
    symbol = symbol.upper().strip()
    db_path = resolve_path(db_path, DEFAULT_PRUNE_DB)
    with FileLock(db_path):
        data = load_prune_list(db_path)
        if symbol not in data["pruned"]:
            return False
        del data["pruned"][symbol]
        save_prune_list(
            data,
            db_path,
            audit=True,
            audit_action="graduate_prune",
            audit_detail=f"Graduated {symbol} from prune list. {note}".strip(),
        )
    return True


def fetch_ticker_info(
    symbol: str,
    use_cache: bool = True,
    ttl_hours: int = FUNDAMENTAL_TTL_HOURS,
) -> Dict[str, Any]:
    """Fetch ticker fundamentals with long TTL caching (rate-limit safe).

    Extended TTL (48h) reflects that fundamentals move on the earnings cycle,
    not tick-by-tick — this is the Phase-4 rate-limit protection.
    """
    symbol = symbol.upper().strip()
    endpoint_key = f"ticker_info_{symbol}"
    if use_cache:
        cached = get_cached_response(endpoint_key, ttl_hours=ttl_hours)
        if cached is not None and isinstance(cached, dict):
            return cached
    import yfinance as yf

    info = yf.Ticker(symbol).info
    if not isinstance(info, dict):
        info = {}
    cache_response(endpoint_key, info)
    return info


def compute_fast_metrics(
    df: pd.DataFrame,
    benchmark_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Compute trailing-only fast metrics (no look-ahead) for the veto rules."""
    if df is None or df.empty:
        raise ValueError("Price data required for fast metrics.")
    if "adjusted_close" not in df.columns:
        raise ValueError("Price data must include an adjusted_close column.")

    close = float(df["adjusted_close"].iloc[-1])
    out: Dict[str, Any] = {"bars": int(len(df)), "close": close}

    for name, window in FAST_WINDOWS.items():
        if len(df) > window:
            start = float(df["adjusted_close"].iloc[-window - 1])
            out[f"r_{name}"] = (close / start - 1.0) if start > 0 else None
        else:
            out[f"r_{name}"] = None

    sma_50 = calculate_sma(df, 50).iloc[-1] if len(df) >= 50 else float("nan")
    sma_200 = calculate_sma(df, 200).iloc[-1] if len(df) >= 200 else float("nan")
    out["sma_50"] = None if pd.isna(sma_50) else float(sma_50)
    out["sma_200"] = None if pd.isna(sma_200) else float(sma_200)
    out["above_sma_200"] = (
        close > out["sma_200"] if out["sma_200"] is not None else None
    )
    out["death_cross"] = (
        out["sma_50"] is not None
        and out["sma_200"] is not None
        and out["sma_50"] < out["sma_200"]
    )

    out["rs_6m"] = None
    if benchmark_df is not None and not benchmark_df.empty and len(benchmark_df) > 126:
        b_close = float(benchmark_df["adjusted_close"].iloc[-1])
        b_start = float(benchmark_df["adjusted_close"].iloc[-127])
        b_r6 = (b_close / b_start - 1.0) if b_start > 0 else None
        if out["r_6m"] is not None and b_r6 is not None:
            out["rs_6m"] = out["r_6m"] - b_r6
    return out


def fast_veto_reasons(
    metrics: Dict[str, Any],
    rs_percentile_6m: Optional[float] = None,
) -> List[str]:
    """Apply fast veto rules to computed metrics.

    Rules (hard veto):
      1. Death cross: 50D SMA < 200D SMA while price sits below the 200D SMA.
      2. 6M relative strength in the bottom 20% of the universe; when no
         universe percentile is supplied, fall back to >10pp underperformance
         vs SPY.
    """
    reasons: List[str] = []
    if metrics.get("death_cross") and metrics.get("above_sma_200") is False:
        reasons.append("death_cross_below_200sma")

    rs = metrics.get("rs_6m")
    if rs_percentile_6m is not None:
        if rs_percentile_6m <= RS_6M_BOTTOM_PCT:
            reasons.append("rs_6m_bottom_20pct")
    elif rs is not None and rs < RS_6M_UNDERPERFORM:
        reasons.append("rs_6m_underperform")
    return reasons


def fundamental_veto_reasons(info: Dict[str, Any]) -> List[str]:
    """Apply slow veto rules to ticker fundamentals.

    Rules (hard veto):
      1. PEG > 3.5 — paying too much for growth.
      2. Debt trap: debt/equity > 2.0 with negative profit margins.
      3. Growth decay: non-positive earnings growth with forward P/E > 25.

    Missing fields do NOT veto — unknown is not a mathematical loser.
    """
    if not isinstance(info, dict) or not info:
        return []
    reasons: List[str] = []

    peg = _num(info.get("pegRatio")) or _num(info.get("trailingPegRatio"))
    if peg is not None and peg > PEG_EXPENSIVE:
        reasons.append("peg_expensive")

    de = _num(info.get("debtToEquity"))
    margin = _num(info.get("profitMargins"))
    if de is not None and margin is not None and de > DANGER_DEBT_TO_EQUITY and margin < 0:
        reasons.append("debt_trap")

    growth = _num(info.get("earningsGrowth"))
    if growth is None:
        growth = _num(info.get("earningsQuarterlyGrowth"))
    fwd_pe = _num(info.get("forwardPE"))
    if growth is not None and growth <= 0 and fwd_pe is not None and fwd_pe > EXPENSIVE_FWD_PE:
        reasons.append("growth_decay_expensive")
    return reasons


def evaluate_symbol(
    symbol: str,
    benchmark_df: Optional[pd.DataFrame] = None,
    info: Optional[Dict[str, Any]] = None,
    rs_percentile_6m: Optional[float] = None,
    period: str = "2y",
    fetcher=None,
) -> Dict[str, Any]:
    """Evaluate one symbol against all veto rules.

    Returns a dict with pruned flag, per-tier reasons, and a flag field for
    non-veto anomalies (e.g. no data) so callers can distinguish "clean"
    from "could not evaluate".
    """
    symbol = symbol.upper().strip()
    fetch = fetcher or fetch_daily
    df = fetch(symbol, period=period)
    if df is None or df.empty:
        return {
            "symbol": symbol,
            "pruned": False,
            "fast_reasons": [],
            "slow_reasons": [],
            "flag": "no_data",
        }

    metrics = compute_fast_metrics(df, benchmark_df)
    fast = fast_veto_reasons(metrics, rs_percentile_6m)
    slow = fundamental_veto_reasons(info) if info is not None else []
    pruned = bool(fast or slow)
    if fast and slow:
        tier = "both"
    elif fast:
        tier = "fast"
    elif slow:
        tier = "slow"
    else:
        tier = "none"
    return {
        "symbol": symbol,
        "pruned": pruned,
        "fast_reasons": fast,
        "slow_reasons": slow,
        "tier": tier,
        "metrics": metrics,
        "flag": None,
    }


def evaluate_universe(
    symbols: List[str],
    db_path: Path | str | None = None,
    period: str = "2y",
    record: bool = True,
) -> Dict[str, Any]:
    """Evaluate many symbols; cross-sectional RS percentile vs each other."""
    symbols = [s.upper().strip() for s in symbols if s and s.strip()]
    if not symbols:
        raise ValueError("At least one symbol is required.")

    benchmark_df = fetch_daily(BENCHMARK, period=period)
    if benchmark_df is None or benchmark_df.empty:
        raise ValueError("Benchmark SPY data unavailable; cannot evaluate universe.")

    rows: List[Dict[str, Any]] = []
    rs_map: Dict[str, float] = {}
    for symbol in symbols:
        row = evaluate_symbol(symbol, benchmark_df=benchmark_df, period=period)
        rows.append(row)
        rs = (row.get("metrics") or {}).get("rs_6m")
        if rs is not None:
            rs_map[symbol] = float(rs)

    percentiles: Dict[str, float] = {}
    if rs_map:
        series = pd.Series(rs_map)
        percentiles = (series.rank(pct=True) * 100.0).to_dict()

    for row in rows:
        pct = percentiles.get(row["symbol"])
        if pct is not None:
            row["rs_6m_percentile"] = round(float(pct), 1)
            reasons = fast_veto_reasons(row["metrics"], rs_percentile_6m=pct)
            row["fast_reasons"] = reasons
            row["pruned"] = bool(reasons or row["slow_reasons"])
            if row["pruned"]:
                row["tier"] = "both" if row["fast_reasons"] and row["slow_reasons"] else (
                    "fast" if row["fast_reasons"] else "slow"
                )

    if record:
        for row in rows:
            if row["pruned"] and row["flag"] is None:
                add_prune(row["symbol"], row["fast_reasons"] + row["slow_reasons"], db_path=db_path)

    pruned_symbols = [r["symbol"] for r in rows if r["pruned"]]
    return {
        "evaluated": len(rows),
        "pruned_count": len(pruned_symbols),
        "pruned_symbols": pruned_symbols,
        "results": rows,
    }


def run_amnesty(
    symbols: Optional[List[str]] = None,
    mode: str = "light",
    db_path: Path | str | None = None,
) -> Dict[str, Any]:
    """Tiered amnesty review of pruned symbols.

    light (weekly): re-checks fast (price/trend) reasons only. A symbol with
      no slow reasons and cleared fast reasons is auto-graduated.
    deep (monthly/quarterly): also re-fetches fundamentals and re-checks
      slow reasons; graduation requires all reasons gone.
    """
    if mode not in ("light", "deep"):
        raise ValueError("Mode must be 'light' or 'deep'.")
    data = load_prune_list(db_path)
    targets = [s.upper().strip() for s in (symbols or list(data["pruned"].keys()))]
    if not targets:
        return {"mode": mode, "reviewed": 0, "cleared": [], "still_pruned": [], "errors": []}

    benchmark_df = None
    if mode == "light" or mode == "deep":
        try:
            benchmark_df = fetch_daily(BENCHMARK, period="2y")
        except Exception as e:
            logger.warning("Benchmark fetch failed during amnesty: %s", e)

    cleared: List[str] = []
    still_pruned: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for symbol in targets:
        entry = data["pruned"].get(symbol)
        if entry is None:
            continue
        old_reasons = set(entry.get("reasons", []))
        fast_prefixes = ("death_cross", "rs_6m")
        had_slow = any(not r.startswith(fast_prefixes) for r in old_reasons)

        try:
            metrics_df = fetch_daily(symbol, period="2y")
            if metrics_df is None or metrics_df.empty:
                errors.append({"symbol": symbol, "error": "no_data"})
                still_pruned.append({"symbol": symbol, "reasons": sorted(old_reasons)})
                continue
            metrics = compute_fast_metrics(metrics_df, benchmark_df)
            fast_now = set(fast_veto_reasons(metrics))
        except Exception as e:
            errors.append({"symbol": symbol, "error": str(e)})
            still_pruned.append({"symbol": symbol, "reasons": sorted(old_reasons)})
            continue

        if mode == "deep":
            info = fetch_ticker_info(symbol)
            slow_now = set(fundamental_veto_reasons(info))
            remaining = fast_now | slow_now
        else:
            if had_slow:
                still_pruned.append(
                    {"symbol": symbol, "reasons": sorted(old_reasons), "note": "slow_reasons_pending_deep_review"}
                )
                continue
            remaining = fast_now

        if remaining:
            still_pruned.append({"symbol": symbol, "reasons": sorted(remaining)})
        else:
            graduate_prune(symbol, note=f"amnesty_{mode}", db_path=db_path)
            cleared.append(symbol)

    return {
        "mode": mode,
        "reviewed": len(targets),
        "cleared": cleared,
        "still_pruned": still_pruned,
        "errors": errors,
    }


def backtest_fast_veto(
    df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    warmup: int = 200,
    forward: int = 63,
    step: int = 21,
) -> Dict[str, Any]:
    """Backtest the fast veto rules; measure the false-negative rate.

    At each signal date the veto uses only trailing data (no look-ahead).
    A false negative = the veto fired but the symbol beat SPY over the
    forward window (the cost of a wrong veto).
    """
    if df is None or df.empty or benchmark_df is None or benchmark_df.empty:
        raise ValueError("Both symbol and benchmark data are required.")
    n = min(len(df), len(benchmark_df))
    if n < warmup + forward + 1:
        raise ValueError(
            f"Insufficient overlapping history ({n} bars); need at least {warmup + forward + 1}."
        )

    records: List[Dict[str, Any]] = []
    for i in range(warmup, n - forward, step):
        metrics = compute_fast_metrics(df.iloc[: i + 1], benchmark_df.iloc[: i + 1])
        reasons = fast_veto_reasons(metrics)
        sym_start = float(df["adjusted_close"].iloc[i])
        sym_end = float(df["adjusted_close"].iloc[i + forward])
        bench_start = float(benchmark_df["adjusted_close"].iloc[i])
        bench_end = float(benchmark_df["adjusted_close"].iloc[i + forward])
        if sym_start <= 0 or bench_start <= 0:
            continue
        records.append(
            {
                "date": str(df.index[i].date()),
                "vetoed": bool(reasons),
                "reasons": reasons,
                "fwd_return": sym_end / sym_start - 1.0,
                "bench_fwd_return": bench_end / bench_start - 1.0,
            }
        )

    if not records:
        raise ValueError("Backtest produced no observations; adjust warmup/forward/step.")

    vetoed = [r for r in records if r["vetoed"]]
    kept = [r for r in records if not r["vetoed"]]
    false_negatives = [r for r in vetoed if r["fwd_return"] > r["bench_fwd_return"]]

    def _avg(items: List[Dict[str, Any]], key: str) -> Optional[float]:
        if not items:
            return None
        return round(sum(r[key] for r in items) / len(items), 6)

    from finance.bias_guard import point_in_time_universe

    return {
        "observations": len(records),
        "vetoed_observations": len(vetoed),
        "veto_rate": round(len(vetoed) / len(records), 4) if records else None,
        "false_negative_rate": (
            round(len(false_negatives) / len(vetoed), 4) if vetoed else None
        ),
        "vetoed_avg_fwd_return": _avg(vetoed, "fwd_return"),
        "kept_avg_fwd_return": _avg(kept, "fwd_return"),
        "bench_avg_fwd_return": _avg(records, "bench_fwd_return"),
        "false_negatives": false_negatives,
        "survivorship_note": point_in_time_universe([])["warning"],
    }


def run_veto_backtest(
    symbols: Optional[List[str]] = None,
    period: str = "5y",
    warmup: int = 200,
    forward: int = 63,
    step: int = 21,
) -> Dict[str, Any]:
    """Run the fast-veto backtest across a universe of symbols."""
    symbols = [s.upper().strip() for s in (symbols or DEFAULT_BACKTEST_SYMBOLS)]
    benchmark_df = fetch_daily(BENCHMARK, period=period)
    if benchmark_df is None or benchmark_df.empty:
        raise ValueError("Benchmark SPY data unavailable; cannot backtest vetoes.")

    per_symbol: List[Dict[str, Any]] = []
    all_fn_rates: List[float] = []
    for symbol in symbols:
        try:
            df = fetch_daily(symbol, period=period)
            if df is None or df.empty:
                per_symbol.append({"symbol": symbol, "error": "no_data"})
                continue
            result = backtest_fast_veto(
                df, benchmark_df, warmup=warmup, forward=forward, step=step
            )
            result["symbol"] = symbol
            per_symbol.append(result)
            if result["false_negative_rate"] is not None:
                all_fn_rates.append(result["false_negative_rate"])
        except Exception as e:
            per_symbol.append({"symbol": symbol, "error": str(e)})

    avg_fn = round(sum(all_fn_rates) / len(all_fn_rates), 4) if all_fn_rates else None
    return {
        "period": period,
        "warmup": warmup,
        "forward": forward,
        "step": step,
        "symbols_tested": len(symbols),
        "avg_false_negative_rate": avg_fn,
        "per_symbol": per_symbol,
    }
