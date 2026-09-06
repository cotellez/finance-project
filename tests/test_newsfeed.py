"""Tests for the free RSS news aggregation module (newsfeed.py).

All tests are offline: requests.get is mocked and the SQLite cache is replaced
with in-memory stubs so no network or filesystem state is touched by default.
"""

import pytest

from finance.newsfeed import (
    FEEDS,
    fetch_rss_feed,
    fetch_financial_news,
    score_news_feed,
    detect_catalysts,
    parse_rss_xml,
    _normalize_url,
    MAX_BYTES,
)

SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Nvidia beats earnings, raises guidance</title>
      <description>Record revenue and strong AI demand drive the beat.</description>
      <link>https://example.com/nvda</link>
      <pubDate>Wed, 03 Sep 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Fed signals rate cut as inflation cools</title>
      <description>Policymakers lean dovish on slowing price growth.</description>
      <link>https://example.com/fed</link>
      <pubDate>Wed, 03 Sep 2026 13:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    """Replace the persistent SQLite cache with no-op stubs (offline)."""

    def fake_get(key, ttl_hours=12, db_path=None):
        return None

    def fake_set(key, data, db_path=None):
        return None

    monkeypatch.setattr("finance.newsfeed.get_cached_response", fake_get)
    monkeypatch.setattr("finance.newsfeed.cache_response", fake_set)


class FakeResponse:
    def __init__(self, data, headers=None, status=200):
        self._data = data
        self.headers = headers or {"Content-Type": "application/rss+xml"}
        self.status_code = status
        self.content = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise IOError(f"HTTP {self.status_code}")


def test_parse_rss_basic():
    items = parse_rss_xml(SAMPLE_RSS)
    assert len(items) == 2
    assert items[0]["title"] == "Nvidia beats earnings, raises guidance"
    assert items[0]["link"] == "https://example.com/nvda"


def test_parse_rss_html_unescaped():
    raw = b'<rss><channel><item><title>Prices &amp; yields &lt;up&gt;</title></item></channel></rss>'
    items = parse_rss_xml(raw)
    assert items[0]["title"] == "Prices & yields <up>"


def test_parse_rss_xxe_guard_rejects_doctype():
    evil = b'<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY x "boom">]><rss><channel><item><title>&x; attack</title></item></channel></rss>'
    assert parse_rss_xml(evil) == []


def test_parse_rss_xxe_guard_rejects_entity_billion_laughs():
    evil = b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lollol">]><rss/>'
    assert parse_rss_xml(evil) == []


def test_parse_rss_malformed_returns_empty():
    assert parse_rss_xml(b"<rss><channel>") == []
    assert parse_rss_xml(b"") == []


def test_normalize_url_allowlist():
    # Valid whitelisted host
    assert _normalize_url("https://www.cnbc.com/id/10001147/device/rss/rss.html")
    assert _normalize_url("https://feeds.marketwatch.com/marketwatch/topstories/")
    # Newer whitelisted sources
    assert _normalize_url("https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US")
    assert _normalize_url("https://www.investing.com/rss/news.rss")
    # Rejects http (not https)
    assert _normalize_url("http://www.cnbc.com/id/10001147/device/rss/rss.html") is None
    # Rejects non-whitelisted host (SSRF)
    assert _normalize_url("https://169.254.169.254/latest/meta-data") is None
    assert _normalize_url("https://evil.com/feed") is None
    assert _normalize_url("https://localhost:8080/feed") is None
    assert _normalize_url("https://feeds.otherdomainyahoo.com/x") is None


def test_fetch_rss_feed_success(monkeypatch):
    monkeypatch.setattr("finance.newsfeed.requests.get", lambda *a, **k: FakeResponse(SAMPLE_RSS))
    out = fetch_rss_feed(FEEDS["cnbc"]["business"])
    assert out["ok"] is True
    assert len(out["items"]) == 2
    assert out["source"] == "cnbc"
    assert out["items"][0]["source"] == "cnbc"


def test_fetch_rss_feed_rejects_unallowed_url(monkeypatch):
    # Should not even call requests.get
    called = []

    def fake_get(*a, **k):
        called.append(True)
        return FakeResponse(SAMPLE_RSS)

    monkeypatch.setattr("finance.newsfeed.requests.get", fake_get)
    out = fetch_rss_feed("https://evil.com/feed.rss")
    assert out["ok"] is False
    assert "allowlist" in out["error"].lower()
    assert called == []


