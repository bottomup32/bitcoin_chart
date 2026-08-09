-- 0005_agent_lessons.sql — long-term memory (durable lessons from outcomes)
--
-- Append-only. Supersede semantics come free from as_of_trade_date ordering:
-- retrieval at date D takes the newest row per (agent, ticker) with
-- as_of_trade_date <= D. There is deliberately NO superseded_at column — any
-- column recording "when we learned this was stale" is a future fact relative
-- to older run dates, so filtering on it would reintroduce the look-ahead this
-- whole design exists to prevent.
--
-- stats holds the code-computed inputs so a lesson is auditable after the fact;
-- body is the short prose the agent actually reads (a template writes it — see
-- core/memory.py:render_lesson — the LLM is not involved at this tier).

create table agent_lessons (
    id               bigint generated always as identity primary key,
    agent            text    not null,
    ticker           text,                       -- null = agent-level lesson
    as_of_trade_date date    not null,           -- knowable-at date; the retrieval filter
    n                integer not null,
    n_eff            numeric not null,
    tier             text    not null check (tier in ('provisional', 'established')),
    stats            jsonb   not null,
    body             text    not null check (length(body) <= 240),
    generator        text    not null default 'template'
                     check (generator in ('template', 'llm')),
    created_at       timestamptz not null default now(),
    unique (agent, ticker, as_of_trade_date)
);

create index agent_lessons_lookup_idx
    on agent_lessons (agent, ticker, as_of_trade_date desc);
