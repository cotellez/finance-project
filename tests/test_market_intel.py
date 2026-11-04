"""Offline tests for market-intel modules: sector rotation, pruner, hunter, ingest."""

import numpy as np
import pandas as pd
import pytest

from finance.sector_rotation import (
    BENCHMARK,
    classify_macro_regime,
    classify_sector,
    compute_relative_strength,
    compute_trend_state,
    rank_sectors,
)
from finance.pruner import (
    add_prune,
    backtest_fast_veto,
    compute_fast_metrics,
    evaluate_symbol,
    evaluate_universe,
    fast_veto_reasons,
    fundamental_veto_reasons,
    graduate_prune,
    load_prune_list,
    run_amnesty,
)
from finance.hunter import (
    beats_sector_etf,
    compute_momentum_metrics,
    evaluate_candidate,
    garp_gate,
    normalize_roe,
    run_hunt,
    stage_for_paper_trade,
)
from finance.ingest import ingest_file


def make_df(prices, volume=None, start="2025-01-01"):
    n = len(prices)
    idx = pd.date_range(start, periods=n, freq="B")
    close = np.asarray(prices, dtype=float)
    vol = np.full(n, 1_000_000.0) if volume is None else np.asarray(volume, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "adjusted_close": close,
            "volume": vol,
        },
        index=idx,
    )


def uptrend(n=260, start=100.0, end=200.0):
    return make_df(np.linspace(start, end, n))


def downtrend(n=260, start=200.0, end=80.0):
    return make_df(np.linspace(start, end, n))


def geom_trend(n=260, daily=0.003, wiggle=0.004, base=100.0):
    """Geometric growth path with identical wiggle so Sharpe ordering
    between two series is driven by growth, not smoothness artifacts."""
    t = np.arange(n, dtype=float)
    prices = base * (1.0 + daily) ** t * (1.0 + wiggle * np.sin(t / 3.0))
    return make_df(prices)


# ---------------------------------------------------------------------------
# sector_rotation
# ---------------------------------------------------------------------------


def test_compute_relative_strength_positive_when_symbol_beats_benchmark():
    sym = make_df(np.linspace(100, 140, 200))
    bench = make_df(np.linspace(100, 110, 200))
    rs = compute_relative_strength(sym, bench)
    assert rs["rs_1m"] is not None and rs["rs_1m"] > 0
    assert rs["rs_6m"] is not None and rs["rs_6m"] > 0.1


def test_compute_relative_strength_none_when_history_short():
    sym = make_df(np.linspace(100, 110, 30))
    bench = make_df(np.linspace(100, 110, 200))
    rs = compute_relative_strength(sym, bench)
    assert rs["rs_6m"] is None
    assert rs["rs_3m"] is None


def test_compute_trend_state_uptrend_vs_death_cross():
    up = compute_trend_state(uptrend())
    assert up["above_sma_200"] is True
    assert up["death_cross"] is False
    assert up["trend"] in ("Strong Bullish", "Bullish")

    down = compute_trend_state(downtrend())
    assert down["above_sma_200"] is False
    assert down["death_cross"] is True
    assert down["trend"] == "Strong Bearish"


def test_classify_sector_labels():
    assert classify_sector(None, {"death_cross": False}) == "Unknown"
    assert classify_sector(0.05, {"death_cross": False, "above_sma_200": True}) == "Strong Bullish"
    assert classify_sector(0.01, {"death_cross": False, "above_sma_200": False}) == "Bullish"
    assert classify_sector(-0.05, {"death_cross": False, "above_sma_200": True}) == "Bearish Rotation"
    assert classify_sector(0.0, {"death_cross": True, "above_sma_200": False}) == "Bearish Rotation"