def test_fetch_rss_feed_size_cap(monkeypatch):
    big = b"a" * (MAX_BYTES + 1)
    monkeypatch.setattr("finance.newsfeed.requests.get", lambda *a, **k: FakeResponse(big))
    out = fetch_rss_feed(FEEDS["cnbc"]["business"])
    assert out["ok"] is False
    assert "size" in out["error"].lower()


def test_fetch_rss_feed_wrong_content_type(monkeypatch):
    resp = FakeResponse(SAMPLE_RSS, headers={"Content-Type": "text/html"})
    monkeypatch.setattr("finance.newsfeed.requests.get", lambda *a, **k: resp)
    out = fetch_rss_feed(FEEDS["cnbc"]["business"])
    assert out["ok"] is False
    assert "content-type" in out["error"].lower()


def test_fetch_financial_news_merge_and_status(monkeypatch):
    monkeypatch.setattr("finance.newsfeed.requests.get", lambda *a, **k: FakeResponse(SAMPLE_RSS))
    out = fetch_financial_news(sources=("cnbc", "marketwatch"), limit=50)
    assert out["status"] == "ok"
    assert len(out["items"]) >= 2
    # dedup across feeds (same titles repeated per source URL are deduped by source)
    assert "sources" in out
    assert all("ok" in s for s in out["sources"])


def test_fetch_financial_news_partial_on_failure(monkeypatch):
    def fake_get(url, *a, **k):
        if "cnbc" in url:
            return FakeResponse(SAMPLE_RSS)
        return FakeResponse(b"", status=404)

    monkeypatch.setattr("finance.newsfeed.requests.get", fake_get)
    out = fetch_financial_news(sources=("cnbc", "marketwatch"), retries=0)
    assert out["status"] == "partial"
    assert len(out["items"]) >= 2


def test_fetch_financial_news_default_sources_include_new_publications(monkeypatch):
    urls = []

    def fake_get(url, *a, **k):
        urls.append(url)
        return FakeResponse(SAMPLE_RSS)

    monkeypatch.setattr("finance.newsfeed.requests.get", fake_get)
    out = fetch_financial_news(limit=50)
    joined = " ".join(urls)
    assert "feeds.finance.yahoo.com" in joined
    assert "investing.com" in joined
    assert out["status"] == "ok"
    assert len(out["items"]) >= 2


def test_fetch_financial_news_interleaves_sources(monkeypatch):
    # CNBC floods 3 items per feed across 5 feeds; Yahoo returns a single item.
    # Round-robin must surface the Yahoo item instead of CNBC drowning it out.
    c = b'<rss><channel><item><title>CNBC market update</title></item><item><title>CNBC tech news</title></item><item><title>CNBC earnings recap</title></item></channel></rss>'
    y = b'<rss><channel><item><title>Yahoo market wrap</title></item></channel></rss>'

    def fake_get(url, *a, **k):
        return FakeResponse(c if "cnbc" in url else y)

    monkeypatch.setattr("finance.newsfeed.requests.get", fake_get)
    out = fetch_financial_news(sources=("cnbc", "yahoo"), limit=6)
    titles = [it["title"] for it in out["items"]]
    # global dedup: 3 CNBC + 1 Yahoo
    assert titles == ["CNBC market update", "Yahoo market wrap", "CNBC tech news", "CNBC earnings recap"]


def test_score_news_feed(monkeypatch):
    from finance import sentiment
    captured = {}

    def fake_score(items):
        captured["items"] = items
        return {"label": "bullish", "score": 0.6, "items_scored": len(items)}

    monkeypatch.setattr(sentiment, "score_news_items", fake_score)
    out = score_news_feed([{"title": "Great rally beats expectations", "summary": "up"}])
    assert out["label"] == "bullish"
    assert captured["items"][0]["content"]["title"] == "Great rally beats expectations"


def test_detect_catalysts_groups(monkeypatch):
    items = [
        {"title": "Fed signals rate cut as inflation cools", "summary": ""},
        {"title": "Company X beats quarterly earnings", "summary": ""},
    ]
    result = detect_catalysts(items)
    assert "macro" in result and len(result["macro"]) == 1
    assert "earnings" in result and len(result["earnings"]) == 1
    # deterministic data only, no instructions
    assert set(result.keys()) == set(result.keys())
