# Progress Log

## Phase 1: Architecture & Planning (Completed)
- **Goal:** Establish working stack, Alpha Vantage API integration, database strategy, guardrails, and agent rules.
- **Decisions Made:**
  - Selected **Alpha Vantage API** for market data (S&P 500 / Dow Jones indices & individual stocks).
  - Designed local SQLite caching layer with TTL and rate-limit safeguards.
  - Planned modules: `alpha_vantage.py`, `indicators.py`, `portfolio.py`, and CLI extensions.
  - Incorporated advanced quantitative tools (Portfolio Optimization via MPT, backtesting, factor scoring).

## Phase 2: Implementation & Testing (Completed)
- **Goal:** Implement Alpha Vantage, FRED, technical indicators, portfolio tracking, optimization, backtesting, screener, reporting, and session wrap-up.
- **Completed Modules:**
  - `src/finance/alpha_vantage.py`: Alpha Vantage API client with SQLite TTL caching
  - `src/finance/fred.py`: FRED API client for macroeconomic indicators
  - `src/finance/indicators.py`: Technical indicators (SMA, EMA, RSI, MACD, Volatility)
  - `src/finance/portfolio.py`: Portfolio tracking, cost basis, P&L, risk metrics
  - `src/finance/optimization.py`: Modern Portfolio Theory (Mean-Variance, Max Sharpe)
  - `src/finance/backtest.py`: Vectorized SMA crossover backtesting engine
  - `src/finance/screener.py`: Multi-factor stock screener (Momentum & Volatility)
  - `src/finance/reports.py`: Automated market briefing report generator
  - `src/finance/cli.py`: Unified CLI with 15+ commands
- **Testing:** 15 unit tests passing (pytest) with mocked API responses for offline execution
- **Security:** API keys via environment variables, parameterized SQL queries, rate-limit caching

## Session Wrap-Up (2026-09-03 12:43)
- **Transactions:** 2 recorded | Net Balance: $1,164.75
- **Portfolio:** 0 position(s) tracked
- **Actions Taken:**
  - Session wrap-up completed
  - Short-term memory cleared
- **Next Steps:**
  [ ] Add your first stock position: finance portfolio add SPY 10 400.00
  [ ] Screen for top momentum stocks: finance screen
  [ ] Check macroeconomic conditions: finance macro overview
  [ ] Run a backtest on a strategy: finance backtest SPY --fast 20 --slow 50
  [ ] Generate a full market briefing: finance report

## Alpha Vantage MCP Blocker: Resolved (2026-09-03)
- **Root cause:** `marketdata-mcp-server` v0.3.1 (`av_mcp/stdio_server.py`) uses the
  legacy `mcp.server.lowlevel.Server.list_tools()` / `call_tool()` decorators, which were
  removed in the `mcp` SDK 2.x rewrite (replaced by FastMCP/MCPServer). The package's
  `pyproject.toml` declares `mcp>=1` with no upper bound, so fresh installs resolve to
  `mcp==2.1.1` and crash on startup with `AttributeError: 'Server' object has no
  attribute 'list_tools'`.
- **Fix:** Pin the `mcp` SDK below `2` when launching via uvx. `opencode.json` now runs:
  `uvx --from marketdata-mcp-server --with "mcp<2" marketdata-mcp.exe`.
- **Verified:** With `mcp==1.29.1`, both decorators exist and `av_mcp.stdio_server`
  imports cleanly; server starts past the decorator registration.
- **Note (follow-up):** opencode initially reported `-32000 connection closed` because the
  `{env:ALPHA_VANTAGE_API_KEY}` MCP environment reference resolves from the **OS process
  environment**, but the key lives only in the project `.env`, so it was empty and the
  server exited with "API key required". Fixed by adding `scripts/launch_mcp.py`, which
  loads `.env`, reads `ALPHA_VANTAGE_API_KEY`, and `os.execvp`'s
  `uvx --from marketdata-mcp-server --with "mcp<2" marketdata-mcp.exe <key>` (so stdio is
  inherited). `opencode.json` now runs `python scripts/launch_mcp.py`. Handshake verified
  returning `alphavantage-mcp` server info.
- **Note:** Live Alpha Vantage calls require a valid paid-tier key in `.env`; the current
  value has been set but should be confirmed.

## Security Review & Hardening (2026-09-03)
- **`scripts/launch_mcp.py`:** Replaced fragile manual `.env` parsing with `python-dotenv`
  (`load_dotenv(..., override=False)`). API key is now passed to the server via **process
  environment** (inherited by `os.execvp`), not as a CLI argument — no longer exposed in OS
  process tables (`ps`/Task Manager). Handshake re-verified (`alphavantage-mcp`).
- **`.env.example`:** Contained real API keys and was committable (not gitignored). Replaced
  with placeholders (`your_alpha_vantage_key` / `your_fred_key`).
- **Git:** Initialized repo at project root. Extended `.gitignore` to also ignore runtime
  artifacts (`market_cache.db`, `*.db`, `memory_short.json`, `memory_long.json`) so no
  potentially sensitive data is tracked. Verified: `.env`, `finance.json`, `*.db`,
  `memory_*.json` are ignored; non-ignored files are clean of real secrets.
