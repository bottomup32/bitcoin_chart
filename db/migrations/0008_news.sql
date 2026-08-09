-- 0008_news.sql — per-ticker headlines
--
-- News is a different data class from the philosophy corpus: perishable rather
-- than durable, and a recurring daily cost rather than a one-time one. It gets
-- its own table so its retention and its budget can be reasoned about apart
-- from knowledge_chunks.
--
-- published_at is what makes news replay-safe: it filters with the same as-of
-- rule as every other memory source, which is precisely what a web-search tool
-- could not offer.

create table news_items (
    id           bigint generated always as identity primary key,
    ticker       text        not null,
    title        text        not null,
    summary      text        not null default '',
    url          text,
    published_at timestamptz not null,
    source       text        not null default 'rss',
    ingested_at  timestamptz not null default now(),
    -- Feeds repeat the same story across polls; this makes ingest idempotent.
    unique (ticker, source, title, published_at)
);

create index news_items_lookup_idx on news_items (ticker, published_at desc);
