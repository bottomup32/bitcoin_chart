-- 0006_knowledge_corpus.sql — 지식메모리: the investor-philosophy corpus
--
-- Activates the sources scaffolding that has been declared but unused since
-- 0001. A knowledge source is a sources row with type='research' (the CHECK
-- already allows it) and a user-set credibility_prior.
--
-- Chunks are short, opinionated DECISION RULES, not encyclopedic summaries.
-- Sonnet already knows Buffett, Graham, Munger, Marks and Lynch from
-- pretraining, so spending tokens re-explaining them buys nothing. What the
-- corpus actually contributes is (a) pinning which principles THIS user
-- endorses, (b) forcing them onto today's specific numbers, and (c) creating an
-- attribution channel so source_weights has something to learn from.
--
--   bad:  "Howard Marks emphasizes second-level thinking and cycle awareness."
--   good: "In a drawdown with elevated volatility, ask whether price fell more
--          than value. If so, reduce sizing rather than exiting."

create table knowledge_docs (
    id          bigint generated always as identity primary key,
    source_id   bigint not null references sources (id),
    title       text   not null,
    author      text,
    url         text,
    origin      text   not null check (origin in ('url', 'pasted', 'file')),
    -- Idempotent re-ingest, the same trick tax_lots.external_ref uses.
    content_sha text   not null unique,
    raw         text   not null,
    ingested_at timestamptz not null default now()
);

create table knowledge_chunks (
    id         bigint generated always as identity primary key,
    doc_id     bigint  not null references knowledge_docs (id) on delete cascade,
    source_id  bigint  not null references sources (id),   -- denormalized for retrieval
    seq        integer not null,
    -- A cost control expressed as a constraint: prompt bloat becomes a DB
    -- error rather than a slowly growing bill.
    body       text    not null check (length(body) <= 400),
    kind       text    not null check (kind in ('principle', 'heuristic', 'caution')),
    horizons   text[]  not null default '{}',  -- days|weeks|months|quarters; empty = any
    agents     text[]  not null default '{}',  -- daily_signal|allocation|risk|tax; empty = all
    tags       text[]  not null default '{}',  -- controlled vocabulary, see core/memory.py
    layer      text    not null default 'situational'
               check (layer in ('core', 'situational')),
    char_len   integer not null,
    -- Human review gate. A bad chunk is a permanent daily token cost AND a
    -- permanent bias in every future decision, so retrieval filters on this.
    approved   boolean not null default false,
    created_at timestamptz not null default now(),
    unique (doc_id, seq)
);

create index knowledge_chunks_tags_idx   on knowledge_chunks using gin (tags);
create index knowledge_chunks_agents_idx on knowledge_chunks using gin (agents);
create index knowledge_chunks_live_idx   on knowledge_chunks (layer) where approved;
