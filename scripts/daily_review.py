"""Daily market intelligence briefing - local Task Scheduler entry point.

Sections run in isolation so a hunt or network failure never discards the
core macro/sector report. Outputs (UTF-8) under ``daily_reports/``:

- ``latest.txt``       full report, change alerts at top (the one file to open)
- ``STATUS.txt``       OK/FAIL + timestamp (+ error detail on failure)
- ``history.log``      one-line summaries enabling change detection
- ``archive/forecast_*`` timestamped copies (pruned after 60 days)

A best-effort Windows toast fires on core failure or action flags (stop
breached / near stop / regime or sector-leader change). Network entry
points are module-level names so tests can monkeypatch them offline.
"""

from __future__ import annotations

import logging
import math
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from finance.hunter import run_hunt  # noqa: E402
from finance.memory import push_context  # noqa: E402
from finance.portfolio import load_portfolio  # noqa: E402
from finance.pruner import load_prune_list  # noqa: E402
from finance.risk_guardrails import atr_trailing_stop  # noqa: E402
from finance.sector_rotation import build_sector_report  # noqa: E402
from finance.stock_data import fetch_daily  # noqa: E402

logger = logging.getLogger("daily_review")

DEFAULT_REPORTS_DIR = ROOT / "daily_reports"
ARCHIVE_SUBDIR = "archive"
RETENTION_DAYS = 60
NEAR_STOP_PCT = 0.02
HISTORY_DIFF_FIELDS = ("regime", "top", "bearish", "pruned")
_FIELD_LABELS = {
    "regime": "Regime",
    "top": "Top sector",
    "bearish": "Bearish rotation",
    "pruned": "Pruned count",
}
_ACTION_STATUSES = ("BREACHED", "NEAR_STOP")


# ---------------------------------------------------------------------------
# Portfolio health (ATR trailing stops)
# ---------------------------------------------------------------------------
def compute_health(
    holdings: List[Dict[str, Any]],
    fetch_df: Optional[Callable] = None,
    stop_fn: Optional[Callable] = None,
) -> List[Dict[str, Any]]:
    """Evaluate each holding against its ATR trailing stop.

    Statuses: OK (cushion >= 2%), NEAR_STOP (within 2% above stop),
    BREACHED (price below stop), NO_DATA (fetch/parse failure).
    """
    fetch_df = fetch_df or fetch_daily
    stop_fn = stop_fn or atr_trailing_stop
    rows: List[Dict[str, Any]] = []
    for h in holdings:
        symbol = str(h.get("symbol", "?")).upper()
        row: Dict[str, Any] = {
            "symbol": symbol,
            "shares": h.get("shares"),
            "price": None,
            "stop": None,
            "dist_pct": None,
            "status": "NO_DATA",
            "detail": "",
        }
        try:
            df = fetch_df(symbol)
            if df is None or df.empty:
                row["detail"] = "no price data"
                rows.append(row)
                continue
            stopped = stop_fn(df)
            stop_val = stopped["trailing_stop"].iloc[-1]
            price = float(df["adjusted_close"].iloc[-1])
            if price <= 0 or stop_val is None or math.isnan(float(stop_val)):
                row["detail"] = "stop/price unavailable"
                rows.append(row)
                continue
            stop_val = float(stop_val)
            dist = (price - stop_val) / price
            row.update(price=price, stop=stop_val, dist_pct=dist)
            if price < stop_val:
                row["status"] = "BREACHED"
            elif dist < NEAR_STOP_PCT:
                row["status"] = "NEAR_STOP"
            else:
                row["status"] = "OK"
        except Exception as e:  # noqa: BLE001 - per-symbol isolation
            row["detail"] = f"{type(e).__name__}: {e}"
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# History: one-line summaries + change detection
# ---------------------------------------------------------------------------
def summarize(
    regime_str: str,
    sectors: List[Dict[str, Any]],
    pruned_count: int,
    hunt_state: Dict[str, Any],
    health_rows: List[Dict[str, Any]],
) -> Dict[str, str]:
    """Build the comparable summary dict stored in history.log."""
    top = sectors[0]["symbol"] if sectors else "none"
    bearish = (
        ",".join(
            r["symbol"]
            for r in sectors
            if r.get("classification") == "Bearish Rotation"
        )
        or "none"
    )
    flags = [r for r in health_rows if r.get("status") in _ACTION_STATUSES]
    if hunt_state.get("state") == "ok":
        hunt_val = str(hunt_state.get("qualified", 0))
    else:
        hunt_val = str(hunt_state.get("state", "off"))
    return {
        "regime": regime_str,
        "top": top,
        "bearish": bearish,
        "pruned": str(pruned_count),
        "hunt": hunt_val,
        "health": "OK" if not flags else f"{len(flags)}flag",
    }


