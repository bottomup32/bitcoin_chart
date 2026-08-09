-- 0003_llm_calls.sql — per-call token accounting (memory plan, 증분 0)
--
-- Counts only. No prompt or response content is stored: the repo is public and
-- the prompts contain holdings-derived text, so this table is deliberately
-- content-free (PLAN.md §6). Per-block character counts are exact and free to
-- measure at assembly time; response usage is ground truth for the total, and
-- llm_cost_daily attributes tokens across memory blocks proportionally.

create table llm_calls (
    id                          bigint generated always as identity primary key,
    run_id                      bigint references runs (id),
    purpose                     text    not null,  -- agent name | 'narrative' | 'reflect' | 'knowledge_ingest'
    model_id                    text    not null,
    prompt_version              text,
    input_tokens                integer not null default 0,
    output_tokens               integer not null default 0,
    cache_creation_input_tokens integer not null default 0,
    cache_read_input_tokens     integer not null default 0,
    -- code-measured serialized sizes (characters), for proportional attribution
    chars_total                 integer not null default 0,
    chars_knowledge             integer not null default 0,
    chars_short_term            integer not null default 0,
    chars_long_term             integer not null default 0,
    ok                          boolean not null default true,
    created_at                  timestamptz not null default now()
);

create index llm_calls_run_idx on llm_calls (run_id);
create index llm_calls_created_idx on llm_calls (created_at desc);

create view llm_cost_daily as
select coalesce(r.run_date, c.created_at::date)                        as run_date,
       count(*)                                                        as calls,
       count(*) filter (where not c.ok)                                as failed_calls,
       sum(c.input_tokens)                                             as input_tokens,
       sum(c.output_tokens)                                            as output_tokens,
       sum(c.cache_creation_input_tokens)                              as cache_creation_tokens,
       sum(c.cache_read_input_tokens)                                  as cache_read_tokens,
       sum(c.input_tokens * c.chars_knowledge  / nullif(c.chars_total, 0)) as est_knowledge_tokens,
       sum(c.input_tokens * c.chars_short_term / nullif(c.chars_total, 0)) as est_short_term_tokens,
       sum(c.input_tokens * c.chars_long_term  / nullif(c.chars_total, 0)) as est_long_term_tokens
from llm_calls c
left join runs r on r.id = c.run_id
group by 1;
