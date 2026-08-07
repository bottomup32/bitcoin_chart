"""Daily advise job: agents → orchestrator → decisions → report (PLAN.md §5 2-3단계).

Flow: session guard → record run + universe → run 3 agents (structured
opinions) → deterministic conflict rules produce decisions with price
snapshots → build the Korean daily report (LLM narrative optional) → store in
reports and email via Resend when configured.

Partial-failure policy (PLAN.md §1 [4]): tax failure aborts the run; a
daily_signal/allocation failure is recorded and the run continues degraded.

Requires ANTHROPIC_API_KEY and an already-ingested prices table for the
session (run_ingest runs first in the workflow). Logs print counts only —
never holdings or report contents (PLAN.md §6).
"""

from __future__ import annotations

import os

from adapters.resend_email import send_email
from agents import allocation, daily_signal, tax
from agents.base import PROMPT_VERSION, model_id, run_agent, save_opinions
from agents.context import BENCHMARK, market_context, portfolio_context, tax_context
from core.orchestrator import orchestrate, synthesize_narrative, tax_alerts
from core.report import build_report
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

        # ── orchestrate: deterministic rules → decisions with price snapshots ──
        decisions, skipped = orchestrate(cur, run_id, session, taxes)
        conn.commit()
        print(f"orchestrator: {len(decisions)} decisions" +
              (f", {skipped} tickers skipped (no price snapshot)" if skipped else ""))

        # ── report: markdown + optional LLM narrative, stored + emailed ──
        cur.execute(
            """
            select agent, ticker, direction, confidence, timeframe, rationale
            from agent_opinions where run_id = %s
            """,
            (run_id,),
        )
        opinion_rows = [
            {"agent": r[0], "ticker": r[1], "direction": r[2],
             "confidence": float(r[3]), "timeframe": r[4], "rationale": r[5]}
            for r in cur.fetchall()
        ]
        cur.execute("select max(created_at)::date from tax_lots")
        as_of = cur.fetchone()[0]

        narrative = synthesize_narrative(decisions, opinion_rows) if decisions else None
        report_md = build_report(
            run_date=session,
            decisions=[
                {"ticker": d.ticker, "action": d.action, "confidence": d.confidence,
                 "rationale": d.rationale, "revisit_days": d.revisit_days}
                for d in decisions
            ],
            opinions=opinion_rows,
            tax_alerts=tax_alerts(taxes),
            narrative=narrative,
            portfolio_as_of=as_of.isoformat() if as_of else None,
        )
        emailed = False
        try:
            emailed = send_email(f"일일 포트폴리오 브리핑 — {session}", report_md)
        except Exception as exc:  # noqa: BLE001 — delivery failure shouldn't fail the run
            print(f"email delivery failed: {type(exc).__name__}")
        cur.execute(
            """
            insert into reports (run_id, body_md, sent_at)
            values (%s, %s, case when %s then now() end)
            """,
            (run_id, report_md, emailed),
        )
        print(f"report stored ({len(report_md)} chars), emailed={emailed}, "
              f"narrative={'yes' if narrative else 'no'}")

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
