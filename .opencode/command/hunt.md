---
description: Run the alpha-hunter subagent to scan for high-probability long opportunities and validate them with risk checks. Usage: /hunt [universe]
agent: build
---

Run the alpha-hunter workflow to discover high-probability long opportunities

for the requested universe (default: US large/mid caps). Use the yfinance MCP
tools to scan gappers and momentum names, evaluate catalysts via news and
analyst actions, score the candidates, and flag liquidity/slippage risks.

Then, for the top candidate(s), have the quant-analyst compute indicators and
confirm the risk-sentinel's circuit-breaker check passes before presenting the
watchlist. Do NOT execute trades.
