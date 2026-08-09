-- 0004_as_of_learned_state.sql — every learned state carries a knowable-at date
--
-- core/orchestrator.py's latest_agent_weights had no as-of filter at all. Live
-- that is benign, because run_evaluate runs after run_advise on the same day,
-- but it is a real replay bug: FORCE_ADVISE=1 on an old session pulled today's
-- weights into that session's decision. Memory sets the precedent that all
-- learned state is filtered to what was knowable on the session being advised,
-- so the existing learned state is brought under the same rule here.

alter table agent_weights  add column as_of_trade_date date;
alter table source_weights add column as_of_trade_date date;

-- Backfill: effective_from is the only date the existing rows carry.
update agent_weights set as_of_trade_date = effective_from::date
where as_of_trade_date is null;

create index agent_weights_as_of_idx  on agent_weights  (agent, as_of_trade_date desc);
create index source_weights_as_of_idx on source_weights (source_id, ticker, as_of_trade_date desc);

-- Audit only. This column MUST NOT become a retrieval filter: a legitimately
-- backfilled evaluation has a late created_at and an early eval_trade_date, so
-- filtering on it would wrongly hide real rows. eval_trade_date <= D is the
-- correct and sufficient filter — an evaluation whose horizon endpoint is on or
-- before D derives entirely from adj_close values knowable at D, and PLAN.md §4
-- already forbids re-fetching prices at evaluation time.
alter table sim_evaluations add column created_at timestamptz not null default now();