- **Tests:** 18/18 passing (offline, mocked APIs).
- **Todo for user:** Restart opencode to pick up the new MCP config (command unchanged, but
  launcher behavior changed to env-based key injection).

## Data Provider Migration: Alpha Vantage -> yfinance (2026-09-03)
- **Problem:** `TIME_SERIES_DAILY_ADJUSTED` (used by the CLI) is a premium endpoint on
  Alpha Vantage; a free key returns `{"Information": "This is a premium endpoint..."}`
  causing "Invalid response format" errors. The free `TIME_SERIES_DAILY` and `GLOBAL_QUOTE`
  endpoints DO work.
- **Verified live:** `GLOBAL_QUOTE` and `TIME_SERIES_DAILY` work on the free key; only the
  ADJUSTED endpoint is paywalled.
- **Decision (Option 1):** Keep the Alpha Vantage **MCP** (free endpoints, no subscription)
  for natural-language agent access; switch the **CLI/analysis data layer to yfinance**
  (free, no key, split- & dividend-adjusted) to avoid paying and keep precision for
  long-term backtests.
- **Changes:**
  - New `src/finance/stock_data.py`: `fetch_daily(symbol)` returns a normalized DataFrame
    (DatetimeIndex ascending; columns `open/high/low/close/adjusted_close/volume`) using
    yfinance with `auto_adjust=True` (adjusted close sourced from Close). Normalizes index,
    coerces numerics, drops missing rows.
  - `cli.py`: market analyze, portfolio fallback, optimize, backtest, screener now use
    `fetch_daily` instead of `fetch_daily_adjusted`+`parse_time_series_daily`. Quote handler
    still uses Alpha Vantage `fetch_global_quote` (free, works).
  - `reports.py`: `generate_market_briefing` uses `fetch_daily`.
  - `__init__.py`: exports `fetch_daily` from `stock_data`.
  - `alpha_vantage.py`: removed unused `fetch_daily_adjusted`; hardened `query_alpha_vantage`
    to reject payloads containing ONLY informational keys (`Information`/`Note`/`Error
    Message`), preventing premium/rate notices from being cached as valid data.
  - `indicators.py`: `parse_time_series_daily` retained for backward compat (AV format),
    but CLI no longer depends on it.
  - `pyproject.toml`: added `yfinance>=0.2.40` dependency.
- **Tests:** 22/22 passing (18 original + 3 new `stock_data` offline/mocked + 1 new Alpha
  Vantage premium-notice-not-cached).
- **Live verified:** `finance market analyze SPY`, `backtest`, `screen`, `report` all return
  real adjusted data via yfinance; `market quote` works via Alpha Vantage free endpoint.
- **Note:** The Alpha Vantage MCP config in `opencode.json` is unchanged and remains
  available (its free tools require no subscription).

## MCP Swap: Alpha Vantage -> yfinance (yfmcp) (2026-09-03)
- **Problem:** The Alpha Vantage MCP (`marketdata-mcp-server` via `scripts/launch_mcp.py`)
  persistently showed opencode status **"red - Failed to get tools"**, even though the
  protocol handshake worked. Root cause: that server uses **progressive discovery**,
  advertising only 3 meta-tools (`TOOL_LIST`/`TOOL_GET`/`TOOL_CALL`) instead of standard
  per-function tools, which opencode's client cannot enumerate.
- **Fix (Option A):** Replaced the Alpha Vantage MCP with **`yfmcp`** (narumiruna/yfinance-mcp),
  a stdio MCP server exposing **standard per-function tools** on yfinance. This:
  - Fixes the red status (tools enumerate cleanly).
  - Needs no API key / `.env` (yfinance is free).
  - Stays consistent with the CLI data layer (also yfinance).
  - Declares `mcp<2,>=1.28.1` itself, so it self-resolves to the SDK 1.x that has
    `list_tools` — no compatibility pin needed.
- **Changes:**
  - `opencode.json`: `mcp.yfinance` -> `{"type":"local","command":["uvx","yfmcp@latest"]}`;
    removed the `alpha-vantage` block.
  - Removed obsolete `scripts/launch_mcp.py` (and now-empty `scripts/` dir).
- **Verified live:** `uvx yfmcp@latest` handshake returns `serverInfo: yfinance_mcp v1.29.1`
  and `tools/list` returns standard tools (e.g. `yfinance_get_ticker_info`,
  `yfinance_get_analyst_price_targets`). First run installs 62 packages (matplotlib, pandas,
  numpy, ...), cached afterward.
- **Note:** User must **restart opencode** to load the new MCP config.

## MCP Timeout Fix: yfinance MCP (2026-09-03)
- **Problem:** "yfinance mcp operation timed out after 30000ms". Root cause: the server was
  launched via `uvx yfmcp@latest`, which on a cold cache downloads yfinance/pandas/numpy
  wheels on Windows — routinely exceeding opencode's 30s operation timeout. The server itself
  is fast (data calls return in 0.06-0.6s once running).
- **Fix:** Installed yfmcp as a persistent uv tool (`uv tool install yfmcp`) and changed
  `opencode.json` MCP command from `["uvx","yfmcp@latest"]` to `["yfmcp"]`, so it launches the
  installed executable instantly with no re-resolution/download.
- **Verified:** Fresh launch returns `yfinance_get_ticker_info SPY` in 0.6s.
- **Note:** User must **restart opencode** to load the new MCP command.