def test_rank_sectors_orders_leaders_first(monkeypatch):
    bench = make_df(np.linspace(100, 110, 260))

    def fake_fetch(symbol, period="2y", interval="1d"):
        if symbol == BENCHMARK:
            return bench
        if symbol == "XLK":
            return uptrend(260, 100, 250)
        if symbol == "XLV":
            return downtrend(260, 200, 80)
        return uptrend(260, 100, 130)

    monkeypatch.setattr("finance.sector_rotation.fetch_daily", fake_fetch)
    ranked = rank_sectors()
    assert len(ranked) == 11
    assert ranked[0]["symbol"] == "XLK"
    assert ranked[0]["rank"] == 1
    xlk = ranked[0]
    assert xlk["rs"]["rs_6m"] is not None and xlk["rs"]["rs_6m"] > 0
    xlk_row = next(r for r in ranked if r["symbol"] == "XLK")
    assert xlk_row["classification"] == "Strong Bullish"
    xlv_row = next(r for r in ranked if r["symbol"] == "XLV")
    assert xlv_row["classification"] == "Bearish Rotation"
    assert [r["rank"] for r in ranked] == list(range(1, 12))


def test_macro_regime_inverted_curve(monkeypatch):
    calls = [
        {"series_id": "T10Y2Y", "date": "2026-10-30", "value": -0.2, "change": 0.05},
        {"series_id": "DGS10", "date": "2026-10-30", "value": 4.2, "change": -0.2},
    ]
    monkeypatch.setattr(
        "finance.fred.get_latest_observation",
        lambda series_id, db_path=None: calls.pop(0),
    )
    regime = classify_macro_regime()
    assert regime["regime"] == "Inverted Curve (Restrictive)"
    assert regime["details"]["risk_tone"] == "Risk-Off"
    assert regime["details"]["rate_tone"] == "falling"


def test_macro_regime_degrades_to_unknown_without_fred(monkeypatch):
    def boom(series_id, db_path=None):
        raise ValueError("FRED_API_KEY not found")

    monkeypatch.setattr("finance.fred.get_latest_observation", boom)
    regime = classify_macro_regime()
    assert regime["regime"] == "Unknown"
    assert "FRED unavailable" in regime["note"]


def test_macro_regime_omits_none_db_path(monkeypatch, tmp_path):
    calls = []

    def fake(series_id, **kwargs):
        calls.append((series_id, kwargs))
        return {"value": 0.5, "date": "2026-10-01", "change": 0.05}

    monkeypatch.setattr("finance.fred.get_latest_observation", fake)

    out = classify_macro_regime()
    assert out["regime"] == "Positive Curve (Expansion)"
    assert calls, "FRED lookups should have run"
    assert all("db_path" not in kw for _, kw in calls), (
        "db_path=None must not override fred's default cache"
    )

    calls.clear()
    custom = tmp_path / "macro.db"
    classify_macro_regime(db_path=custom)
    assert all(kw.get("db_path") == custom for _, kw in calls)


# ---------------------------------------------------------------------------
# pruner — fast rules
# ---------------------------------------------------------------------------


def test_fast_metrics_uptrend_no_veto():
    metrics = compute_fast_metrics(uptrend())
    assert metrics["death_cross"] is False
    assert metrics["above_sma_200"] is True
    assert fast_veto_reasons(metrics) == []


def test_fast_metrics_death_cross_veto():
    metrics = compute_fast_metrics(downtrend())
    assert metrics["death_cross"] is True
    assert metrics["above_sma_200"] is False
    reasons = fast_veto_reasons(metrics)
    assert "death_cross_below_200sma" in reasons


def test_fast_veto_rs_rules():
    base = {"death_cross": False, "above_sma_200": True, "rs_6m": -0.15}
    assert "rs_6m_underperform" in fast_veto_reasons(base)
    assert "rs_6m_bottom_20pct" in fast_veto_reasons(base, rs_percentile_6m=15.0)
    assert fast_veto_reasons(base, rs_percentile_6m=50.0) == []


def test_fast_veto_rs_percentile_overrides_threshold():
    base = {"death_cross": False, "above_sma_200": True, "rs_6m": -0.02}
    assert fast_veto_reasons(base, rs_percentile_6m=10.0) == ["rs_6m_bottom_20pct"]
    assert fast_veto_reasons(base, rs_percentile_6m=80.0) == []


