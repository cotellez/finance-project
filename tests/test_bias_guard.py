"""Tests for bias guardrails (look-ahead and survivorship)."""

import pytest
import pandas as pd
from finance.bias_guard import (
    assert_no_lookahead,
    shift_signal_to_position,
    point_in_time_universe,
)


def test_shift_signal_prevents_lookahead():
    df = pd.DataFrame({"signal": [1, 1, 0, 0, 1]})
    shifted = shift_signal_to_position(df).tolist()
    # Position at t uses signal from t-1.
    assert shifted == [0.0, 1.0, 1.0, 0.0, 0.0]


def test_assert_no_lookahead_clean_signal_passes():
    # A clean (non-predictive) signal should not trip the detector.
    df = pd.DataFrame(
        {
            "signal": [0, 0, 1, 0, 1, 0, 1, 0],
            "adjusted_close": [100, 101, 102, 99, 103, 98, 104, 101],
        }
    )
    # No exception expected.
    assert_no_lookahead(df)


def test_assert_no_lookahead_missing_signal_raises():
    df = pd.DataFrame({"adjusted_close": [1.0, 2.0, 3.0]})
    with pytest.raises(ValueError, match="Signal column"):
        assert_no_lookahead(df)


def test_survivorship_bias_flag():
    res = point_in_time_universe(["AAPL", "MSFT", "GOOG"])
    assert res["survivorship_bias_risk"] == "HIGH"
    assert "survivorship" in res["warning"].lower()
