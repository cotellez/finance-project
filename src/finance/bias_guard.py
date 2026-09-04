"""Bias guardrails for historical backtesting and screening.

Mitigates two of the most damaging quantitative biases:

1. Look-Ahead Bias - accidentally using future information in a signal.
   Strategy signals MUST only depend on data known up to and including the
   current bar's close. This module verifies that no indicator columns leak
   future values and provides helper utilities to enforce signal shifting.

2. Survivorship Bias - backtests that only include currently-listed equities
   historically overstate performance because delisted/bankrupt companies are
   excluded. This module surfaces the bias and encourages maintaining a
   point-in-time universe where survivorship-bias-free analysis is required.
"""

import pandas as pd

BIAS_GUARD_ENFORCED = True


def assert_no_lookahead(df: pd.DataFrame, signal_col: str = "signal", price_col: str = "adjusted_close") -> None:
    """Raise if a signal column appears to use same-bar close information.

    A valid tradeable signal must be computed from information available BEFORE
    the execution bar. The safest pattern is to shift the signal by one row so
    today's position only reflects yesterday's (or earlier) data. This raises
    ValueError when a raw (unshifted) signal equals the sign of the current
    bar's forward return, which strongly indicates look-ahead leakage.
    """
    if df.empty:
        return
    if signal_col not in df.columns:
        raise ValueError(f"Signal column '{signal_col}' not present in DataFrame.")
    if price_col not in df.columns:
        raise ValueError(f"Price column '{price_col}' not present in DataFrame.")

    signal = df[signal_col].fillna(0)
    prices = df[price_col]
    future_return = prices.shift(-1) / prices - 1.0

    # Compare the signal's intent (long = positive) to the NEXT bar's return.
    # A signal that materially predicts the VERY NEXT bar with near-perfect
    # alignment is a red flag for leakage (real alpha rarely looks this clean).
    effective = signal.clip(-1.0, 1.0)
    aligned = (effective != 0) & (future_return != 0)
    if aligned.sum() == 0:
        return

    same_direction = (effective[aligned] > 0) == (future_return[aligned] > 0)
    hit_rate = float(same_direction.mean())
    if hit_rate > 0.95:
        raise ValueError(
            f"Look-ahead bias detected: signal aligns with next-bar return {hit_rate:.0%} "
            "of the time. Ensure the signal only uses data available before execution "
            "(use .shift(1))."
        )


def shift_signal_to_position(df: pd.DataFrame, signal_col: str = "signal", fill: float = 0.0) -> pd.Series:
    """Return a position series that uses only prior-bar information.

    Shifts the signal by one row so the position at bar t reflects the signal
    computed at bar t-1 (no look-ahead into the current/next bar).
    """
    return df[signal_col].shift(1).fillna(fill)


def point_in_time_universe(current_universe: list) -> dict:
    """Flag candidates that may introduce survivorship bias into backtests.

    Args:
        current_universe: List of tickers from a CURRENT screener/snapshot.

    Returns:
        A dict describing the survivorship-bias risk and remediation guidance.
    """
    return {
        "universe_source": "current_snapshot",
        "survivorship_bias_risk": "HIGH" if current_universe else "UNKNOWN",
        "warning": (
            "Survivorship bias: this universe is drawn from currently-listed "
            "equities and omits delisted/bankrupt names. Historical backtests on "
            "this universe will overstate returns and understate drawdowns. For "
            "point-in-time accuracy, maintain a historically complete universe "
            "(e.g., CRSP-style) or treat these backtests as upper-bound estimates."
        ),
        "recommendation": (
            "For live decision-making, run paper trading (forward simulation) rather "
            "than relying solely on historical backtests to validate strategy robustness."
        ),
    }