def test_fundamental_veto_rules():
    assert fundamental_veto_reasons({}) == []
    assert fundamental_veto_reasons(None) == []
    assert "peg_expensive" in fundamental_veto_reasons({"pegRatio": 4.2})
    assert "debt_trap" in fundamental_veto_reasons(
        {"debtToEquity": 3.5, "profitMargins": -0.1}
    )
    assert "growth_decay_expensive" in fundamental_veto_reasons(
        {"earningsGrowth": -0.05, "forwardPE": 40}
    )
    assert fundamental_veto_reasons(
        {"pegRatio": 1.2, "debtToEquity": 0.5, "profitMargins": 0.2, "earningsGrowth": 0.15}
    ) == []
    assert fundamental_veto_reasons({"pegRatio": "junk"}) == []


def test_evaluate_symbol_no_data_flag(monkeypatch):
    monkeypatch.setattr(
        "finance.pruner.fetch_daily",
        lambda symbol, period="2y", interval="1d": pd.DataFrame(),
    )
    row = evaluate_symbol("FAKE")
    assert row["flag"] == "no_data"
    assert row["pruned"] is False


def test_prune_list_lifecycle(tmp_path):
    db = tmp_path / "prune_list.json"
    assert load_prune_list(db) == {"pruned": {}}

    entry = add_prune("BAD", ["death_cross_below_200sma"], db_path=db)
    assert entry["reasons"] == ["death_cross_below_200sma"]
    data = load_prune_list(db)
    assert "BAD" in data["pruned"]

    add_prune("BAD", ["rs_6m_underperform"], db_path=db)
    merged = load_prune_list(db)["pruned"]["BAD"]["reasons"]
    assert set(merged) == {"death_cross_below_200sma", "rs_6m_underperform"}

    assert graduate_prune("BAD", db_path=db) is True
    assert load_prune_list(db)["pruned"] == {}
    assert graduate_prune("BAD", db_path=db) is False


def test_add_prune_requires_reasons(tmp_path):
    db = tmp_path / "prune_list.json"
    with pytest.raises(ValueError, match="reason"):
        add_prune("X", [], db_path=db)


def test_evaluate_universe_percentile_veto(monkeypatch, tmp_path):
    db = tmp_path / "prune_list.json"
    bench = make_df(np.linspace(100, 110, 260))
    frames = {
        "SPY": bench,
        "AAA": uptrend(260, 100, 220),
        "BBB": downtrend(260, 200, 120),
        "CCC": downtrend(260, 200, 110),
        "DDD": downtrend(260, 200, 100),
        "EEE": downtrend(260, 200, 90),
    }

    def fake_fetch(symbol, period="2y", interval="1d"):
        return frames.get(symbol, pd.DataFrame())

    monkeypatch.setattr("finance.pruner.fetch_daily", fake_fetch)
    result = evaluate_universe(list(frames.keys()), db_path=db, record=True)
    assert result["evaluated"] == 6
    assert "EEE" in result["pruned_symbols"]
    assert "AAA" not in result["pruned_symbols"]
    eee = next(r for r in result["results"] if r["symbol"] == "EEE")
    assert "rs_6m_bottom_20pct" in eee["fast_reasons"] or "death_cross_below_200sma" in eee["fast_reasons"]
    assert load_prune_list(db)["pruned"]  # recorded


def test_amnesty_light_clears_fast_only(tmp_path, monkeypatch):
    db = tmp_path / "prune_list.json"
    add_prune("GOOD", ["death_cross_below_200sma"], db_path=db)
    add_prune("SLOW", ["death_cross_below_200sma", "peg_expensive"], db_path=db)

    monkeypatch.setattr(
        "finance.pruner.fetch_daily",
        lambda symbol, period="2y", interval="1d": uptrend(260),
    )
    result = run_amnesty(mode="light", db_path=db)
    assert "GOOD" in result["cleared"]
    remaining = load_prune_list(db)["pruned"]
    assert "GOOD" not in remaining
    assert "SLOW" in remaining
    slow_row = next(r for r in result["still_pruned"] if r["symbol"] == "SLOW")
    assert slow_row.get("note") == "slow_reasons_pending_deep_review"


