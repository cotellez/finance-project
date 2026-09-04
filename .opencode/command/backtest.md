---
description: Backtest a strategy on historical data with transaction costs and slippage, and assess bias/survivorship risk.
agent: build
---

Backtest the requested strategy (default: SMA crossover). Steps:

1. Fetch data with `finance.stock_data.fetch_daily_with_fallback`.
2. Run `finance.backtest.backtest_sma_crossover` with non-zero
   transaction_cost_pct and slippage_pct (state the values used).
3. Assess bias risk: call `finance.bias_guard.point_in_time_universe` on the
   candidate universe and report whether survivorship bias applies.
4. If a strategy signal is provided, run it through
   `finance.bias_guard.assert_no_lookahead` to guard against leakage.

Report: gross and NET strategy return, max drawdown, Sharpe, total turnover and
cost drag, plus a clear statement that these are upper-bound figures susceptible to
survivorship bias — and recommend validating via `finance.paper_trading`.
