"""Per-ticker news headlines from free RSS feeds.

The system had no news at all: only prices were ingested, and daily_signal was
explicitly told to "base every rationale only on the numbers provided". This
fills that gap for the cheapest thing that is still decision-relevant —
headlines and one-line summaries, not article bodies.

Why RSS rather than a web-search tool: search results cannot be stored and
replayed, which would break the property the whole codebase is built on (an old
session can be re-run and produce the same advice) and would make it impossible
to audit what an agent actually saw. RSS items carry a published_at, so they
filter with the same as_of rule as every other memory source, and the raw
payload lands in daily_ingest for backfill and re-scoring.

No new dependency: feeds are small XML documents and the standard library's
ElementTree reads them. Parsing is defensive because feed shapes vary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from xml.etree import ElementTree

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36"
)

# Tried in order until one returns parseable items. Both are free, keyless and
# quota-free. More than one because the Yahoo endpoint has been deprecated and
# revived repeatedly over the years, and a silent switch to zero headlines would
# be invisible in the pipeline — prices would still flow and nobody would notice
# the agents had stopped seeing news.
FEED_TEMPLATES = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US",
    "https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en",
)

SOURCE_NAME = "rss"
TIMEOUT = 20
MAX_ITEMS_PER_TICKER = 8
MAX_SUMMARY_CHARS = 200

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class NewsItem:
    ticker: str
    title: str
    summary: str
    url: str
    published_at: datetime


def clean_text(raw: str | None, limit: int = MAX_SUMMARY_CHARS) -> str:
    """Strip markup and collapse whitespace; feed summaries are HTML fragments."""
    if not raw:
        return ""
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", raw)).strip()
    return text[:limit].rstrip()


def parse_pubdate(raw: str | None) -> datetime | None:
    """RFC 822 dates, as RSS specifies. Returns an aware UTC datetime."""
    if not raw:
        return None
    from email.utils import parsedate_to_datetime

    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_feed(xml: str, ticker: str, limit: int = MAX_ITEMS_PER_TICKER) -> list[NewsItem]:
    """Parse an RSS document into items. Malformed input yields [], never raises."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return []

    items: list[NewsItem] = []
    for node in root.iter("item"):
        title = clean_text(node.findtext("title"), limit=300)
        published = parse_pubdate(node.findtext("pubDate"))
        if not title or published is None:
            # Without a timestamp an item cannot be filtered by as-of, so it is
            # unusable here regardless of how good the headline is.
            continue
        items.append(NewsItem(
            ticker=ticker,
            title=title,
            summary=clean_text(node.findtext("description")),
            url=(node.findtext("link") or "").strip(),
            published_at=published,
        ))
        if len(items) >= limit:
            break
    return items


def fetch_news(tickers: list[str], session: date) -> tuple[list[NewsItem], list[str]]:
    """Fetch headlines for each ticker. Returns (items, failed_tickers).

    Items published after the session's end are dropped: run_ingest may run
    hours after the close, and letting tomorrow's headline into today's advice
    is the same look-ahead the rest of the system is built to prevent.
    """
    import requests

    items: list[NewsItem] = []
    failed: list[str] = []
    cutoff = datetime.combine(session, datetime.max.time(), tzinfo=timezone.utc)
    for ticker in tickers:
        fetched: list[NewsItem] = []
        for template in FEED_TEMPLATES:
            try:
                response = requests.get(
                    template.format(ticker=ticker),
                    timeout=TIMEOUT,
                    headers={"User-Agent": USER_AGENT},
                )
                response.raise_for_status()
            except Exception:  # noqa: BLE001 — news is optional; never fail the run
                continue
            fetched = parse_feed(response.text, ticker)
            if fetched:
                break
        if not fetched:
            failed.append(ticker)
            continue
        items.extend(i for i in fetched if i.published_at <= cutoff)
    return items, failed
