"""Deterministic fundamental valuation metrics.

Pure functions computing valuation ratios (trailing/forward P/E, PEG, earnings
yield) and a composite valuation score from numeric inputs. They:
  - degrade gracefully on loss-making / zero-earnings inputs (return None rather
    than raising so agents and screens can detect "no meaningful P/E"),
  - are deterministic and unit-testable offline,
  - are meant to be called by subagents (quant-analyst, alpha-hunter) which
    interpret the results; the raw arithmetic lives here so it is auditable and
    consistent across every execution path.
"""

from __future__ import annotations

from typing import Dict, Optional


def price_to_earnings(price: Optional[float], eps: Optional[float]) -> Optional[float]:
    """Trailing P/E ratio.

    Returns None when price or EPS is missing, non-positive price, or EPS is
    zero/negative (loss-making companies have no meaningful P/E).
    """
    if price is None or eps is None or price <= 0 or eps <= 0:
        return None
    return price / eps


def forward_pe(price: Optional[float], forward_eps: Optional[float]) -> Optional[float]:
    """Forward P/E based on estimated next-year EPS."""
    if price is None or forward_eps is None or price <= 0 or forward_eps <= 0:
        return None
    return price / forward_eps


def earnings_yield(price: Optional[float], eps: Optional[float]) -> Optional[float]:
    """Earnings yield = EPS / price (the inverse of P/E).

    Only defined for positive EPS; loss-makers return None.
    """
    if price is None or eps is None or price <= 0 or eps <= 0:
        return None
    return eps / price


def peg_ratio(
    forward_pe: Optional[float], earnings_growth_pct: Optional[float]
) -> Optional[float]:
    """PEG ratio = forward P/E / expected earnings growth (%)."""
    if forward_pe is None or earnings_growth_pct is None:
        return None
    if earnings_growth_pct <= 0:
        return None
    return forward_pe / earnings_growth_pct


def valuation_score(
    price: Optional[float],
    eps: Optional[float],
    forward_eps: Optional[float],
    earnings_growth_pct: Optional[float] = None,
) -> Dict:
    """Composite valuation summary with a simple 0-100 attractiveness score.

    Interpretation:
      - Lower P/E and lower PEG (if growth supplied) are treated as cheaper.
      - A score of 100 = very cheap, 0 = extremely expensive.
      - When P/E is undefined (loss-maker), score is None and a flag is set so
        callers know the assessment is not meaningful.
    """
    trailing = price_to_earnings(price, eps)
    fwd = forward_pe(price, forward_eps)
    e_yield = earnings_yield(price, eps)
    peg = peg_ratio(fwd, earnings_growth_pct) if earnings_growth_pct else None

    result: Dict = {
        "price": price,
        "trailing_pe": trailing,
        "forward_pe": fwd,
        "earnings_yield": e_yield,
        "peg_ratio": peg,
        "score": None,
        "loss_maker": trailing is None,
    }

    anchor = fwd or trailing
    if anchor is None:
        result["note"] = "No meaningful P/E (missing, zero, or negative earnings)."
        return result

    # Simple scoring bands on the anchor P/E.
    if anchor <= 10:
        score = 90
        band = "very cheap"
    elif anchor <= 15:
        score = 75
        band = "cheap"
    elif anchor <= 20:
        score = 60
        band = "fair"
    elif anchor <= 30:
        score = 45
        band = "premium"
    else:
        score = 25
        band = "expensive"

    # Reward moderate growth that lowers PEG.
    if peg is not None:
        if peg < 1.0:
            score = min(score + 10, 100)
            band = f"{band}, attractive growth-adjusted (PEG<1)"
        elif peg > 2.0:
            score = max(score - 5, 0)
            band = f"{band}, expensive on growth (PEG>2)"

    result["score"] = score
    result["valuation_band"] = band
    result["note"] = "Lower is cheaper."
    return result
