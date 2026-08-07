"""Orchestrator glue: opinions + weights + tax state → decisions → report data.

Decisions are produced by the deterministic rules in core/conflict_rules.py
and stored with same-day price snapshots (the scoring reference — paper fills
happen at the NEXT session's open, recorded by the phase-4 simulation job).
The LLM contributes narrative only, and its failure never blocks the run.
"""

from __future__ import annotations

from datetime import date

from core.conflict_rules import Decision, OpinionInput, TaxFlags, decide

BENCHMARK = "SPY"


def flags_from_lots(lots: list[dict], wash_risk: dict[str, str]) -> dict[str, TaxFlags]:
    """Fold tax_context lot rows into per-ticker TaxFlags. Pure."""
    flags: dict[str, TaxFlags] = {}
    for lot in lots:
        f = flags.setdefault(lot["ticker"], TaxFlags())
        pnl = lot.get("unrealized_pnl")
        if pnl is not None and pnl > 0:
            f.has_unrealized_gain = True
            days = lot["days_to_longterm"]
            if days > 0 and (f.days_to_longterm is None or days < f.days_to_longterm):
                f.days_to_longterm = days
        if pnl is not None and pnl < 0:
            f.has_unrealized_loss = True
    for ticker, msg in wash_risk.items():
        flags.setdefault(ticker, TaxFlags()).wash_sale_risk = msg
    return flags


def latest_agent_weights(cur) -> dict[str, float]:
    cur.execute(
        """
        select distinct on (agent) agent, weight
        from agent_weights order by agent, effective_from desc
        """
    )
    return {agent: float(w) for agent, w in cur.fetchall()}


def orchestrate(cur, run_id: int, run_date: date, tax_ctx: dict) -> tuple[list[Decision], int]:
    """Combine the run's opinions into decisions and upsert them with snapshots."""
    cur.execute(
        """
        select agent, ticker, direction, confidence, timeframe
        from agent_opinions where run_id = %s
        """,
        (run_id,),
    )
    by_ticker: dict[str, list[OpinionInput]] = {}
    for agent, ticker, direction, confidence, timeframe in cur.fetchall():
        by_ticker.setdefault(ticker, []).append(
            OpinionInput(agent=agent, direction=direction,
                         confidence=float(confidence), timeframe=timeframe)
        )

    weights = latest_agent_weights(cur)
    flags = flags_from_lots(tax_ctx["lots"], tax_ctx["wash_sale_risk"])

    cur.execute(
        "select close, adj_close from prices where ticker = %s and trade_date = %s",
        (BENCHMARK, run_date),
    )
    spy = cur.fetchone()

    decisions: list[Decision] = []
    skipped = 0
    for ticker, opinions in sorted(by_ticker.items()):
        cur.execute(
            "select close, adj_close from prices where ticker = %s and trade_date = %s",
            (ticker, run_date),
        )
        price = cur.fetchone()
        if price is None or spy is None:
            skipped += 1  # no snapshot → not scorable → don't record a decision
            continue

        d = decide(ticker, opinions, weights, flags.get(ticker))
        cur.execute(
            """
            insert into orchestrator_decisions
                (run_id, ticker, action, combined_rationale, confidence,
                 price_at_decision, adj_price_at_decision, benchmark_adj_price)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (run_id, ticker) do update
                set action = excluded.action,
                    combined_rationale = excluded.combined_rationale,
                    confidence = excluded.confidence,
                    price_at_decision = excluded.price_at_decision,
                    adj_price_at_decision = excluded.adj_price_at_decision,
                    benchmark_adj_price = excluded.benchmark_adj_price
            """,
            (run_id, ticker, d.action, d.rationale, d.confidence,
             price[0], price[1], spy[1]),
        )
        decisions.append(d)
    return decisions, skipped


def tax_alerts(tax_ctx: dict, transition_days: int = 45) -> dict:
    transitions = []
    seen: dict[str, int] = {}
    for lot in tax_ctx["lots"]:
        pnl = lot.get("unrealized_pnl")
        days = lot["days_to_longterm"]
        if pnl is not None and pnl > 0 and 0 < days <= transition_days:
            if lot["ticker"] not in seen or days < seen[lot["ticker"]]:
                seen[lot["ticker"]] = days
    transitions = [{"ticker": t, "days": d} for t, d in seen.items()]
    return {"wash_sale_risk": tax_ctx["wash_sale_risk"], "transitions": transitions}


NARRATIVE_SYSTEM = (
    "당신은 개인 포트폴리오 자문 시스템의 오케스트레이터입니다. 아래 JSON의 "
    "최종 결정과 에이전트 의견을 바탕으로, 한국어로 4~6문장의 일일 요약을 "
    "작성하세요. 결정을 바꾸거나 새 종목을 언급하지 말고, 숫자는 제공된 값만 "
    "인용하세요. 어조는 담백하게, 투자 자문이 아닌 정보 제공임을 전제로."
)


def synthesize_narrative(decisions: list[Decision], opinions: list[dict]) -> str | None:
    """One LLM call for the report's summary prose. Returns None on any failure."""
    import json

    import anthropic

    from agents.base import model_id

    payload = {
        "decisions": [
            {"ticker": d.ticker, "action": d.action, "confidence": d.confidence,
             "rules_applied": d.rules_applied, "revisit_days": d.revisit_days}
            for d in decisions
        ],
        "opinions": opinions,
    }
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model_id(),
            max_tokens=1500,
            system=NARRATIVE_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
        if response.stop_reason == "refusal":
            return None
        return next((b.text for b in response.content if b.type == "text"), None)
    except Exception:  # noqa: BLE001 — narrative is optional by design
        return None
