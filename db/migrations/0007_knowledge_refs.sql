-- 0007_knowledge_refs.sql — attribution: which principles were shown, which used
--
-- Logging EXPOSURE (shown), not just citation, is what makes learning possible
-- at all. Without the denominator you cannot tell "this source was shown and
-- did not help" from "this source was never shown" — and the exposure counts
-- double as the exploration counter that keeps retrieval from collapsing onto
-- whatever ranked well early.

create table opinion_knowledge_refs (
    opinion_id bigint  not null references agent_opinions (id) on delete cascade,
    chunk_id   bigint  not null references knowledge_chunks (id),
    shown      boolean not null default true,
    cited      boolean not null default false,
    primary key (opinion_id, chunk_id)
);

create index opinion_knowledge_refs_chunk_idx on opinion_knowledge_refs (chunk_id);
