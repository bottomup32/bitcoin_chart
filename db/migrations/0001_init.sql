-- 0001_init.sql — schema v2 (PLAN.md §2)
-- Applied inside a transaction by jobs/apply_migrations.py

-- ── market data ────────────────────────────────────────────────────────────
-- Scoring, snapshots and tax views always join this table, never daily_ingest.
create table prices (
    ticker      text        not null,
    trade_date  date        not null,
    close       numeric     not null check (close > 0),
    adj_close   numeric     not null check (adj_close > 0),
    volume      bigint,
    source      text        not null,
    ingested_at timestamptz not null default now(),
    primary key (ticker, trade_date)
);

create table trading_sessions (
    trade_date date primary key,
    is_open    boolean not null
);

-- ── sources & ingestion ────────────────────────────────────────────────────
create table sources (
    id                bigint generated always as identity primary key,
    name              text not null unique,
    type              text not null check (type in ('price', 'fundamental', 'research', 'macro', 'scoring')),
    url               text,
    credibility_prior numeric not null default 0.5 check (credibility_prior between 0 and 1),
    created_at        timestamptz not null default now()
);

-- append-only; per-ticker rows, fall back to source average when sample is thin
create table source_weights (
    id             bigint generated always as identity primary key,
    source_id      bigint not null references sources (id),
    ticker         text,
    weight         numeric not null check (weight between 0 and 1),
    sample_n       integer not null default 0,
    n_eff          numeric,
    effective_from timestamptz not null default now()
);

-- raw payload archive for re-scoring/backfill; never a join target
create table daily_ingest (
    id          bigint generated always as identity primary key,
    source_id   bigint not null references sources (id),
    ticker      text,
    kind        text not null check (kind in ('price', 'fundamental', 'research', 'macro')),
    payload     jsonb not null,
    trade_date  date not null,
    ingested_at timestamptz not null default now()
);
create index daily_ingest_trade_date_idx on daily_ingest (trade_date);
create index daily_ingest_ticker_idx on daily_ingest (ticker);

-- ── portfolio: tax lots are the source of truth, holdings is a view ────────
create table accounts (
    id       bigint generated always as identity primary key,
    name     text not null unique,
    broker   text not null default 'fidelity',
    tax_type text not null check (tax_type in ('taxable', 'ira', 'other')),
    owner    text not null default 'self' check (owner in ('self', 'spouse'))
);

create table tax_lots (
    id                  bigint generated always as identity primary key,
    account_id          bigint not null references accounts (id),
    ticker              text not null,
    qty                 numeric not null check (qty > 0),
    cost_basis          numeric not null check (cost_basis >= 0), -- per share
    acquired_at         date not null,
    drip                boolean not null default false,           -- DRIP buys are new lots
    wash_sale_adjusted  boolean not null default false,
    external_ref        text unique,                              -- idempotent CSV ingestion
    created_at          timestamptz not null default now()
);
create index tax_lots_ticker_idx on tax_lots (ticker);

-- splits/spinoffs/return-of-capital/corrections only; cash dividends go to cash_events
create table lot_adjustments (
    id         bigint generated always as identity primary key,
    lot_id     bigint not null references tax_lots (id),
    kind       text not null check (kind in ('split', 'spinoff', 'return_of_capital', 'correction')),
    ratio      numeric,
    note       text,
    applied_at timestamptz not null default now()
);

create table cash_events (
    id           bigint generated always as identity primary key,
    account_id   bigint not null references accounts (id),
    ticker       text,
    kind         text not null check (kind in ('dividend', 'interest', 'deposit', 'withdrawal')),
    amount       numeric not null,
    occurred_at  date not null,
    external_ref text unique
);

-- open qty of a lot = tax_lots.qty − Σ realized_events.qty
create table realized_events (
    id           bigint generated always as identity primary key,
    lot_id       bigint not null references tax_lots (id),
    qty          numeric not null check (qty > 0),
    sold_at      date not null,
    proceeds     numeric not null,  -- total for this slice
    gain         numeric not null,
    term         text not null check (term in ('short', 'long')),
    wash_sale    boolean not null default false,
    external_ref text,
    unique (lot_id, external_ref)
);
create index realized_events_sold_at_idx on realized_events (sold_at);

-- ── agent runs & decisions (all idempotent via ON CONFLICT) ────────────────
create table runs (
    id             bigint generated always as identity primary key,
    run_date       date not null unique,
    status         text not null check (status in ('running', 'succeeded', 'failed')),
    prompt_version text,
    model_id       text,
    started_at     timestamptz not null default now(),
    finished_at    timestamptz
);

