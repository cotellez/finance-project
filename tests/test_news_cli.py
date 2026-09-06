"""Tests for the `finance news` CLI subcommand (mocked, offline)."""

from argparse import Namespace

from finance.cli import handle_news_fetch

FAKE_ITEMS = [
    {"title": "Nvidia beats earnings, raises guidance", "summary": "Record revenue.", "source": "cnbc", "link": "https://www.cnbc.com/x"},
    {"title": "Fed signals rate cut as inflation cools", "summary": "Policymakers lean dovish.", "source": "marketwatch", "link": "https://feeds.marketwatch.com/y"},
]

FAKE_FEED = {
    "items": FAKE_ITEMS,
    "sources": [
        {"source": "cnbc", "url": "https://www.cnbc.com/1", "ok": True, "error": None, "item_count": 1},
        {"source": "marketwatch", "url": "https://feeds.marketwatch.com/1", "ok": True, "error": None, "item_count": 1},
    ],
    "status": "ok",
}

FAKE_SCORE = {"label": "bullish", "score": 0.6, "items_scored": 2}

FAKE_CATALYSTS = {
    "earnings": [FAKE_ITEMS[0]],
    "macro": [FAKE_ITEMS[1]],
    "m_a": [],
    "regulation": [],
    "downgrade": [],
}


def _args(**overrides):
    base = {"limit": 20, "source": None, "no_sentiment": False, "no_catalysts": False, "links": False}
    base.update(overrides)
    return Namespace(**base)


def test_news_fetch_display_headlines(monkeypatch, capsys):
    monkeypatch.setattr("finance.newsfeed.fetch_financial_news", lambda **k: FAKE_FEED)
    monkeypatch.setattr("finance.newsfeed.score_news_feed", lambda items: FAKE_SCORE)
    monkeypatch.setattr("finance.newsfeed.detect_catalysts", lambda items: FAKE_CATALYSTS)

    rc = handle_news_fetch(_args())
    out = capsys.readouterr().out

    assert rc == 0
    assert "Status: OK" in out
    assert "Aggregate Sentiment: +0.600 (bullish)" in out
    assert "Catalysts Detected:" in out
    assert "EARNINGS (1): Nvidia beats earnings" in out
    assert "Nvidia beats earnings" in out
    assert "Fed signals rate cut" in out
    assert "https://www.cnbc.com/x" not in out  # links off by default


def test_news_fetch_links_and_disables(monkeypatch, capsys):
    monkeypatch.setattr("finance.newsfeed.fetch_financial_news", lambda **k: FAKE_FEED)
    monkeypatch.setattr("finance.newsfeed.score_news_feed", lambda items: FAKE_SCORE)
    monkeypatch.setattr("finance.newsfeed.detect_catalysts", lambda items: FAKE_CATALYSTS)

    handle_news_fetch(_args(no_sentiment=True, no_catalysts=True, links=True, limit=1))
    out = capsys.readouterr().out

    assert "Aggregate Sentiment" not in out
    assert "Catalysts Detected:" not in out
    assert "https://www.cnbc.com/x" in out


def test_news_fetch_empty_feed_lists_failures(monkeypatch, capsys):
    feed = {
        "items": [],
        "sources": [
            {"source": "cnbc", "url": "https://www.cnbc.com/1", "ok": False, "error": "timeout", "item_count": 0},
            {"source": "marketwatch", "url": "https://feeds.marketwatch.com/1", "ok": False, "error": "HTTP 404", "item_count": 0},
        ],
        "status": "failed",
    }
    monkeypatch.setattr("finance.newsfeed.fetch_financial_news", lambda **k: feed)
    monkeypatch.setattr("finance.newsfeed.score_news_feed", lambda items: {"label": "neutral", "score": 0.0, "items_scored": 0})
    monkeypatch.setattr("finance.newsfeed.detect_catalysts", lambda items: {})

    rc = handle_news_fetch(_args())
    out = capsys.readouterr().out

    assert rc == 0
    assert "FAILED cnbc" in out
    assert "HTTP 404" in out


def test_news_fetch_error_handling(monkeypatch, capsys):
    def boom(**k):
        raise RuntimeError("network down")

    monkeypatch.setattr("finance.newsfeed.fetch_financial_news", boom)

    rc = handle_news_fetch(_args())
    out = capsys.readouterr().err

    assert rc == 1
    assert "network down" in out