def format_history_line(ts: datetime, summary: Dict[str, str]) -> str:
    return (
        f"{ts:%Y-%m-%d %H:%M} | regime={summary['regime']} "
        f"| top={summary['top']} | bearish={summary['bearish']} "
        f"| pruned={summary['pruned']} | hunt={summary['hunt']} "
        f"| health={summary['health']}"
    )


def parse_history_line(line: str) -> Optional[Dict[str, str]]:
    parts = [p.strip() for p in line.split(" | ")]
    if len(parts) < 2:
        return None
    out: Dict[str, str] = {"timestamp": parts[0]}
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            out[key.strip()] = value.strip()
    return out


def read_last_history(history_path: Path) -> Optional[Dict[str, str]]:
    if not history_path.exists():
        return None
    lines = [
        ln for ln in history_path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    if not lines:
        return None
    return parse_history_line(lines[-1])


def diff_summaries(
    prev: Dict[str, str], curr: Dict[str, str]
) -> List[Tuple[str, str, str]]:
    """Return (label, old, new) tuples for changed diffable fields."""
    changes: List[Tuple[str, str, str]] = []
    for key in HISTORY_DIFF_FIELDS:
        old, new = prev.get(key), curr.get(key)
        if old is not None and old != new:
            changes.append((_FIELD_LABELS[key], old, new))
    return changes


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------
def _fmt_pct(v: Optional[float]) -> str:
    return f"{v * 100:+.1f}%" if v is not None else "n/a"


def _fmt_money(v: Optional[float]) -> str:
    return f"${v:,.2f}" if v is not None else "-"


def format_report(
    now: datetime,
    duration_s: float,
    core_error: Optional[str],
    report: Optional[Dict[str, Any]],
    pruned: Dict[str, Any],
    hunt_state: Dict[str, Any],
    health_rows: List[Dict[str, Any]],
    changes: List[Tuple[str, str, str]],
    first_run: bool,
) -> str:
    lines: List[str] = []
    status = f"FAIL ({core_error})" if core_error else "OK"
    lines.append("=== DAILY MARKET BRIEFING ===")
    lines.append(f"Generated: {now:%Y-%m-%d %H:%M:%S} (local)")
    lines.append(f"Status: {status} | duration: {duration_s:.1f}s")

    hunt_label = {
        "ok": f"OK ({hunt_state.get('qualified', 0)} qualified)",
        "skip": f"SKIPPED ({hunt_state.get('error')})",
        "off": "OFF (--no-hunt)",
    }.get(hunt_state.get("state", "off"), "unknown")
    health_flags = [
        r for r in health_rows if r.get("status") in _ACTION_STATUSES
    ]
    health_label = "OK" if not health_flags else f"{len(health_flags)} action(s)"
    lines.append(f"Hunt: {hunt_label} | Health: {health_label}")
    lines.append("")

    # Change alerts (top of report)
    lines.append("!! CHANGES SINCE LAST RUN !!")
    if first_run:
        lines.append("  First run - no baseline.")
    elif changes:
        for label, old, new in changes:
            lines.append(f"  * {label}: {old} -> {new}")
    else:
        lines.append("  No material changes since last run.")
    lines.append("")

    # Portfolio health
    lines.append("!! PORTFOLIO HEALTH (ATR trailing stops) !!")
    header = (
        f"  {'Symbol':<7} {'Shares':>8} {'Price':>10} "
        f"{'ATR Stop':>10} {'Dist':>8}  Status"
    )
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for r in health_rows:
        dist = f"{r['dist_pct'] * 100:+.1f}%" if r["dist_pct"] is not None else "-"
        status_txt = r["status"]
        if r["status"] == "NO_DATA" and r.get("detail"):
            status_txt = f"NO_DATA ({r['detail']})"
        elif r["status"] == "BREACHED":
            status_txt = "BREACHED - review exit"
        elif r["status"] == "NEAR_STOP":
            status_txt = "NEAR STOP (within 2%)"
        lines.append(
            f"  {r['symbol']:<7} {r['shares']:>8} {_fmt_money(r['price']):>10} "
            f"{_fmt_money(r['stop']):>10} {dist:>8}  {status_txt}"
        )
    if health_flags:
        lines.append(
            "  Flags: " + ", ".join(r["symbol"] for r in health_flags) + " need attention"
        )
    lines.append("")

    if core_error:
        lines.append("=== CORE REPORT FAILED ===")
        lines.append(f"Error: {core_error}")
        lines.append("")
        lines.append(
            "Note: macro/sector sections unavailable this run; "
            "history and health sections above are still valid."
        )
        return "\n".join(lines) + "\n"

    regime = report["macro_regime"]
    details = regime.get("details") or {}
    lines.append("=== MACRO REGIME ===")
    lines.append(f"Regime: {regime.get('regime')}")
    yc = details.get("yield_curve_2s10s")
    if yc:
        lines.append(f"2s10s spread: {yc['value']:.2f}% ({yc.get('date')})")
    if "rate_tone" in details:
        lines.append(
            f"10Y tone: {details['rate_tone']} | Risk: {details.get('risk_tone')}"
        )
    if regime.get("note"):
        lines.append(f"Note: {regime['note']}")
    lines.append("")

    lines.append("=== SECTOR ROTATION (vs SPY) ===")
    header = (
        f"{'#':<3} {'ETF':<6} {'Sector':<26} {'RS 1M':>8} {'RS 3M':>8} "
        f"{'RS 6M':>8} {'Composite':>10} {'Classification':<20}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for row in report["sectors"]:
        rs = row.get("rs") or {}
        lines.append(
            f"{row['rank']:<3} {row['symbol']:<6} {row['sector']:<26} "
            f"{_fmt_pct(rs.get('rs_1m')):>8} {_fmt_pct(rs.get('rs_3m')):>8} "
            f"{_fmt_pct(rs.get('rs_6m')):>8} "
            f"{_fmt_pct(row.get('rs_composite')):>10} "
            f"{row.get('classification', ''):<20}"
        )
    lines.append("")

    pruned_map = pruned.get("pruned", {}) if pruned else {}
    lines.append("=== PRUNED (HARD VETO) ===")
    if pruned_map:
        for sym in sorted(pruned_map):
            lines.append(f"  {sym}")
    else:
        lines.append("  No symbols currently vetoed.")
    lines.append("")

    lines.append("=== DARK HORSES (paper-trade candidates) ===")
    if hunt_state.get("state") == "ok":
        qualified = hunt_state.get("rows") or []
        lines.append(f"Qualified: {hunt_state.get('qualified', 0)}")
        for c in qualified[:5]:
            signals = ",".join(c.get("signals") or [])
            lines.append(
                f"  {c.get('symbol')} ({c.get('sector')}) signals={signals}"
            )
        if not qualified:
            lines.append("  None this run.")
    elif hunt_state.get("state") == "skip":
        lines.append(f"SKIPPED: {hunt_state.get('error')}")
    else:
        lines.append("OFF (--no-hunt).")
    lines.append("")
    lines.append(
        "[Reminder: dark-horse output is research-only - paper trading "
        "first per standing rule 2A; never auto-executed.]"
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
def prune_archive(
    archive_dir: Path,
    retention_days: int = RETENTION_DAYS,
    now: Optional[datetime] = None,
) -> int:
    """Delete forecast_YYYY-MM-DD_HHMM.txt files older than retention."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=retention_days)
    if not archive_dir.exists():
        return 0
    removed = 0
    for path in archive_dir.glob("forecast_*.txt"):
        stamp_raw = path.stem[len("forecast_"):]
        try:
            stamp = datetime.strptime(stamp_raw, "%Y-%m-%d_%H%M")
        except ValueError:
            continue
        if stamp < cutoff:
            try:
                path.unlink()
                removed += 1
            except OSError:
                logger.warning("Could not prune %s", path)
    return removed


def toast(title: str, message: str, runner: Optional[Callable] = None) -> bool:
    """Best-effort Windows balloon notification; never raises."""
    runner = runner or subprocess.run
    safe_title = title.replace("'", "''")
    safe_msg = message.replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "Add-Type -AssemblyName System.Drawing;"
        "$n=New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon=[System.Drawing.SystemIcons]::Information;"
        "$n.Visible=$true;"
        f"$n.ShowBalloonTip(6000,'{safe_title}','{safe_msg}',"
        "[System.Windows.Forms.ToolTipIcon]::Warning);"
        "Start-Sleep -Seconds 7;$n.Dispose()"
    )
    try:
        runner(
            [
                "powershell",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-Command",
                ps,
            ],
            timeout=25,
            capture_output=True,
        )
        return True
    except Exception:  # noqa: BLE001 - toast is cosmetic
        logger.warning("Toast notification failed", exc_info=True)
        return False


def write_outputs(
    reports_dir: Path,
    now: datetime,
    report_text: str,
    status_text: str,
    history_line: str,
) -> None:
    archive_dir = reports_dir / ARCHIVE_SUBDIR
    archive_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest.txt").write_text(report_text, encoding="utf-8")
    (reports_dir / "STATUS.txt").write_text(status_text + "\n", encoding="utf-8")
    with (reports_dir / "history.log").open("a", encoding="utf-8") as fh:
        fh.write(history_line + "\n")
    archive_name = f"forecast_{now:%Y-%m-%d_%H%M}.txt"
    (archive_dir / archive_name).write_text(report_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(
    reports_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
    no_hunt: bool = False,
) -> int:
    reports_dir = Path(reports_dir) if reports_dir else DEFAULT_REPORTS_DIR
    now = now or datetime.now()
    reports_dir.mkdir(parents=True, exist_ok=True)
    log_path = reports_dir / "run.log"
    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    t0 = time.monotonic()

    # Section A: core (macro + sectors + prune list) - failure => FAIL status
    core_error: Optional[str] = None
    report: Optional[Dict[str, Any]] = None
    pruned: Dict[str, Any] = {}
    try:
        report = build_sector_report()
        pruned = load_prune_list()
    except Exception as e:  # noqa: BLE001 - degrade, do not crash
        core_error = f"{type(e).__name__}: {e}"
        logger.exception("Core report failed")

    # Section B: hunt - isolated, never fails the run
    hunt_state: Dict[str, Any] = {
        "state": "off" if no_hunt else "skip",
        "qualified": None,
        "rows": [],
        "error": None,
    }
    if no_hunt:
        hunt_state["error"] = "--no-hunt"
    else:
        try:
            hunt = run_hunt()
            qualified = hunt.get("qualified") or []
            hunt_state = {
                "state": "ok",
                "qualified": len(qualified),
                "rows": qualified,
                "error": None,
            }
        except Exception as e:  # noqa: BLE001 - isolated
            hunt_state["state"] = "skip"
            hunt_state["error"] = f"{type(e).__name__}: {e}"
            logger.exception("Hunt failed (report continues)")

    # Section C: portfolio health - isolated
    health_rows: List[Dict[str, Any]] = []
    try:
        holdings = load_portfolio()
        health_rows = compute_health(holdings)
    except Exception as e:  # noqa: BLE001 - isolated
        logger.exception("Health section failed")
        health_rows = [
            {
                "symbol": "-",
                "shares": "-",
                "price": None,
                "stop": None,
                "dist_pct": None,
                "status": "NO_DATA",
                "detail": f"{type(e).__name__}: {e}",
            }
        ]

    # Summary + change detection
    if report is not None:
        regime_str = report["macro_regime"].get("regime", "Unknown")
        sectors = report.get("sectors") or []
    else:
        regime_str = "ERROR"
        sectors = []
    pruned_count = len((pruned or {}).get("pruned", {}))
    summary = summarize(regime_str, sectors, pruned_count, hunt_state, health_rows)

    history_path = reports_dir / "history.log"
    prev = read_last_history(history_path)
    first_run = prev is None
    changes = diff_summaries(prev, summary) if prev else []

    duration = time.monotonic() - t0
    report_text = format_report(
        now=now,
        duration_s=duration,
        core_error=core_error,
        report=report,
        pruned=pruned,
        hunt_state=hunt_state,
        health_rows=health_rows,
        changes=changes,
        first_run=first_run,
    )

    ts = f"{now:%Y-%m-%d %H:%M:%S}"
    if core_error:
        status_text = f"FAIL {ts} | core error: {core_error}"
    else:
        degraded = " (degraded: hunt)" if hunt_state["state"] == "skip" else ""
        status_text = f"OK {ts} | duration={duration:.1f}s | hunt={hunt_state['state']}{degraded}"
    write_outputs(
        reports_dir,
        now,
        report_text,
        status_text,
        format_history_line(now, summary),
    )
    prune_archive(reports_dir / ARCHIVE_SUBDIR, RETENTION_DAYS, now)

    # Best-effort memory push so the next opencode session sees the briefing
    try:
        push_context(
            f"Daily briefing {now:%m-%d %H:%M}: macro {regime_str}, "
            f"top {summary['top']}, flags {summary['health']}"
        )
    except Exception:  # noqa: BLE001 - cosmetic
        logger.warning("push_context failed", exc_info=True)

    # Toast: FAIL or action flags / material changes
    if core_error:
        toast("Finance briefing FAILED", f"Core report error: {core_error[:150]}")
    else:
        actions: List[str] = []
        for r in health_rows:
            if r["status"] == "BREACHED":
                actions.append(f"{r['symbol']} STOP BREACHED")
            elif r["status"] == "NEAR_STOP":
                actions.append(f"{r['symbol']} near ATR stop")
        for label, old, new in changes:
            actions.append(f"{label}: {old} -> {new}")
        if actions:
            toast("Finance briefing - action needed", "; ".join(actions)[:180])

    return 1 if core_error else 0


if __name__ == "__main__":
    sys.exit(main(no_hunt="--no-hunt" in sys.argv[1:]))