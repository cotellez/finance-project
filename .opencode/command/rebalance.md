---
description: Rebalance the portfolio toward target weights using optimization, then validate with hard risk circuit breakers.
agent: build
---

Rebalance the tracked portfolio. Steps:

1. Load positions and current prices; compute current weights and metrics with
   `finance.portfolio.calculate_portfolio_metrics`.
2. Fetch historical data for each held ticker and run portfolio optimization:
   - Use `finance.advanced_optimization.hierarchical_risk_parity` (robust for many assets),
     or `finance.optimization.optimize_portfolio` for a stable small set.
3. Compute the target weight per ticker and the resulting rebalance trades.
4. Run `finance.risk_guardrails.check_circuit_breakers` on the rebalanced portfolio.

Report: current vs target weights, proposed trades, expected return/vol/Sharpe,
and whether the risk-sentinel halts the rebalance. Do NOT execute live trades; propose
them. If a shadow ledger exists, apply the trades via `finance.paper_trading.paper_buy`
/ `paper_sell` as a paper run.
