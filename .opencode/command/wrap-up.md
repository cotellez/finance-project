---
description: End-of-session wrap-up. Reconcile every trade, mark the portfolio to market, run hard risk checks, archive context to long-term memory, and log the session to progress.md. Usage: /wrap-up [trades + notes...]
agent: build
---

Close out the current session. Trade reconciliation comes FIRST — a sale never
recorded stays a phantom holding (this is how a real disposition was nearly
carried forward as if still owned).

1. RECONCILE TRADES (do this first):
   - Enumerate every buy/sell/position change this session. Sources: $ARGUMENTS
     (declare trades here), short-term memory, paper-ledger fills
     (`finance.paper_trading.load_ledger`), and any live `portfolio` commands run.
   - Ask the user to confirm any trade that isn't explicitly stated — do NOT guess.
   - Diff expected positions: (current `portfolio.json`) + session buys − session
     sells. Flag ANY position in `portfolio.json` that should no longer exist, or
     any fill that isn't reflected (e.g., a sold share still listed = phantom
     holding).
   - Record each trade (symbol, shares, fill $, date, realized P&L if a sell) into
     a session trade log, and reconcile `portfolio.json` / the paper ledger if
     they're stale. The CLI has no `sell` action, so this capture is manual.

2. Recap the session from short-term memory (`finance.memory.get_short_term_memory`)
   and $ARGUMENTS: what was analyzed, decided, bought, or sold.

3. Mark the portfolio to market: live prices via `finance.stock_data.fetch_daily` →
   `finance.portfolio.calculate_portfolio_metrics` for current value and unrealized P&L.

4. Books and base log via `finance.cli.handle_wrap_up` (prints balance, cost-basis
   portfolio recap, "What's Next" roadmap, appends a Session Wrap-Up entry to
   progress.md, and clears short-term memory at the end).

5. Risk status BEFORE the clear: `finance.risk_guardrails.check_circuit_breakers`
   on the live metrics; report any halts (concentration/vol/drawdown) into the log.

6. Archive context (BEFORE the clear lands): `finance.memory.remember(
   "session_<YYYY-MM-DD>", ...)` covering the trade log, decisions, market reads,
   and open questions. Then let short-term memory be cleared.

7. Extend the progress.md entry with the live valuation, reconciled trades, and
   risk status so the log is complete.

Report back: trades reconciled (buys/sells/realized P&L), net balance, holdings
market value, unrealized P&L, risk-halt status, and open items carried into the
next session.