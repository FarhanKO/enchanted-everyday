"""Stage 1: pull ~20 trend items from several sources. One failing source never stops the run."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import feedparser
import httpx
from sqlalchemy.dialects.postgresql import insert
from tenacity import retry, stop_after_attempt, wait_exponential

from engine.config import Settings
from engine.db.models import TrendItem
from engine.stages.base import StageContext

log = logging.getLogger(__name__)

GOOGLE_TRENDS_RSS = "https://trends.google.com/trending/rss?geo={geo}"
YOUTUBE_SEARCH = "https://www.googleapis.com/youtube/v3/search"
USER_AGENT = "content-engine/0.1 (+https://github.com/)"
PER_SOURCE_LIMIT = 8
TOTAL_LIMIT = 24


@dataclass(frozen=True)
class Item:
    source: str
    title: str
    url: str
    summary: str | None = None


Source = Callable[[httpx.Client, Settings], list[Item]]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10), reraise=True)
def _get(client: httpx.Client, url: str, **params) -> httpx.Response:
    resp = client.get(url, params=params or None)
    resp.raise_for_status()
    return resp


def parse_feed(source: str, content: bytes | str, limit: int = PER_SOURCE_LIMIT) -> list[Item]:
    feed = feedparser.parse(content)
    items = []
    for entry in feed.entries[:limit]:
        title, link = entry.get("title"), entry.get("link")
        if title and link:
            summary = entry.get("summary") or entry.get("description")
            items.append(Item(source, title.strip(), link.strip(), summary))
    return items


def parse_google_trends(
    content: bytes | str, geo: str, limit: int = PER_SOURCE_LIMIT
) -> list[Item]:
    """Every item's <link> is the feed URL itself, so use its attached news article instead.

    That article is also a real source the script can cite.
    """
    items = []
    for entry in feedparser.parse(content).entries[:limit]:
        term = (entry.get("title") or "").strip()
        if not term:
            continue
        url = entry.get("ht_news_item_url") or (
            f"https://trends.google.com/trends/explore?{urlencode({'geo': geo, 'q': term})}"
        )
        traffic = entry.get("ht_approx_traffic")
        headline = entry.get("ht_news_item_title")
        summary = " | ".join(x for x in (f"searches: {traffic}" if traffic else "", headline) if x)
        items.append(Item("google_trends", term, url, summary or None))
    return items


def google_trends(client: httpx.Client, settings: Settings) -> list[Item]:
    resp = _get(client, GOOGLE_TRENDS_RSS.format(geo=settings.trends_geo))
    return parse_google_trends(resp.content, settings.trends_geo)


def niche_feeds(client: httpx.Client, settings: Settings) -> list[Item]:
    items: list[Item] = []
    for url in settings.rss_feeds:
        try:
            items += parse_feed(f"rss:{httpx.URL(url).host}", _get(client, url).content, limit=4)
        except Exception:
            log.warning("feed failed", extra={"feed": url}, exc_info=True)
    return items


def youtube_search(client: httpx.Client, settings: Settings) -> list[Item]:
    if not (settings.youtube_api_key and settings.youtube_query):
        return []
    since = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    resp = _get(
        client,
        YOUTUBE_SEARCH,
        part="snippet",
        q=settings.youtube_query,
        type="video",
        order="viewCount",
        publishedAfter=since,
        maxResults=PER_SOURCE_LIMIT,
        relevanceLanguage=settings.content_language,
        key=settings.youtube_api_key.get_secret_value(),
    )
    return [
        Item(
            "youtube",
            it["snippet"]["title"],
            f"https://www.youtube.com/watch?v={it['id']['videoId']}",
            it["snippet"].get("description"),
        )
        for it in resp.json().get("items", [])
        if it.get("id", {}).get("videoId")
    ]


SOURCES: dict[str, Source] = {
    "google_trends": google_trends,
    "niche_feeds": niche_feeds,
    "youtube": youtube_search,
}


def collect(client: httpx.Client, settings: Settings, sources: dict[str, Source] = SOURCES):
    items: list[Item] = []
    failed: list[str] = []
    for name, source in sources.items():
        try:
            got = source(client, settings)
            log.info("trend source ok", extra={"source": name, "items": len(got)})
            items += got
        except Exception:
            failed.append(name)
            log.warning("trend source failed", extra={"source": name}, exc_info=True)

    seen: set[str] = set()
    unique = [i for i in items if not (i.url in seen or seen.add(i.url))]
    return unique[:TOTAL_LIMIT], failed


def run(ctx: StageContext) -> dict:
    with httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as c:
        items, failed = collect(c, ctx.settings)
    if not items:
        raise RuntimeError(f"every trend source failed or was empty: {failed}")

    ctx.session.execute(
        insert(TrendItem)
        .values(
            [
                {
                    "run_id": ctx.run_id,
                    "source": i.source,
                    "title": i.title,
                    "url": i.url,
                    "summary": (i.summary or "")[:2000] or None,
                }
                for i in items
            ]
        )
        .on_conflict_do_nothing(index_elements=["run_id", "url"])
    )
    return {"items": len(items), "failed_sources": failed}
