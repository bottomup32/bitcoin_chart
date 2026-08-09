"""Read back LLM token spend — locally, with no LLM calls.

Increment 0 of the memory plan: measure the baseline before adding anything to
the prompts, so every later number is attributable. Reads llm_calls and the
llm_cost_daily view; prints counts only, never prompt or response content.

Usage:
  python -m jobs.show_costs                  # last 30 days, per-day totals
  python -m jobs.show_costs --by-purpose     # per-day x per-agent breakdown
  python -m jobs.show_costs --days 90
"""

from __future__ import annotations

import argparse

from db.client import get_conn

# Sonnet 5 list price, USD per million tokens (PLAN.md §3). Cache writes bill at
# 1.25x input, cache reads at 0.1x. Override with --in-price/--out-price when
# running on another model.
DEFAULT_INPUT_PRICE = 3.0
DEFAULT_OUTPUT_PRICE = 15.0
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int,
    cache_read_tokens: int,
    in_price: float,
    out_price: float,
) -> float:
    """USD for one bucket of usage. Pure — unit-tested in tests/test_llm_log.py.

    input_tokens from the API already excludes cached reads and cache writes,
    so the three input-side terms add rather than overlap.
    """
    return (
        input_tokens * in_price
        + cache_write_tokens * in_price * CACHE_WRITE_MULTIPLIER
        + cache_read_tokens * in_price * CACHE_READ_MULTIPLIER
        + output_tokens * out_price
    ) / 1_000_000


def _print_daily(cur, days: int, in_price: float, out_price: float) -> None:
    cur.execute(
        """
        select run_date, calls, failed_calls, input_tokens, output_tokens,
               cache_creation_tokens, cache_read_tokens,
               est_knowledge_tokens, est_short_term_tokens, est_long_term_tokens
        from llm_cost_daily
        where run_date >= current_date - %s
        order by run_date desc
        """,
        (days,),
    )
    rows = cur.fetchall()
    if not rows:
        print("no LLM calls recorded yet — run jobs.run_advise first")
        return

    print(f"{'date':<12} {'calls':>5} {'fail':>4} {'in':>8} {'out':>7} "
          f"{'c_wr':>7} {'c_rd':>7} {'know':>6} {'short':>6} {'long':>6} {'USD':>8}")
    total = 0.0
    for (run_date, calls, failed, tin, tout, cwr, crd, know, short, long_) in rows:
        cost = estimate_cost(tin or 0, tout or 0, cwr or 0, crd or 0, in_price, out_price)
        total += cost
        print(f"{run_date!s:<12} {calls:>5} {failed:>4} {tin or 0:>8} {tout or 0:>7} "
              f"{cwr or 0:>7} {crd or 0:>7} {int(know or 0):>6} {int(short or 0):>6} "
              f"{int(long_ or 0):>6} {cost:>8.4f}")
    print(f"\n{len(rows)} days, ${total:.4f} total, ${total / max(len(rows), 1):.4f}/day "
          f"(~${total / max(len(rows), 1) * 21:.2f}/month at 21 sessions)")
    print("know/short/long = input tokens attributed to each memory block "
          "(proportional to serialized chars)")


def _print_by_purpose(cur, days: int, in_price: float, out_price: float) -> None:
    cur.execute(
        """
        select coalesce(r.run_date, c.created_at::date) as run_date,
               c.purpose,
               count(*)                                 as calls,
               sum(c.input_tokens)                      as input_tokens,
               sum(c.output_tokens)                     as output_tokens,
               sum(c.cache_creation_input_tokens)       as cache_write,
               sum(c.cache_read_input_tokens)           as cache_read
        from llm_calls c
        left join runs r on r.id = c.run_id
        where coalesce(r.run_date, c.created_at::date) >= current_date - %s
        group by 1, 2
        order by 1 desc, 2
        """,
        (days,),
    )
    rows = cur.fetchall()
    if not rows:
        print("no LLM calls recorded yet — run jobs.run_advise first")
        return

    print(f"{'date':<12} {'purpose':<16} {'calls':>5} {'in':>8} {'out':>7} {'USD':>8}")
    for run_date, purpose, calls, tin, tout, cwr, crd in rows:
        cost = estimate_cost(tin or 0, tout or 0, cwr or 0, crd or 0, in_price, out_price)
        print(f"{run_date!s:<12} {purpose:<16} {calls:>5} {tin or 0:>8} "
              f"{tout or 0:>7} {cost:>8.4f}")
    print("\noutput tokens bill at 5x input — watch this column for rationale bloat")


def main() -> int:
    parser = argparse.ArgumentParser(prog="show_costs")
    parser.add_argument("--days", type=int, default=30, help="lookback window (default 30)")
    parser.add_argument("--by-purpose", action="store_true",
                        help="break each day down by agent / narrative")
    parser.add_argument("--in-price", type=float, default=DEFAULT_INPUT_PRICE,
                        help="USD per million input tokens")
    parser.add_argument("--out-price", type=float, default=DEFAULT_OUTPUT_PRICE,
                        help="USD per million output tokens")
    args = parser.parse_args()

    with get_conn() as conn, conn.cursor() as cur:
        if args.by_purpose:
            _print_by_purpose(cur, args.days, args.in_price, args.out_price)
        else:
            _print_daily(cur, args.days, args.in_price, args.out_price)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