def test_amnesty_deep_clears_recovered_fundamentals(tmp_path, monkeypatch):
    db = tmp_path / "prune_list.json"
    add_prune("RECOVERED", ["death_cross_below_200sma", "peg_expensive"], db_path=db)

    monkeypatch.setattr(
        "finance.pruner.fetch_daily",
        lambda symbol, period="2y", interval="1d": uptrend(260),
    )
    monkeypatch.setattr(
        "finance.pruner.fetch_ticker_info",
        lambda symbol, use_cache=True, ttl_hours=48: {
            "pegRatio": 1.1,
            "debtToEquity": 50,
            "profitMargins": 0.2,
            "earningsGrowth": 0.2,
        },
    )
    result = run_amnesty(mode="deep", db_path=db)
    assert result["cleared"] == ["RECOVERED"]
    assert load_prune_list(db)["pruned"] == {}


def test_amnesty_rejects_bad_mode(tmp_path):
    with pytest.raises(ValueError, match="Mode"):
        run_amnesty(mode="weekly", db_path=tmp_path / "p.json")


# ---------------------------------------------------------------------------
# pruner — backtest (false-negative audit)
# ---------------------------------------------------------------------------


def test_backtest_all_vetoed_steady_decline_beats_steeper_benchmark():
    n = 300
    sym = 200.0 * np.exp(-0.001 * np.arange(n))
    bench = 200.0 * np.exp(-0.005 * np.arange(n))
    result = backtest_fast_veto(
        make_df(sym), make_df(bench), warmup=200, forward=21, step=7
    )
    assert result["observations"] >= 10
    assert result["veto_rate"] == 1.0
    assert result["false_negative_rate"] == 1.0
    assert result["false_negatives"]
    assert result["vetoed_avg_fwd_return"] > result["bench_avg_fwd_return"]


def test_backtest_uptrend_not_vetoed():
    n = 300
    sym = np.linspace(100, 250, n)
    bench = np.full(n, 100.0)
    result = backtest_fast_veto(
        make_df(sym), make_df(bench), warmup=200, forward=21, step=7
    )
    assert result["observations"] >= 10
    assert result["veto_rate"] == 0.0
    assert result["false_negative_rate"] is None


def test_backtest_insufficient_history_raises():
    with pytest.raises(ValueError, match="Insufficient"):
        backtest_fast_veto(
            make_df(np.linspace(100, 110, 50)),
            make_df(np.linspace(100, 110, 50)),
        )


# ---------------------------------------------------------------------------
# hunter
# ---------------------------------------------------------------------------


def test_momentum_metrics_volume_surge_and_breakout():
    n = 260
    prices = np.linspace(100, 150, n)
    volumes = np.full(n, 1_000_000.0)
    volumes[-1] = 5_000_000.0
    metrics = compute_momentum_metrics(make_df(prices, volume=volumes))
    assert metrics["volume_surge"] is True
    assert metrics["volume_surge_ratio"] >= 2.0
    assert metrics["near_52w_high"] is True
    assert metrics["r_3m"] is not None and metrics["r_3m"] > 0


def test_momentum_metrics_no_signal_when_flat_and_quiet():
    n = 260
    prices = np.linspace(100, 80, n)
    volumes = np.full(n, 1_000_000.0)
    metrics = compute_momentum_metrics(make_df(prices, volume=volumes))
    assert metrics["volume_surge"] is False
    assert metrics["near_52w_high"] is False


def test_normalize_roe():
    assert normalize_roe(15) == 0.15
    assert normalize_roe(0.2) == 0.2
    assert normalize_roe(None) is None
    assert normalize_roe("abc") is None


