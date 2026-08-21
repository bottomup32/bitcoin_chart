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

import json
import os

from adapters.resend_email import send_email
from agents import allocation, daily_signal, risk, tax
from agents.base import PROMPT_VERSION, model_id, run_agent, save_opinions
from agents.context import (
    BENCHMARK,
    correlation_context,
    market_context,
    portfolio_context,
    tax_context,
)
from agents.memory import build_memory, core_knowledge, with_core_knowledge
from core.claude_cli import cli_available, transport
from core.llm_log import CallRecord, measure_chars, record_call, usage_line
from core.orchestrator import orchestrate, synthesize_narrative, tax_alerts
from core.report import build_report
from core.trade_date import latest_completed_session
from db.client import get_conn

CRITICAL_AGENTS = {tax.NAME, risk.NAME}  # PLAN.md §1 [4] partial-failure policy


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
    if transport() == "claude_cli":
        if not cli_available():
            print("LLM_TRANSPORT=claude_cli but no claude CLI on PATH; skipping")
            return 0
    elif not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set; skipping advise run "
              "(or set LLM_TRANSPORT=claude_cli to use the subscription)")
        return 0

    session = latest_completed_session()
    if session is None:
        print("no completed NYSE session; exiting")
        return 0

    force = os.environ.get("FORCE_ADVISE", "").strip().lower() in ("1", "true", "yes")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select 1 from prices where ticker = %s and trade_date = %s",
            (BENCHMARK, session),
        )
        if cur.fetchone() is None:
            print(f"prices for {session} not ingested yet; run run_ingest first")
            return 1

        # The workflow fires two UTC slots to cover DST, and both resolve to
        # the same session — without this guard the agents would run twice a
        # day (double LLM spend) and mail two reports. Manual runs can force.
        cur.execute(
            "select 1 from runs where run_date = %s and status = 'succeeded'",
            (session,),
        )
        if cur.fetchone() is not None and not force:
            print(
                f"advice for {session} already generated; skipping "
                "(set FORCE_ADVISE=1, or use the workflow's 'force' input, to re-run)"
            )
            return 0

        # Nothing to advise on yet is a no-op, not a failure — same posture as
        # the holiday guard. Checked before a run row exists so empty days
        # leave no 'failed' rows behind.
        universe = _universe(cur)
        if not universe:
            print(
                "nothing to advise on: no holdings seeded and WATCHLIST is empty. "
                "Seed lots with jobs.ingest_portfolio, or set the WATCHLIST "
                "repository variable (e.g. NVDA,MSFT)."
            )
            return 0

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
        held = sorted(t for t, origin in universe.items() if origin == "holding")
        correlations = correlation_context(cur, held) if len(held) > 1 else {}

        # Memory: each agent's own recent calls and how they resolved, the
        # lessons drawn from them, and the endorsed principles today's market
        # state makes relevant — all filtered to what was knowable on this
        # session (agents/memory.py).
        memory, shown = build_memory(
            cur, session, sorted(universe),
            market=market, portfolio=portfolio,
            correlations=correlations, taxes=taxes,
        )
        # Shared across all four agents, so it is a candidate for a
        # cache_control breakpoint once it clears Sonnet's 1024-token minimum.
        core = core_knowledge(cur)
        core_chars = len(json.dumps(core, ensure_ascii=False)) if core else 0

        agent_calls = [
            (daily_signal.NAME, daily_signal.SYSTEM,
             daily_signal.build_context(cur, market, memory.get(daily_signal.NAME))),
            (allocation.NAME, allocation.SYSTEM,
             allocation.build_context(cur, market, portfolio, memory.get(allocation.NAME))),
            (risk.NAME, risk.SYSTEM,
             risk.build_context(cur, market, portfolio, correlations, memory.get(risk.NAME))),
            (tax.NAME, tax.SYSTEM, tax.build_context(cur, taxes, memory.get(tax.NAME))),
        ]

        failed: list[str] = []
        for name, role_prompt, context in agent_calls:
            system = with_core_knowledge(role_prompt, core)
            try:
                opinions, record = run_agent(
                    system, context, system_knowledge_chars=core_chars
                )
                n = save_opinions(cur, run_id, name, opinions, shown.get(name))
                record_call(cur, run_id=run_id, purpose=name, model_id=model_id(),
                            prompt_version=PROMPT_VERSION, record=record)
                conn.commit()
                print(f"{name}: {n} opinions, {usage_line(record.usage)}")
            except Exception as exc:  # noqa: BLE001 — policy decides fatal vs degraded
                conn.rollback()
                # Log the failed call too: a refusal or a timeout still costs
                # input tokens, and invisible failures under-report the bill.
                record_call(cur, run_id=run_id, purpose=name, model_id=model_id(),
                            prompt_version=PROMPT_VERSION,
                            record=CallRecord(
                                chars=measure_chars(system, context,
                                                    system_knowledge_chars=core_chars),
                                ok=False))
                conn.commit()
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

        narrative = None
        if decisions:
            narrative, record = synthesize_narrative(decisions, opinion_rows)
            record_call(cur, run_id=run_id, purpose="narrative", model_id=model_id(),
                        prompt_version=PROMPT_VERSION, record=record)
            conn.commit()
            print(f"narrative: {usage_line(record.usage)}")
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
        emailed, email_reason = False, "not attempted"
        try:
            emailed, email_reason = send_email(f"일일 포트폴리오 브리핑 — {session}", report_md)
        except Exception as exc:  # noqa: BLE001 — delivery failure shouldn't fail the run
            email_reason = f"{type(exc).__name__}"
        if not emailed:
            print(f"email not sent: {email_reason}")
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
