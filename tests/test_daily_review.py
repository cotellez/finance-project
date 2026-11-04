"""Offline tests for scripts/daily_review.py (local Task Scheduler briefing).

All network entry points are monkeypatched on the loaded module so the
suite runs fully offline per repo rule 4.
"""

import importlib.util
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "daily_review.py"

spec = importlib.util.spec_from_file_location("daily_review", SCRIPT)
daily_review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily_review)

FIXED_NOW = datetime(2026, 11, 3, 7, 0, 0)


def make_df(n=60, start=100.0, end=110.0):
    prices = np.linspace(start, end, n)
    idx = pd.date_range("2026-06-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": prices,
            "high": prices * 1.01,
            "low": prices * 0.99,
            "close": prices,
            "adjusted_close": prices,
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


def fake_report(regime="Positive Curve (Expansion)", top="XLV"):
    sectors = [
        {
            "rank": 1,
            "symbol": top,
            "sector": "Healthcare",
            "rs": {"rs_1m": 0.12, "rs_3m": 0.15, "rs_6m": 0.22},
            "rs_composite": 0.165,
            "classification": "Strong Bullish",
        },
        {
            "rank": 2,
            "symbol": "XLI",
            "sector": "Industrials",
            "rs": {"rs_1m": 0.01, "rs_3m": -0.076, "rs_6m": -0.068},
            "rs_composite": -0.045,
            "classification": "Bearish Rotation",
        },
    ]
    return {
        "generated_at": FIXED_NOW.isoformat(),
        "benchmark": "SPY",
        "macro_regime": {
            "regime": regime,
            "details": {
                "yield_curve_2s10s": {"value": 0.38, "date": "2026-10-30"},
                "rate_tone": "stable",
                "risk_tone": "Risk-On",
            },
        },
        "sectors": sectors,
    }


def fake_stop_fn(df, **kwargs):
    out = df.copy()
    out["trailing_stop"] = 100.0
    return out


@pytest.fixture
def offline(monkeypatch):
    """Patch every network/IO entry point; capture toast + push calls."""
    calls = {"toast": [], "push": 0}

    monkeypatch.setattr(daily_review, "build_sector_report", fake_report)
    monkeypatch.setattr(daily_review, "load_prune_list", lambda: {"pruned": {}})
    monkeypatch.setattr(
        daily_review,
        "run_hunt",
        lambda: {
            "qualified": [
                {"symbol": "ABC", "sector": "Technology", "signals": ["volume_surge"]}
            ],
            "rejected": [],
        },
    )
    monkeypatch.setattr(
        daily_review,
        "load_portfolio",
        lambda: [{"symbol": "SCHD", "shares": 106.0, "cost_basis": 34.23}],
    )
    monkeypatch.setattr(daily_review, "fetch_daily", lambda sym, *a, **k: make_df())
    monkeypatch.setattr(daily_review, "atr_trailing_stop", fake_stop_fn)
    monkeypatch.setattr(
        daily_review,
        "toast",
        lambda title, message, runner=None: calls["toast"].append((title, message))
        or True,
    )
    monkeypatch.setattr(
        daily_review,
        "push_context",
        lambda item: calls.__setitem__("push", calls["push"] + 1),
    )
    return calls


# ---------------------------------------------------------------------------
# compute_health
# ---------------------------------------------------------------------------
def test_compute_health_statuses():
    holdings = [{"symbol": "AAA", "shares": 1.0}]
    cases = [
        (110.0, "OK"),
        (101.0, "NEAR_STOP"),
        (99.0, "BREACHED"),
    ]
    for end, expected in cases:
        rows = daily_review.compute_health(
            holdings,
            fetch_df=lambda s, e=end: make_df(end=e),
            stop_fn=fake_stop_fn,
        )
        assert rows[0]["status"] == expected, f"price end={end}"
    assert rows[0]["dist_pct"] is not None


def test_compute_health_no_data_when_fetch_returns_none():
    holdings = [{"symbol": "AAA", "shares": 1.0}]
    rows = daily_review.compute_health(
        holdings, fetch_df=lambda s: None, stop_fn=fake_stop_fn
    )
    assert rows[0]["status"] == "NO_DATA"


def test_compute_health_isolates_symbol_errors():
    def boom(s):
        raise ValueError("bad series")

    holdings = [
        {"symbol": "GOOD", "shares": 1.0},
        {"symbol": "BAD", "shares": 2.0},
    ]

    def fetch(s):
        if s == "BAD":
            raise RuntimeError("network")
        return make_df()

    rows = daily_review.compute_health(
        holdings, fetch_df=fetch, stop_fn=fake_stop_fn
    )
    by_sym = {r["symbol"]: r for r in rows}
    assert by_sym["GOOD"]["status"] == "OK"
    assert by_sym["BAD"]["status"] == "NO_DATA"
    assert "RuntimeError" in by_sym["BAD"]["detail"]


# ---------------------------------------------------------------------------
# History round-trip + change detection
# ---------------------------------------------------------------------------
def test_history_line_roundtrip():
    summary = daily_review.summarize(
        "Positive Curve (Expansion)",
        fake_report()["sectors"],
        0,
        {"state": "ok", "qualified": 2},
        [],
    )
    line = daily_review.format_history_line(FIXED_NOW, summary)
    parsed = daily_review.parse_history_line(line)
    assert parsed["timestamp"] == "2026-11-03 07:00"
    assert parsed["regime"] == "Positive Curve (Expansion)"
    assert parsed["top"] == "XLV"
    assert parsed["bearish"] == "XLI"
    assert parsed["pruned"] == "0"
    assert parsed["hunt"] == "2"
    assert parsed["health"] == "OK"


def test_diff_summaries_detects_changes():
    prev = {"regime": "A", "top": "XLV", "bearish": "XLI", "pruned": "0"}
    curr = {"regime": "B", "top": "XLE", "bearish": "XLI", "pruned": "0"}
    changes = daily_review.diff_summaries(prev, curr)
    labels = [c[0] for c in changes]
    assert "Regime" in labels and "Top sector" in labels
    assert len(changes) == 2


def test_diff_summaries_identical_is_empty():
    s = {"regime": "A", "top": "XLV", "bearish": "XLI", "pruned": "0"}
    assert daily_review.diff_summaries(dict(s), dict(s)) == []


def test_diff_summaries_ignores_missing_prev_keys():
    prev = {"regime": "A"}  # no top/bearish/pruned keys
    curr = {"regime": "A", "top": "XLV", "bearish": "none", "pruned": "0"}
    assert daily_review.diff_summaries(prev, curr) == []


# ---------------------------------------------------------------------------
# main() end-to-end (offline)
# ---------------------------------------------------------------------------
def test_first_run_writes_all_outputs(offline, tmp_path):
    rc = daily_review.main(reports_dir=tmp_path, now=FIXED_NOW)
    assert rc == 0

    latest = (tmp_path / "latest.txt").read_text(encoding="utf-8")
    assert "First run - no baseline." in latest
    assert "SCHD" in latest and "OK" in latest
    assert "Positive Curve (Expansion)" in latest
    assert "ABC" in latest  # hunt output present

    status = (tmp_path / "STATUS.txt").read_text(encoding="utf-8")
    assert status.startswith("OK")

    hist = (tmp_path / "history.log").read_text(encoding="utf-8").strip()
    assert "regime=Positive Curve (Expansion)" in hist
    assert "top=XLV" in hist

    archives = list((tmp_path / "archive").glob("forecast_2026-11-03_0700.txt"))
    assert len(archives) == 1
    assert (tmp_path / "run.log").exists()

    assert offline["push"] == 1
    assert offline["toast"] == []  # first run, no flags


def test_second_run_reports_no_changes_when_identical(offline, tmp_path):
    daily_review.main(reports_dir=tmp_path, now=FIXED_NOW)
    daily_review.main(
        reports_dir=tmp_path, now=datetime(2026, 11, 3, 14, 30, 0)
    )
    latest = (tmp_path / "latest.txt").read_text(encoding="utf-8")
    assert "No material changes since last run." in latest
    assert offline["toast"] == []


def test_second_run_detects_regime_and_leader_change(offline, tmp_path, monkeypatch):
    daily_review.main(reports_dir=tmp_path, now=FIXED_NOW)

    def changed_report():
        return fake_report(regime="Flat Curve (Late Cycle)", top="XLE")

    monkeypatch.setattr(daily_review, "build_sector_report", changed_report)
    daily_review.main(
        reports_dir=tmp_path, now=datetime(2026, 11, 3, 14, 30, 0)
    )

    latest = (tmp_path / "latest.txt").read_text(encoding="utf-8")
    assert "!! CHANGES SINCE LAST RUN !!" in latest
    assert (
        "Regime: Positive Curve (Expansion) -> Flat Curve (Late Cycle)" in latest
    )
    assert "Top sector: XLV -> XLE" in latest

    assert offline["toast"], "action toast should fire on material change"
    title, message = offline["toast"][-1]
    assert "action needed" in title.lower()
    assert "Regime" in message

    # two archive files, both runs recorded
    assert len(list((tmp_path / "archive").glob("forecast_*.txt"))) == 2
    lines = [
        ln
        for ln in (tmp_path / "history.log").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert len(lines) == 2


def test_core_failure_sets_fail_and_keeps_health(offline, tmp_path, monkeypatch):
    def boom():
        raise RuntimeError("FRED down")

    monkeypatch.setattr(daily_review, "build_sector_report", boom)
    rc = daily_review.main(reports_dir=tmp_path, now=FIXED_NOW)
    assert rc == 1

    status = (tmp_path / "STATUS.txt").read_text(encoding="utf-8")
    assert status.startswith("FAIL")
    assert "FRED down" in status

    latest = (tmp_path / "latest.txt").read_text(encoding="utf-8")
    assert "CORE REPORT FAILED" in latest
    assert "FRED down" in latest
    assert "PORTFOLIO HEALTH" in latest  # section C survives core failure
    assert "SCHD" in latest

    assert offline["toast"], "FAIL must toast"
    assert "FAILED" in offline["toast"][-1][0]


def test_hunt_failure_isolated(offline, tmp_path, monkeypatch):
    def boom():
        raise ConnectionError("screen down")

    monkeypatch.setattr(daily_review, "run_hunt", boom)
    rc = daily_review.main(reports_dir=tmp_path, now=FIXED_NOW)
    assert rc == 0  # hunt never fails the run

    latest = (tmp_path / "latest.txt").read_text(encoding="utf-8")
    assert "SKIPPED" in latest
    assert "ConnectionError" in latest
    assert "MACRO REGIME" in latest  # core survived

    status = (tmp_path / "STATUS.txt").read_text(encoding="utf-8")
    assert status.startswith("OK")
    assert "degraded: hunt" in status

    hist = (tmp_path / "history.log").read_text(encoding="utf-8")
    assert "hunt=skip" in hist
    assert offline["toast"] == []  # degraded run, no action flags


def test_no_hunt_flag(offline, tmp_path):
    rc = daily_review.main(reports_dir=tmp_path, now=FIXED_NOW, no_hunt=True)
    assert rc == 0
    latest = (tmp_path / "latest.txt").read_text(encoding="utf-8")
    assert "OFF (--no-hunt)" in latest
    hist = (tmp_path / "history.log").read_text(encoding="utf-8")
    assert "hunt=off" in hist


def test_near_stop_triggers_toast(offline, tmp_path, monkeypatch):
    # price ends at 101 -> 1% above the fixed 100.0 stop -> NEAR_STOP
    monkeypatch.setattr(
        daily_review, "fetch_daily", lambda sym, *a, **k: make_df(end=101.0)
    )
    rc = daily_review.main(reports_dir=tmp_path, now=FIXED_NOW)
    assert rc == 0
    latest = (tmp_path / "latest.txt").read_text(encoding="utf-8")
    assert "NEAR STOP (within 2%)" in latest
    assert offline["toast"], "near-stop must toast"
    assert "near ATR stop" in offline["toast"][-1][1]


# ---------------------------------------------------------------------------
# Retention + toast robustness
# ---------------------------------------------------------------------------
def test_prune_archive_removes_only_old_files(tmp_path):
    arch = tmp_path / "archive"
    arch.mkdir(parents=True)
    old = arch / "forecast_2026-01-01_0700.txt"
    recent = arch / "forecast_2026-11-02_1430.txt"
    junk = arch / "forecast_not-a-date.txt"
    old.write_text("old", encoding="utf-8")
    recent.write_text("recent", encoding="utf-8")
    junk.write_text("junk", encoding="utf-8")

    removed = daily_review.prune_archive(arch, 60, now=datetime(2026, 11, 3))
    assert removed == 1
    assert not old.exists()
    assert recent.exists()
    assert junk.exists()  # unparseable names are left alone


def test_toast_never_raises_on_runner_failure():
    def bad_runner(*a, **k):
        raise OSError("no powershell")

    assert daily_review.toast("t", "m", runner=bad_runner) is False


def test_toast_escapes_quotes():
    seen = {}

    def ok_runner(cmd, **kwargs):
        seen["cmd"] = cmd

    assert daily_review.toast("T", "it's fine", runner=ok_runner) is True
    assert "it''s fine" in seen["cmd"][-1]


def test_bat_launcher_content():
    text = (ROOT / "daily_review.bat").read_text(encoding="utf-8", errors="replace")
    assert "py -3 scripts\\daily_review.py" in text
    assert "PYTHONIOENCODING=utf-8" in text
    assert "finance-project" in text