create table run_universe (
    run_id bigint not null references runs (id),
    ticker text not null,
    origin text not null check (origin in ('holding', 'research', 'watchlist')),
    primary key (run_id, ticker)
);

create table agent_opinions (
    id                 bigint generated always as identity primary key,
    run_id             bigint not null references runs (id),
    agent              text not null,
    ticker             text not null,
    direction          text not null check (direction in ('buy', 'hold', 'sell', 'trim', 'add')),
    confidence         numeric not null check (confidence between 0 and 1),
    timeframe          text not null check (timeframe in ('days', 'weeks', 'months', 'quarters')),
    rationale          text not null,
    ref_source_ids     bigint[] not null default '{}',
    suggested_size_pct numeric check (suggested_size_pct between 0 and 100),
    unique (run_id, agent, ticker)
);

create table orchestrator_decisions (
    id                    bigint generated always as identity primary key,
    run_id                bigint not null references runs (id),
    ticker                text not null,
    action                text not null check (action in ('buy', 'hold', 'sell', 'trim', 'add')),
    combined_rationale    text not null,
    confidence            numeric not null check (confidence between 0 and 1),
    price_at_decision     numeric not null,  -- close snapshot: scoring reference, NOT the fill price
    adj_price_at_decision numeric not null,
    benchmark_adj_price   numeric not null,  -- SPY adj close
    unique (run_id, ticker)
);

-- ── simulation & learning ──────────────────────────────────────────────────
-- paper fills happen at the NEXT session's open (no look-ahead)
create table sim_trades (
    id          bigint generated always as identity primary key,
    decision_id bigint not null unique references orchestrator_decisions (id),
    fill_date   date not null,
    fill_price  numeric not null check (fill_price > 0),
    qty         numeric not null
);

create table sim_evaluations (
    id               bigint generated always as identity primary key,
    opinion_id       bigint references agent_opinions (id),           -- per-agent scoring
    decision_id      bigint references orchestrator_decisions (id),
    horizon          text not null check (horizon in ('1d', '5d', '21d', '63d')),
    eval_trade_date  date,
    actual_return    numeric,
    benchmark_return numeric,
    excess_return    numeric,
    brier            numeric,
    hit              boolean,
    status           text not null default 'scored'
                     check (status in ('scored', 'unresolved', 'terminal')),
    check (opinion_id is not null or decision_id is not null),
    unique nulls not distinct (opinion_id, decision_id, horizon)
);

-- append-only
create table agent_weights (
    id             bigint generated always as identity primary key,
    agent          text not null,
    weight         numeric not null check (weight between 0 and 1),
    sample_n       integer not null default 0,
    n_eff          numeric,
    effective_from timestamptz not null default now()
);

create table reports (
    id      bigint generated always as identity primary key,
    run_id  bigint not null references runs (id),
    body_md text not null,
    sent_at timestamptz
);

-- ── views ──────────────────────────────────────────────────────────────────
create view lot_open_qty as
select tl.id as lot_id,
       tl.account_id,
       tl.ticker,
       tl.qty - coalesce(sum(re.qty), 0) as open_qty,
       tl.cost_basis,
       tl.acquired_at
from tax_lots tl
left join realized_events re on re.lot_id = tl.id
group by tl.id;

create view holdings as
select account_id,
       ticker,
       sum(open_qty)                                    as qty,
       sum(open_qty * cost_basis) / nullif(sum(open_qty), 0) as avg_cost
from lot_open_qty
where open_qty > 0
group by account_id, ticker;

-- long-term boundary: holding period starts the day AFTER acquisition;
-- a sale is long-term when sold strictly after acquired_at + 1 year.
create view tax_status as
select l.lot_id,
       l.account_id,
       l.ticker,
       l.open_qty,
       l.cost_basis,
       l.acquired_at,
       greatest(0, ((l.acquired_at + interval '1 year' + interval '1 day')::date - current_date)) as days_to_longterm,
       p.trade_date                                  as price_date,
       l.open_qty * (p.close - l.cost_basis)         as unrealized_pnl
from lot_open_qty l
left join lateral (
    select trade_date, close
    from prices
    where prices.ticker = l.ticker
    order by trade_date desc
    limit 1
) p on true
where l.open_qty > 0;

-- ── seed rows ──────────────────────────────────────────────────────────────
insert into sources (name, type, url, credibility_prior) values
    ('yfinance', 'price', 'https://pypi.org/project/yfinance/', 0.9),
    ('stooq',    'price', 'https://stooq.com',                  0.8);