def test_garp_gate_pass_and_fail():
    ok = garp_gate(
        {"returnOnEquity": 0.25, "pegRatio": 1.2, "earningsGrowth": 0.15}
    )
    assert ok["pass"] is True

    bad = garp_gate(
        {"returnOnEquity": 0.05, "pegRatio": 3.0, "earningsGrowth": -0.1}
    )
    assert bad["pass"] is False
    assert "roe_below_15pct" in bad["failures"]
    assert "peg_above_1_5" in bad["failures"]
    assert "non_positive_growth" in bad["failures"]


def test_beats_sector_etf_gate(monkeypatch):
    strong = geom_trend(daily=0.004)
    mild = geom_trend(daily=0.001)
    weak = geom_trend(daily=-0.003)
    frames = {"STRONG": strong, "MILD": mild, "WEAK": weak}

    monkeypatch.setattr(
        "finance.hunter.fetch_daily",
        lambda symbol, period="1y", interval="1d": frames[symbol],
    )
    win = beats_sector_etf("STRONG", "MILD")
    assert win["pass"] is True
    assert win["symbol_sharpe"] > win["etf_sharpe"]
    assert win["symbol_cagr"] > win["etf_cagr"]

    loss = beats_sector_etf("WEAK", "MILD")
    assert loss["pass"] is False


def test_evaluate_candidate_full_pass(monkeypatch):
    n = 260
    prices = geom_trend(n, daily=0.003)["adjusted_close"].to_numpy()
    volumes = np.full(n, 1_000_000.0)
    volumes[-1] = 5_000_000.0
    df = make_df(prices, volume=volumes)

    info = {
        "sector": "Technology",
        "pegRatio": 1.1,
        "returnOnEquity": 0.3,
        "earningsGrowth": 0.2,
        "debtToEquity": 40,
        "profitMargins": 0.25,
        "forwardPE": 28,
    }
    frames = {"CAND": df, "XLK": geom_trend(daily=0.001)}
    monkeypatch.setattr(
        "finance.hunter.fetch_daily",
        lambda symbol, period="1y", interval="1d": frames[symbol],
    )
    result = evaluate_candidate("CAND", info=info, df=df)
    assert result["qualified"] is True
    assert "volume_surge" in result["signals"]
    assert result["etf"] == "XLK"
    assert result["etf_gate"]["pass"] is True


def test_evaluate_candidate_fundamental_veto(monkeypatch):
    n = 260
    prices = np.linspace(100, 150, n)
    volumes = np.full(n, 1_000_000.0)
    volumes[-1] = 5_000_000.0
    df = make_df(prices, volume=volumes)
    info = {
        "sector": "Technology",
        "pegRatio": 5.0,
        "returnOnEquity": 0.3,
        "earningsGrowth": 0.2,
    }
    result = evaluate_candidate("CAND", info=info, df=df)
    assert result["qualified"] is False
    assert result["flag"] == "fundamental_veto"
    assert "peg_expensive" in result["veto_reasons"]


def test_evaluate_candidate_requires_momentum_signal():
    n = 260
    prices = np.linspace(100, 80, n)
    df = make_df(prices)
    result = evaluate_candidate(
        "FLAT", info={"sector": "Technology"}, df=df
    )
    assert result["qualified"] is False
    assert result["flag"] == "no_momentum_signal"


def test_run_hunt_filters_pruned_and_reports(monkeypatch):
    monkeypatch.setattr(
        "finance.hunter.rank_sectors",
        lambda period="2y": [
            {"symbol": "XLK", "sector": "Technology", "classification": "Strong Bullish"},
            {"symbol": "XLV", "sector": "Healthcare", "classification": "Bullish"},
            {"symbol": "XLF", "sector": "Financials", "classification": "Neutral"},
        ],
    )
    monkeypatch.setattr(
        "finance.hunter.fetch_screen_candidates",
        lambda size=50, fallback=None: ["AAA", "BBB", "PRUNED"],
    )
    monkeypatch.setattr(
        "finance.hunter.load_prune_list",
        lambda db_path=None: {"pruned": {"PRUNED": {"reasons": ["x"]}}},
    )
    monkeypatch.setattr(
        "finance.hunter.evaluate_candidate",
        lambda symbol, info=None, df=None: (
            {"symbol": symbol, "qualified": True, "signals": ["volume_surge"]}
            if symbol == "AAA"
            else {"symbol": symbol, "qualified": False, "flag": "no_momentum_signal"}
        ),
    )
    result = run_hunt(top_n=3, size=50)
    assert result["candidates_screened"] == 3
    assert result["candidates_after_prune_filter"] == 2
    assert [c["symbol"] for c in result["qualified"]] == ["AAA"]
    assert result["rejected_count"] == 1
    assert "paper trading" in result["next_action"]


