"""Daily advise job: run the analysis agents and store structured opinions.

Phase 2 scope (PLAN.md §5): three agents (daily_signal, allocation, tax) write
to agent_opinions. The orchestrator/report layer arrives in phase 3.

Partial-failure policy (PLAN.md §1 [4]): tax failure aborts the run; a
daily_signal/allocation failure is recorded and the run continues.

Requires ANTHROPIC_API_KEY and an already-ingested prices table for the
session (run_ingest runs first in the workflow). Logs print counts only.
"""

from __future__ import annotations

import os
import sys

from agents import allocation, daily_signal, tax
from agents.base import PROMPT_VERSION, model_id, run_agent, save_opinions
from agents.context import BENCHMARK, market_context, portfolio_context, tax_context
from core.trade_date import latest_completed_session
from db.client import get_conn

CRITICAL_AGENTS = {tax.NAME}


def _universe(cur) -> dict[str, str]:
    cur.execute("select distinct ticker from holdings")
    universe = {row[0]: "holding" for row in cur.fetchall()}
    for t in os.environ.get("WATCHLIST", "").split(","):
        t = t.strip().upper()
        if t and t not in universe:
            universe[t] = "watchlist"
    universe.pop(BENCHMARK, None)
    return universe


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set; skipping advise run")
        return 0

    session = latest_completed_session()
    if session is None:
        print("no completed NYSE session; exiting")
        return 0

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select 1 from prices where ticker = %s and trade_date = %s",
            (BENCHMARK, session),
        )
        if cur.fetchone() is None:
            print(f"prices for {session} not ingested yet; run run_ingest first")
            return 1

        cur.execute(
            """
            insert into runs (run_date, status, prompt_version, model_id)
            values (%s, 'running', %s, %s)
            on conflict (run_date) do update
                set status = 'running', prompt_version = excluded.prompt_version,
                    model_id = excluded.model_id, started_at = now(), finished_at = null
            returning id
            """,
            (session, PROMPT_VERSION, model_id()),
        )
        run_id = cur.fetchone()[0]

        universe = _universe(cur)
        if not universe:
            print("universe empty — seed holdings or set WATCHLIST")
            cur.execute("update runs set status = 'failed', finished_at = now() where id = %s", (run_id,))
            conn.commit()
            return 1
        for ticker, origin in universe.items():
            cur.execute(
                """
                insert into run_universe (run_id, ticker, origin)
                values (%s, %s, %s) on conflict do nothing
                """,
                (run_id, ticker, origin),
            )
        conn.commit()

        market = market_context(cur, sorted(universe))
        portfolio = portfolio_context(cur)
        taxes = tax_context(cur)

        agent_calls = [
            (daily_signal.NAME, daily_signal.SYSTEM, daily_signal.build_context(cur, market)),
            (allocation.NAME, allocation.SYSTEM, allocation.build_context(cur, market, portfolio)),
            (tax.NAME, tax.SYSTEM, tax.build_context(cur, taxes)),
        ]

        failed: list[str] = []
        for name, system, context in agent_calls:
            try:
                opinions = run_agent(system, context)
                n = save_opinions(cur, run_id, name, opinions)
                conn.commit()
                print(f"{name}: {n} opinions")
            except Exception as exc:  # noqa: BLE001 — policy decides fatal vs degraded
                conn.rollback()
                print(f"{name} failed: {type(exc).__name__}")
                failed.append(name)
                if name in CRITICAL_AGENTS:
                    cur.execute(
                        "update runs set status = 'failed', finished_at = now() where id = %s",
                        (run_id,),
                    )
                    conn.commit()
                    return 1

        status = "succeeded" if not failed else "failed"
        cur.execute(
            "update runs set status = %s, finished_at = now() where id = %s",
            (status, run_id),
        )
        conn.commit()
        print(f"run {session}: {status}" + (f" (degraded: {','.join(failed)})" if failed else ""))
        return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