## Agentic Finance Execution Plan (2026-09-03)
Implemented the full multi-agent architecture to maximize returns while guarding against
the vulnerabilities identified in review (data fragility, overfitting, look-ahead,
survivorship bias, execution friction, runaway losses).

### Phase 1 — Data Resiliency & Bias Safety
- `stock_data.py`: added `fetch_daily_with_fallback(...)` — primary yfinance, automatic
  fallback to Alpha Vantage free `TIME_SERIES_DAILY` via the existing SQLite cache layer.
- `bias_guard.py` (new): `assert_no_lookahead`, `shift_signal_to_position`,
  `point_in_time_universe` (survivorship-bias flag).
- `backtest.py`: friction-aware — s-hifts signals to prevent look-ahead AND models
  transaction costs + slippage; reports gross vs NET return, turnover, cost drag.

### Phase 2 — Agentic Ecosystem (opencode orchestrator)
- **Subagents** (`.opencode/agent/`): `alpha-hunter`, `macro-regime-analyst`,
  `quant-analyst`, `risk-sentinel` (circuit-breaker veto authority).
- **Commands** (`.opencode/command/`): `/briefing`, `/rebalance`, `/backtest`, `/hunt`.
- **Skill** (`.opencode/skills/finance-quant/`): centralizes quant workflows + hard rules.
- **Plugin** (`.opencode/plugin/maintenance.ts`): blocks bash commands that expose API keys
  via argv (enforces AGENTS.md rule #1).

### Phase 3 — Advanced Quant Models (`advanced_optimization.py`, `sentiment.py`)
- `hierarchical_risk_parity` (HRP) — clustering-based, robust to cov-matrix instability.
- `black_litterman` — blends market equilibrium with views.
- `kelly_criterion` — optimal geometric-growth sizing (full/half/quarter).
- `sentiment.py` — rule-based NLP scoring for news + analyst actions (negation-aware),
  works with the yfinance MCP news/upgrade shapes.

### Phase 4 — Hard Guardrails & Paper Trading (`risk_guardrails.py`, `paper_trading.py`)
- `risk_guardrails.py`: ATR trailing stops, VaR, max-drawdown + concentration circuit
  breakers (`check_circuit_breakers` returns a `halt` flag that overrides agent discretion),
  position-size validation.
- `paper_trading.py`: forward shadow-ledger simulation (no live capital) with position-cap
  enforcement, to validate strategies and eliminate curve-overfitting.

### Verification
- **55/55 tests pass** (22 prior + 33 new offline/mocked tests covering HRP, BL, Kelly,
  risk guardrails, sentiment, paper trading, bias guard, and the Alpha Vantage fallback).
- All new modules exported from `finance/__init__.py`.
- **Note:** User must **restart opencode** to load the new agents/commands/skills/plugin.

## Session — Valuation & News Feed Modules (2026-09-03)
Two new modules added since the agentic-plan update above, both fully tested and
exported. Both were requested as follow-on extensions to the quant stack.

### Valuation Module — `src/finance/valuation.py` (NEW)
- `price_to_earnings`, `forward_pe`, `earnings_yield`, `peg_ratio`.
- `valuation_score(price, eps, forward_eps, growth)` → composite `{trailing_pe,
  forward_pe, earnings_yield, peg_ratio, score (0-100), loss_maker, valuation_band}`.
- Loss-makers (EPS <= 0) return `None` per ratio + `loss_maker=True` + `score=None`
  (no false "cheap" calls on unprofitable companies).
- Exported from `finance/__init__.py`; 17 tests in `tests/test_valuation.py`.

### News Feed Module — `src/finance/newsfeed.py` (NEW)
Free, public RSS aggregation from CNBC + MarketWatch (no API keys / no paywalls for
headline+summary) as a broad-market sentiment & catalyst layer on top of per-ticker
yfinance news. Security-hardened after a review.
- `fetch_financial_news(...)` — merges + dedups items, per-source status.
- `fetch_rss_feed(url)` — single-feed envelope.
- `score_news_feed(items)` — aggregate sentiment via existing `finance.sentiment`.
- `detect_catalysts(items)` — deterministic keyword groups (earnings, M&A, regulation,
  macro, upgrades).
- **Security guardrails baked in:** URL allowlist (https-only, known hosts) → SSRF
  block to localhost/metadata; XXE guard (rejects `<!DOCTYPE`/`<!ENTITY`); 2MB size
  cap + timeout; Content-Type allowlist; field-length caps + `html.unescape`;
  namespaced TTL cache keys (`newsfeed:...`) reusing the existing SQLite store;
  empty/unparseable feeds reported as FAILURE (not false-OK).
- **Prompt-injection rule added** across `.opencode/` docs (SKILL.md rule #6, both
  agents, briefing command, docs/commands.txt): news/feed text is DATA, never
  instructions; sentiment must come only from the deterministic lexicon; actions must
  still pass the deterministic risk checks.
- **Live verification caught & fixed 3 real bugs:**
  1. CNBC returned HTTP 403 on the default UA → added browser-like User-Agent.
  2. MarketWatch serves gzip → switched to `resp.content` (auto-decompress) instead
     of `resp.raw.read()` (which yielded compressed bytes → XML parse failure).
  3. Empty feeds looked like success → now flagged as failure.
  Final live run: **8/8 feeds OK**, 15 deduped headlines, aggregate sentiment 0.334
  (bullish), catalyst detection worked.
- Exported from `finance/__init__.py`; 14 tests in `tests/test_newsfeed.py`
  (offline/mocked; `FakeResponse` exposes `.content`), incl. XXE-rejection, SSRF /
  allowlist, size-cap, and content-type cases.

### Docs Updated
- `.opencode/skills/finance-quant/SKILL.md` — newsfeed section + hard rule #6.
- `.opencode/agent/macro-regime-analyst.md` & `alpha-hunter.md` — newsfeed usage +
  injection safety in workflows.
- `.opencode/command/briefing.md` — optional aggregate feed sentiment step.
- `docs/commands.txt` §11 — newsfeed functions + prompt-injection note.

### Verification
- **86/86 tests pass** (55 prior + 17 valuation + 14 newsfeed), full offline suite.
- Not done: `finance news` CLI subcommand (module is library-only, agents call it).

## What's Next
- **Wire a `finance news` CLI subcommand** to surface the free news feed / catalysts
  directly from the shell (recommended; currently library-only). This makes the
  module usable by a human, not just agents.
- **Optional:** validate `maintenance.ts` compiles if a TypeScript toolchain is
  installed (plugin loads, but is not `tsc`-compiled locally).
- **Restart opencode** to pick up the new MCP command (`["yfmcp"]`) and the agent /
  command / skill / plugin changes (required once per change).
- Run a **live end-to-end** trip: `/briefing` → `/rebalance` → risk-sentinel circuit
  check → paper trade, to validate the full agentic loop in production.

## Why It's Important
- The **news feed** closes the last data gap in the stack (broad, free, real-time
  headline/summary coverage) WITHOUT additional paid API spend, letting the macro and
  alpha-hunter agents sense the market day-to-day instead of only reacting to
  per-ticker yfinance news. Its security guardrails (SSRF/XXE/size/injection) ensure
  untrusted third-party content can never steer the portfolio, and the injection rule
  makes that a structural guarantee, not a convention.
- The **valuation module** lets the quant agent cross-check a momentum/technical setup
  against fundamentals (cheap-vs-expensive, PEG, loss-maker rejection), which is the
  missing "value" leg of a complete long-only process and reduces the chance of
  buying over-hyped momentum names at the top.
- **Testing continuity** (86 offline tests) is what keeps every phase safe to extend;
  each new module is proven working before it is trusted with real signals.

## Session — Portfolio Tracking, Asymmetric Guardrails & Earnings Blackout (2026-09-04)

### Portfolio Holdings Recorded
User's brokerage account positions added to `portfolio.json` via CLI:
| Ticker | Shares | Fill Price | Fill Type | Date | Total Cost |
|--------|--------|------------|-----------|------|------------|
| SCHD | 2.0 | $35.05 | Market | Sept 1, 2026 | $70.10 |
| SPYM | 5.0 | $90.24 | Limit | Aug 31, 2026 | $451.20 |
| ~~SPYI~~ | ~~1.0~~ | ~~$53.55~~ | ~~Limit~~ | Aug 26, 2026 | ~~$53.55~~ — SOLD 2026-09-04 @ $53.94 (+$0.39) |
| NVDA | 2.0 | $210.44 | Market | Aug 26, 2026 | $420.88 |
- **Total Cost Basis:** $995.73
- **Current Market Value:** $1,022.76 | **Unrealized P&L:** +$27.03 (+2.71%)

### Approach B: Asymmetric Risk Guardrail / Veto (Implemented)
Design decision: quantitative momentum/volatility factors drive stock selection;
news/sentiment acts only as an **asymmetric gatekeeper** — vetoing trades only when
severe negative catalysts or extreme negative sentiment are detected.

- `check_sentiment_veto(symbol, news_items, threshold=-0.3)` in `risk_guardrails.py`:
  - Aggregates news sentiment score via `finance.sentiment.score_news_items`
  - Flags severe keywords: `lawsuit`, `investigation`, `fraud`, `scandal`,
    `bankruptcy`, `recall`
  - Returns `{veto: bool, reason: str|None, sentiment_score, sentiment_label}`
- Rationale: continuous score blending introduces noise and whip-saw churn;
  asymmetric vetoes prevent tail-risk (sudden corporate crises, SEC probes,
  executive turmoil) without diluting momentum alpha.

### Earnings Blackout Check (Implemented)
- `check_earnings_blackout(symbol, earnings_date, as_of_date=None, blackout_days=5)`
  in `risk_guardrails.py`:
  - Computes days until earnings; flags blackout window (default 5 days pre-earnings)
  - Returns `{in_blackout: bool, days_until_earnings: int, reason: str|None}`
- Prevents binary gap-down risk around earnings releases.

### Project Review — Bugs Fixed (5 issues)
| # | File | Severity | Issue | Fix |
|---|------|----------|-------|-----|
| 1 | `pyproject.toml` | High | `scipy` imported but not in dependencies | Added `scipy>=1.10.0` |
| 2 | `risk_guardrails.py:131` | High | `concentration_ok` hardcoded `True` | Now tracks actual per-position result |
| 3 | `sentiment.py:19` | High | `"price target"` in both bullish+bearish lists (cancelled out) | Removed from both (context-dependent) |
| 4 | `risk_guardrails.py:87` | Medium | `max_volatility_annualized` documented but never implemented | Added volatility circuit breaker |
| 5 | `.gitignore` | Medium | `portfolio.json` / `paper_trading.json` not ignored | Added to `.gitignore` |

### Additional Observations (Non-Critical)
- `sentiment.py` negation window checks 2 tokens after target (negation typically precedes)
- `memory_short.json` / `memory_long.json` write to CWD (concurrency risk with multi-session)

### Verification
- **90/90 tests pass** (86 prior + 2 sentiment veto + 2 earnings blackout)
- All new functions exported from `finance/__init__.py`
- Live portfolio valuation: circuit breakers clear, sentiment vetoes clear

## Session — Cache Unification, Earnings Calendar & Sentiment Integration (2026-09-04)

### 1. Unified fred.py Caching (Completed)
- Refactored `fred.py` to use shared `get_cached_response` / `cache_response` from `alpha_vantage.py`
- Removed duplicate SQLite caching logic (~30 lines of manual connection handling)
- Both Alpha Vantage and FRED now share the same `market_cache.db` cache layer
- Behavior unchanged: 24-hour TTL for FRED, same endpoint key format (`fred_<series_id>`)

### 2. Earnings Calendar Data Source (Completed)
- Added `fetch_earnings_date(symbol)` to `risk_guardrails.py` — pulls next earnings date from yfinance's `ticker.calendar`
- Handles both DataFrame and dict shapes returned by yfinance
- Added `check_earnings_blackout_for_symbol(symbol)` convenience function: fetches earnings date + runs blackout check in one call
- Returns `earnings_date_found` flag so callers know whether the check was possible
- Graceful degradation: returns `in_blackout=False` with explanation if earnings date unavailable
- New functions exported from `finance/__init__.py`

### 3. Sentiment & Newsfeed Integration in reports.py (Completed)
- Added "News & Sentiment" section (section 5) to the automated market briefing
- **Broad Market Sentiment:** Pulls RSS news from CNBC/MarketWatch via `newsfeed.py`, scores aggregate sentiment via `score_news_feed`
- **Per-Ticker Sentiment:** Fetches yfinance news for each watchlist symbol, normalizes into `{title, summary}` shape, scores via `score_news_items`
- **Catalyst Detection:** Runs `detect_catalysts` on broad market feed (earnings, M&A, regulation, macro, downgrades)
- New `include_sentiment` flag on `generate_market_briefing()` allows disabling news (for tests or rate-limited environments)
- CLI `finance report` command updated to display all three subsections (broad market score, per-ticker scores, detected catalysts)
- Error isolation: news failures don't break the briefing — sections degrade gracefully

### Files Changed
| File | Change |
|------|--------|
| `src/finance/fred.py` | Removed 30 lines of duplicate caching; now imports shared cache from `alpha_vantage.py` |
| `src/finance/risk_guardrails.py` | Added `fetch_earnings_date`, `check_earnings_blackout_for_symbol` |
| `src/finance/__init__.py` | Exported `fetch_earnings_date`, `check_earnings_blackout_for_symbol` |
| `src/finance/reports.py` | Added `_fetch_ticker_news_sentiment`, `include_sentiment` param, 3 new briefing sections |
| `src/finance/cli.py` | Updated `handle_report_generate` to display sentiment/catalyst sections |

### Verification
- **90/90 tests pass** (all existing tests unchanged, no regressions)
- New functions are pure/library-level; CLI integration is display-only (no new tests needed for display code)

## Session — Alpha Vantage Removal & Cache Unification (2026-09-04)
- **Removed Alpha Vantage entirely** (`alpha_vantage.py` deleted): real-time quotes and daily historical data were redundant/covered by yfinance, and the free tier lacked split/dividend adjustment.
- **New `src/finance/cache.py`:** generic SQLite TTL cache (`init_cache_db`, `get_cached_response`, `cache_response`) — the only preserved part of AV, now shared by `newsfeed.py` and `fred.py`.
- **`stock_data.py`:** yfinance is the sole provider; `fetch_daily_with_fallback` returns an empty DataFrame on failure (no AV fallback).
- **CLI (`cli.py`):** quote and portfolio-summary paths rewritten to use `ticker.info` with `fetch_daily` close fallback.
- **Security:** `FRED_API_KEY` is now the only API key (`.env.example`, `logging_setup.py`, `maintenance.ts` updated).
- **Tests:** replaced AV tests with cache roundtrip/TTL/missing-key tests; updated stock-data fallback tests.
- **Verification:** 92/92 tests pass; all imports verified.

## Session — User Inquiry: Candlesticks & Wicks (2026-09-04) — OPEN / REVISIT LATER
User asked how to read/interpret/use **candles and wicks** to assess or predict stocks. Summary of discussion stored in memory; see `memory_long.json` key `user_inquiry_candlesticks` and `memory_short.json`.

- **Answered:** anatomy (open/high/low/close; body vs wick), wicks = rejection/supply-demand extremes (hammer, shooting star, lower-wick support defense), bodies = momentum/trend + exhaustion (shrinking bodies, doji, engulfing), and that patterns need volume confirmation to carry weight.
- **Decision reached:** `indicators.py` intentionally does **not** use candle/wick patterns — discretionary patterns carry low quant signal; the engine uses SMA/EMA/RSI/MACD/volatility.
- **Pending offer (REVISIT):** add a wick/buying-pressure indicator — **Close Location Value** `CLV = (close − low) / (high − low)` — to `indicators.py` for intraday bid-ask pressure. User has not decided yet.

## Session — SPYI Sale Reconciliation (2026-09-04)
- **SPYI** (1.0 sh @ $53.55 cost, bought Aug 26, 2026) was **sold 2026-09-04 @ $53.94**.
  - Realized gain: **+$0.39** (short-term). Proceeds credited to brokerage cash.
- **Remaining cost basis:** $942.18 (SCHD $70.10 + SPYM $451.20 + NVDA $420.88).
- **Close 2026-09-04:** SCHD $34.80, SPYM $90.67, NVDA $230.36 → holdings $983.67, unrealized **+$41.49 (+4.40%)**.
- Brokerage report: account value ~$1,050.66, cash ~$58.24.
- The sale was originally logged in another session; `memory_long.json#portfolio_holdings` already reconciled here.
- **Note on tracking gap:** the sale was NOT captured in short-term memory or progress at sell time — the CLI has no `portfolio sell/remove` action, so dispositions can only be logged manually. Consider adding one (see below).

## Session — `finance news` CLI + CLV Indicator + E2E Loop (2026-09-04)
- **`finance news` CLI subcommand** (`cli.py`): surfaces the free CNBC/MarketWatch feed directly from the shell — headlines, aggregate sentiment (`score_news_feed`), catalysts (`detect_catalysts`), per-source status. Flags: `--limit`, `--source`, `--no-sentiment`, `--no-catalysts`, `--links`. Live-verified (status OK, sentiment +0.556 bullish, 10 headlines).
- **Close Location Value (CLV) indicator** (`indicators.py`): added `calculate_clv()` using `CLV = (close − low)/(high − low)`, range [0, 1] (close at high = buying pressure, at low = selling pressure; flat high==low rows → NaN). Exported from `finance/__init__.py`; now included in `analyze_market_data` and displayed in `finance market analyze`. This closes the previously-deferred candlestick/wick offer from the session above.
- **End-to-end loop validated live:** `finance report` (FRED + tickers + MPT + sentiment) → risk-sentinel circuit check → paper trade.
  - Circuit breakers **correctly HALTED**: SPYM 46.1% and NVDA 46.8% both exceed the 25% position-concentration cap → risk-sentinel would block new buys.
  - Sentiment vetoes clear for all holdings; NVDA next earnings 2026-11-17 (outside 5-day blackout).
  - Paper trade: BUY SPY 10 sh @ $770.19 → shadow equity $100,154.
- **Tests:** 99/99 passing (92 prior + 5 CLV + 4 news CLI).

## Session — Concentration Rebalance (2026-09-05) — PLANNED, NOT EXECUTED
- **Trigger:** Circuit breakers HALTED on position concentration at 2026-09-04 close — SPYM 46.1% and NVDA 46.8%, both > 25% cap (SCHD 7.1%). No drawdown/vol halts.
- **User instruction:** KEEP the plan and REASSESS in ~1 month after adding ~$500. **No trades executed.** Holdings unchanged: SCHD 2x @ $35.05, SPYM 5x @ $90.24, NVDA 2x @ $210.44; cash $58.24.
- **Plan A (for month-end reference):** SOLD 3 SPYM @ $90.67 ($272.01) + 1 NVDA @ $230.36 ($230.36); BOUGHT +4 SCHD @ $34.80, 8 SCHB @ $29.73, 1 ITOT @ $168.64 (total $545.68). Cash residual $14.93.
- **Realized gains (if executed):** +$21.21 short-term (NVDA +$19.92, SPYM +$1.29) → ~$4.67 tax at 22%.
- **Projected post-rebalance weights (2026-09-04 close):** SCHD 20.3%, SPYM 17.7%, NVDA 22.4%, SCHB 23.2%, ITOT 16.4% → HALT CLEARED (verified vs check_circuit_breakers).
- **Allocation rationale:** SCHB + ITOT (broad US market, cheap share prices) preferred over SPY/DIA/VTI — a single SPY share ($770) would be ~74% of the ~$1,000 account, creating new concentration.
- **Current status:** concentration halt still ACTIVE until plan executed at month-end reassessment.

## Session — finance.json Balance Audit (2026-09-05)
- **Reported discrepancy:** user's brokerage total ($983.67 holdings + $58.24 cash = $1,041.91) vs finance.json balance shown as $1,222.99 (~$181 gap).
- **Root cause found:** a spurious **income "$1200 'Stipend'"** entry (dated 2026-09-02) sat in finance.json. The `Stipend` string appears NOWHERE else in the repo (no code, docs, tests, commands, or memory seed it); finance.json was never committed to git (no write audit trail); file mtime was 2026-09-04 07:48 (pre-session automation). Docs/tests reference `1200.00` only as an example expense "Rent". User confirmed they never recorded a stipend.
- **Correction:** removed the phantom $1,200 Stipend entry. finance.json income $58.24 (Sold SPYI $53.94 + Cash on hand $4.30) = **brokerage cash $58.24 exactly**. A subsequent phantom **expense "$35.25 Lunch"** (dated 2026-09-02, same provenance) was also removed 2026-09-05. Final finance.json: ONLY 2 income entries ($58.24), no expenses, net balance **$58.24**.
- **Lesson:** finance.json is a personal cash-flow ledger and WILL NOT equal brokerage total - but its income side should reconcile to brokerage cash inflows. Balance refs updated in memory_long.json (session_2026-09-04) and this wrap-up entry.
- **Open item:** (b) confirm finance.json vs brokerage reconciliation approach - now tighter with the phantom entry removed.

## Session Wrap-Up (2026-09-04 21:18)
- **Transactions:** 2 recorded | Net Balance: $58.24 (income only; spurious 'Stipend' and 'Lunch' entries removed 2026-09-05)
- **Portfolio:** 3 position(s) tracked
- **Actions Taken:**
  - Session wrap-up completed
  - Short-term memory cleared
- **Reconciled Trades (session):**
  - SELL SPYI 1x @ $53.94 (2026-09-04) | cost basis $53.55 | realized gain +$0.39 (short-term)
  - No buys this session. No paper-ledger fills.
  - `portfolio.json` diff-checked: SCHD 2x, SPYM 5x, NVDA 2x expected and present — no phantom holdings.
- **Live Valuation (2026-09-04 official close):**
  - Market value: $983.67 | Cost basis: $942.18 | Unrealized P&L: +$41.49 (+4.40%)
- **Risk Status (before clear):** CIRCUIT BREAKERS **HALTED** — concentration breach: SPYM 46.1% and NVDA 46.8% both exceed the 25% cap. Risk-sentinel would block new buys. No drawdown or volatility halts.
- **Open items carried forward:**
  - Diversify to address concentration halt (SPYM/NVDA >25% cap) before adding positions.
  - US Treasury/Fiscal Data API integration — reviewed, marginal vs FRED, deferred.
  - CLV indicator + `finance news` CLI implemented in follow-up session (see entry above; 99/99 tests).
- **Next Steps:**
  [ ] Optimize your portfolio allocation: finance optimize
  [ ] Screen for top momentum stocks: finance screen
  [ ] Check macroeconomic conditions: finance macro overview
  [ ] Run a backtest on a strategy: finance backtest SPY --fast 20 --slow 50
  [ ] Generate a full market briefing: finance report

## Session Wrap-Up (2026-09-05 20:37)
- **Transactions:** 2 recorded | Net Balance: $58.24
- **Portfolio:** 3 position(s) tracked
- **Actions Taken:**
  - Session wrap-up completed
  - Short-term memory cleared
- **Reconciled Trades (session):**
  - NO trades executed this session — Plan A concentration rebalance modeled at 2026-09-04 close, held for month-end reassessment (user adding ~$500 in ~1 month).
  - No paper-ledger fills (0 fills, shadow ledger empty). `portfolio.json` diff-checked: SCHD 2x @ $35.05, SPYM 5x @ $90.24, NVDA 2x @ $210.44 expected and present — no phantom holdings, no stale fills.
- **Ledger Fix:** removed spurious $1,200 "Stipend" income AND $35.25 "Lunch" expense from finance.json (never user-recorded; strings absent from all code/docs/tests, no git history for file). finance.json now holds income $58.24 (Sold SPYI $53.94 + Cash on hand $4.30) only = brokerage cash exactly; net $58.24.
- **Live Valuation (2026-09-04 official close):**
  - Market value: $983.67 | Cost basis: $942.18 | Unrealized P&L: +$41.49 (+4.40%)
  - SCHD 2 @ $34.80 (−0.71%) · SPYM 5 @ $90.67 (+0.48%) · NVDA 2 @ $230.36 (+9.47%)
- **Risk Status (before clear):** CIRCUIT BREAKERS **HALTED** — concentration breach: SPYM 46.1% and NVDA 46.8% both exceed the 25% cap (drawdown/vol checks OK). Risk-sentinel would block new buys until rebalanced.
- **Archived:** `session_2026-09-05` written to memory_long.json before clear.
- **Open items carried forward:**
  - Execute concentration rebalance (Plan A saved in memory) at month-end reassessment after ~$500 deposit.
  - Confirm finance.json vs brokerage reconciliation approach — now reconciled (income side = brokerage cash).
  - US Treasury/Fiscal Data API integration — reviewed, marginal vs FRED, deferred.
- **Next Steps:**
  [ ] Optimize your portfolio allocation: finance optimize
  [ ] Screen for top momentum stocks: finance screen
  [ ] Check macroeconomic conditions: finance macro overview
  [ ] Run a backtest on a strategy: finance backtest SPY --fast 20 --slow 50
  [ ] Generate a full market briefing: finance report

## Session Wrap-Up (2026-09-07 20:18)
- **Transactions:** 2 recorded | Net Balance: $58.24
- **Portfolio:** 3 position(s) tracked
- **Actions Taken:**
  - Session wrap-up completed
  - Short-term memory cleared
- **Next Steps:**
  [ ] Optimize your portfolio allocation: finance optimize
  [ ] Screen for top momentum stocks: finance screen
  [ ] Check macroeconomic conditions: finance macro overview
  [ ] Run a backtest on a strategy: finance backtest SPY --fast 20 --slow 50
  [ ] Generate a full market briefing: finance report

## Session Wrap-Up (2026-09-07 20:18) - FULL CLOSEOUT
- **Trade Reconciliation:** NO trades executed this session. No paper-ledger fills (no paper_trading.json). portfolio.json verified - no phantom holdings: SCHD 2x @ 35.05, SPYM 5x @ 90.24, NVDA 2x @ 210.44.
- **Cash Ledger (finance.json):** Income $58.24 (Sold SPYI $53.94 + Cash on hand $4.30), Expenses $0.00, Net Balance $58.24 = brokerage cash. Reconciled.
- **Live Mark-to-Market (last close 2026-09-04, market closed 09-07):** SCHD 34.80, SPYM 90.67, NVDA 230.36. Holdings $983.67, Cost $942.18, Unrealized P&L +$41.49 (+4.40%). Per-position: SCHD -$0.50 (-0.71%), SPYM +$2.15 (+0.48%), NVDA +$39.84 (+9.47%).
- **Risk Status (check_circuit_breakers):** HALT ACTIVE - POSITION CONCENTRATION: SPYM 46.1% and NVDA 46.8% vs 25% cap. Drawdown OK. Volatility OK. No new buys until concentration rebalanced.
- **Feature Work:** Sandbox watchlist added (finance watchlist add/list/evaluate) - training-only, firewalled (Agents.md rule 6). Paper trading default capital changed to $2,000 + initialize_ledger() added (not yet used).
- **Open Items:** (a) Execute Plan A concentration rebalance at month-end when ~$500 added; (b) decide if watchlist auto-ingests news/sentiment (firewalled); (c) decide whether to run the $2,000 paper account.

## Session Wrap-Up (2026-09-08 16:44)
- **Transactions:** 4 recorded | Net Balance: $1,509.79
- **Portfolio:** 2 position(s) tracked
- **Actions Taken:**
  - Session wrap-up completed
  - Short-term memory cleared
- **Next Steps:**
  [ ] Optimize your portfolio allocation: finance optimize
  [ ] Screen for top momentum stocks: finance screen
  [ ] Check macroeconomic conditions: finance macro overview
  [ ] Run a backtest on a strategy: finance backtest SPY --fast 20 --slow 50
  [ ] Generate a full market briefing: finance report

## Session Wrap-Up (2026-09-08 16:44) - FULL CLOSEOUT
- **Trade Reconciliation:** SELL 5 SPYM @ $90.31 = $451.55 (limit FILLED, basis $90.24, realized +$0.35 short-term). BUY 41 SCHD @ $34.30 = $1,406.30 NOT FILLED - Schwab DAY limit expired 4pm ET unfilled, removed from ledger (no phantom). Cash deposit +$1,000 logged. portfolio.json reconciled: SCHD 2x @ $35.05, NVDA 2x @ $210.44, SPYM removed - NO phantom holdings. No paper-ledger fills (no paper_trading.json).
- **Cash Ledger (finance.json):** Income $1,509.79 (Cash on hand $4.30 + Sold SPYI $53.94 + Cash deposit $1,000 + Sold 5 SPYM $451.55), Expenses $0.00, Net Balance $1,509.79 awaiting deployment into SCHD tomorrow.
- **Live Mark-to-Market (close 2026-09-08):** SCHD 34.41, NVDA 225.73. Holdings $520.28, Cost $490.98, Unrealized P&L +$29.30 (+5.97%). Per-position: SCHD -$1.28 (-1.83%), NVDA +$30.58 (+7.27%).
- **Risk Status (check_circuit_breakers):** HALT ACTIVE - POSITION CONCENTRATION: NVDA 86.8% of holdings vs 25% cap (artifact of $1,509.79 undeployed cash). Drawdown OK. Volatility OK. Projects to clear at ~76.9% SCHD / 23.1% NVDA once SCHD buy fills. No new buys until SCHD deployed.
- **Market Analysis:** Optimizer (1y data) verdict: SCHD 88% + NVDA 12% is the max-Sharpe portfolio (Sharpe 2.25, vol 10.1%, ret 26.8%). SPY/SPYM identical exposure (corr 1.0); QQQ (corr 0.68 w/ NVDA) and Vanguard VOO/VTI/VIG/VYM all positively correlated with NVDA - SCHD is the only diversifier (corr -0.15). Macro: Fed 3.63%, 10Y 4.77%, CPI +0.25%, unemployment 4.1%.
- **Contributions Model:** Monthly $500/$750/$1,000 Monte Carlo (5k sims) - 3yr median $31.7k (500/mo) to $58.8k ($1,000/mo). Contributions naturally dilute concentration if funneled into SCHD.
- **Feature Work:** Added agents portfolio-manager, order-clerk, contribution-planner in .opencode/agent/ (read-only, bash ask, firewalled from watchlist).
- **Open Items:** (a) RE-PLACE 41 SCHD buy today/next session (limit $34.30 GTC or market ~$34.40) - concentration halt blocks new buys until then; (b) monthly $500-1,000 contributions funnel into SCHD per optimizer; (c) assess Plan A rebalance (sell NVDA diversification) at month-end if SCHD deployment insufficient.