def test_stage_for_paper_trade_computes_shares(monkeypatch):
    captured = {}

    def fake_paper_buy(symbol, price, shares, db_path=None, **kwargs):
        captured.update(symbol=symbol, price=price, shares=shares)
        return {"symbol": symbol, "shares": shares, "price": price}

    monkeypatch.setattr("finance.paper_trading.paper_buy", fake_paper_buy)
    res = stage_for_paper_trade("aaa", 50.0, dollars=100.0)
    assert captured["symbol"] == "AAA"
    assert captured["shares"] == 2.0
    assert res["shares"] == 2.0


def test_stage_for_paper_trade_rejects_bad_inputs():
    with pytest.raises(ValueError):
        stage_for_paper_trade("AAA", 0.0, dollars=100.0)


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


def test_ingest_text_report(tmp_path):
    from pathlib import Path

    src = tmp_path / "note.md"
    src.write_text("# Thesis\nSome research notes.\n", encoding="utf-8")
    out_dir = tmp_path / "ingested"
    result = ingest_file(src, out_dir=out_dir)
    stored = result["stored_as"]
    assert stored.endswith(".md")
    assert Path(stored).exists()
    assert result["chars"] > 0
    assert "never executed" in result["untrusted_input_note"]


def test_ingest_rejects_unsupported_and_missing(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        ingest_file(tmp_path / "missing.md")
    bad = tmp_path / "x.exe"
    bad.write_text("bin", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported"):
        ingest_file(bad)


# ---------------------------------------------------------------------------
# CLI parser wiring
# ---------------------------------------------------------------------------


def test_cli_parser_market_intel_commands():
    from finance.cli import build_parser

    parser = build_parser()

    args = parser.parse_args(["sector-rotation"])
    assert args.func.__name__ == "handle_sector_rotation"

    args = parser.parse_args(["hunt", "--top-sectors", "2", "--size", "30", "--stage-paper", "--dollars", "50"])
    assert args.func.__name__ == "handle_hunt"
    assert args.top_sectors == 2
    assert args.size == 30
    assert args.stage_paper is True
    assert args.dollars == 50.0

    args = parser.parse_args(["prune", "evaluate", "AAPL", "MSFT", "--record"])
    assert args.func.__name__ == "handle_prune_evaluate"
    assert args.symbols == ["AAPL", "MSFT"]
    assert args.record is True

    args = parser.parse_args(["prune", "list"])
    assert args.func.__name__ == "handle_prune_list"

    args = parser.parse_args(["prune", "audit", "--mode", "deep"])
    assert args.func.__name__ == "handle_prune_audit"
    assert args.mode == "deep"

    args = parser.parse_args(["prune", "graduate", "AAPL", "--note", "recovered"])
    assert args.func.__name__ == "handle_prune_graduate"

    args = parser.parse_args(["prune", "backtest"])
    assert args.func.__name__ == "handle_prune_backtest"

    args = parser.parse_args(["market-forecast", "--no-hunt"])
    assert args.func.__name__ == "handle_market_forecast"
    assert args.no_hunt is True

    args = parser.parse_args(["ingest", "report.pdf"])
    assert args.func.__name__ == "handle_ingest"
    assert args.path == "report.pdf"


def test_cli_handle_prune_list_empty(capsys):
    from finance.cli import handle_prune_list

    assert handle_prune_list(None) == 0
    out = capsys.readouterr().out
    assert "Prune list" in out
