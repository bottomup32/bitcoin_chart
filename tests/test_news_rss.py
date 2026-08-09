"""RSS news parsing: markup stripping, timestamps, and malformed feeds."""

from datetime import datetime, timezone

from adapters.news_rss import clean_text, parse_feed, parse_pubdate

FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>NVDA News</title>
  <item>
    <title>Nvidia beats on earnings</title>
    <description>&lt;p&gt;Revenue   rose   sharply&lt;/p&gt;</description>
    <link>https://example.com/a</link>
    <pubDate>Wed, 05 Aug 2026 20:30:00 GMT</pubDate>
  </item>
  <item>
    <title>Analyst raises target</title>
    <description>Target lifted</description>
    <link>https://example.com/b</link>
    <pubDate>Tue, 04 Aug 2026 13:00:00 -0400</pubDate>
  </item>
</channel></rss>"""


def test_parse_feed_extracts_items_in_order():
    items = parse_feed(FEED, "NVDA")
    assert [i.title for i in items] == ["Nvidia beats on earnings", "Analyst raises target"]
    assert all(i.ticker == "NVDA" for i in items)


def test_summaries_are_stripped_of_markup_and_whitespace():
    assert parse_feed(FEED, "NVDA")[0].summary == "Revenue rose sharply"


def test_timestamps_are_normalised_to_utc():
    items = parse_feed(FEED, "NVDA")
    assert items[0].published_at == datetime(2026, 8, 5, 20, 30, tzinfo=timezone.utc)
    # -0400 becomes 17:00 UTC.
    assert items[1].published_at == datetime(2026, 8, 4, 17, 0, tzinfo=timezone.utc)


def test_an_item_without_a_usable_timestamp_is_dropped():
    """No timestamp means it cannot be filtered by as-of, so it is unusable."""
    feed = """<rss><channel><item><title>Undated</title></item></channel></rss>"""
    assert parse_feed(feed, "NVDA") == []


def test_an_item_without_a_title_is_dropped():
    feed = """<rss><channel><item>
        <pubDate>Wed, 05 Aug 2026 20:30:00 GMT</pubDate></item></channel></rss>"""
    assert parse_feed(feed, "NVDA") == []


def test_malformed_xml_yields_nothing_rather_than_raising():
    """News is optional — a broken feed must never fail the ingest run."""
    assert parse_feed("<rss><channel><item>", "NVDA") == []
    assert parse_feed("", "NVDA") == []
    assert parse_feed("404 Not Found", "NVDA") == []


def test_item_count_is_capped():
    items = "".join(
        f"<item><title>H{i}</title>"
        f"<pubDate>Wed, 05 Aug 2026 20:30:00 GMT</pubDate></item>"
        for i in range(50)
    )
    assert len(parse_feed(f"<rss><channel>{items}</channel></rss>", "NVDA", limit=4)) == 4


def test_clean_text_truncates_long_summaries():
    assert len(clean_text("x" * 500)) == 200
    assert clean_text(None) == ""
    assert clean_text("") == ""


def test_parse_pubdate_rejects_garbage():
    assert parse_pubdate("not a date") is None
    assert parse_pubdate(None) is None


def test_naive_timestamps_are_assumed_utc():
    parsed = parse_pubdate("Wed, 05 Aug 2026 20:30:00")
    assert parsed is not None and parsed.tzinfo is not None
