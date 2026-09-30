import httpx

from engine.stages import trend
from tests.conftest import FIXTURES

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>First post</title><link>https://blog.example.com/1</link><description>one</description></item>
<item><title>Second post</title><link>https://blog.example.com/2</link></item>
<item><title></title><link>https://blog.example.com/3</link></item>
</channel></rss>"""


def test_google_trends_uses_news_article_urls():
    items = trend.parse_google_trends((FIXTURES / "google_trends.xml").read_bytes(), "US")
    assert items, "fixture should parse"
    urls = [i.url for i in items]
    assert len(set(urls)) == len(urls), "each trend needs its own URL"
    assert not any(u.startswith("https://trends.google.com/trending/rss") for u in urls)


def test_parse_feed_skips_untitled_items():
    items = trend.parse_feed("rss", RSS)
    assert [i.title for i in items] == ["First post", "Second post"]


def test_one_failing_source_does_not_stop_the_scan(settings):
    def ok(client, s):
        return [trend.Item("ok", "A", "https://a"), trend.Item("ok", "dup", "https://a")]

    def broken(client, s):
        raise httpx.ConnectError("down")

    with httpx.Client() as c:
        items, failed = trend.collect(c, settings, {"ok": ok, "broken": broken})
    assert failed == ["broken"]
    assert [i.url for i in items] == ["https://a"]  # deduped by URL


def test_niche_feeds_over_mock_transport(settings):
    settings.niche_rss_feeds = "https://blog.example.com/feed, https://down.example.com/feed"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "down.example.com":
            return httpx.Response(503)
        return httpx.Response(200, content=RSS)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        items = trend.niche_feeds(c, settings)
    assert {i.source for i in items} == {"rss:blog.example.com"}


def test_youtube_skipped_without_key(settings):
    with httpx.Client() as c:
        assert trend.youtube_search(c, settings) == []
