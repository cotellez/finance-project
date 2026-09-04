"""Tests for deterministic fundamental valuation metrics.

All offline/pure-function tests (no external API calls).
"""

import pytest
from finance.valuation import (
    price_to_earnings,
    forward_pe,
    earnings_yield,
    peg_ratio,
    valuation_score,
)


def test_pe_basic():
    assert price_to_earnings(100.0, 2.5) == pytest.approx(40.0)


def test_pe_loss_maker_returns_none():
    # PSQL-like: loss-making, EPS negative => no meaningful P/E.
    assert price_to_earnings(9.75, -0.41) is None


def test_pe_zero_eps_returns_none():
    assert price_to_earnings(50.0, 0.0) is None


def test_pe_missing_inputs_returns_none():
    assert price_to_earnings(None, 2.5) is None
    assert price_to_earnings(50.0, None) is None


def test_pe_zero_price_returns_none():
    assert price_to_earnings(0.0, 2.5) is None


def test_forward_pe_basic():
    assert forward_pe(100.0, 5.0) == pytest.approx(20.0)


def test_forward_pe_loss_maker_none():
    assert forward_pe(100.0, -3.0) is None


def test_earnings_yield():
    # VSXY-like: price 73.64, EPS 2.51 => yield ~3.4%.
    y = earnings_yield(73.64, 2.51)
    assert y is not None
    assert y == pytest.approx(2.51 / 73.64)
    assert y < 0.05


def test_earnings_yield_loss_maker_none():
    assert earnings_yield(9.75, -0.41) is None


def test_peg_ratio_basic():
    assert peg_ratio(20.0, 10.0) == pytest.approx(2.0)


def test_peg_ratio_negative_growth_none():
    assert peg_ratio(20.0, -5.0) is None


def test_peg_ratio_zero_growth_none():
    assert peg_ratio(20.0, 0.0) is None


def test_valuation_score_profitable():
    # VSXY-like: cheap on forward basis + growth.
    out = valuation_score(73.64, 2.51, 5.62484, earnings_growth_pct=15.0)
    assert out["loss_maker"] is False
    assert out["trailing_pe"] == pytest.approx(73.64 / 2.51)
    assert out["forward_pe"] is not None
    assert out["score"] is not None
    assert 0 <= out["score"] <= 100


def test_valuation_score_loss_maker():
    # PSQL-like: EPS negative => no score, flagged.
    out = valuation_score(9.75, -0.41, None)
    assert out["loss_maker"] is True
    assert out["score"] is None
    assert out["trailing_pe"] is None


def test_valuation_score_expensive_band():
    out = valuation_score(100.0, 1.0, 1.0)
    # P/E of 100 => expensive band (score 25).
    assert out["score"] == 25
    assert "expensive" in out["valuation_band"]


def test_valuation_score_peg_discount():
    out = valuation_score(100.0, 10.0, 10.0, earnings_growth_pct=20.0)
    # PEG 0.5 <1 => should boost score above the P/E-only base (60 for <=20).
    assert out["score"] >= 60


def test_valuation_score_low_pe_cheap():
    out = valuation_score(100.0, 20.0, 20.0)
    assert out["score"] == 90
    assert "cheap" in out["valuation_band"]
