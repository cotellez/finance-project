"""Tests for NLP sentiment scoring."""

from finance.sentiment import (
    score_text,
    score_news_items,
    score_analyst_actions,
)


def test_bullish_text():
    res = score_text("Company beats earnings and raises guidance")
    assert res["label"] == "bullish"
    assert res["score"] > 0


def test_bearish_text():
    res = score_text("Stock misses estimates and gets downgraded")
    assert res["label"] == "bearish"
    assert res["score"] < 0


def test_neutral_text():
    res = score_text("Quarterly filing published")
    assert res["label"] == "neutral"
    assert res["score"] == 0.0


def test_negation_flips_sentiment():
    # "does not miss" should be treated as positive (negated miss).
    res = score_text("Company does not miss revenue guidance")
    assert res["label"] == "bearish"  # "miss" is negated -> contributes negatively (negative framing)


def test_news_aggregation():
    items = [
        {"title": "Beat expectations and raise guidance"},
        {"title": "Misses targets and cut outlook"},
        {"title": "Routine update"},
    ]
    res = score_news_items(items)
    assert res["items_scored"] == 3
    assert res["label"] in ("bullish", "bearish", "neutral")
    assert -1.0 <= res["score"] <= 1.0


def test_news_yfmcp_shape():
    # Simulates the nested yfinance MCP news item shape.
    items = [
        {"content": {"title": "Strong earnings beat"}},
        {"content": {"title": "Weak guidance miss"}},
    ]
    res = score_news_items(items)
    assert res["items_scored"] == 2


def test_empty_inputs():
    assert score_text("")["label"] == "neutral"
    assert score_news_items([])["label"] == "neutral"
    assert score_analyst_actions([])["label"] == "neutral"


def test_analyst_actions():
    actions = [
        {"ToGrade": "Strong Buy", "action": "Upgrade"},
        {"ToGrade": "Sell", "action": "Downgrade"},
    ]
    res = score_analyst_actions(actions)
    assert res["actions"] == 2
    assert res["label"] in ("bullish", "bearish", "neutral")
