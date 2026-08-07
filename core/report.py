"""Daily report builder — pure markdown assembly, Korean output.

The report is delivered by email and stored in the reports table only; it is
never committed to the repo and never printed to CI logs (PLAN.md §6).
"""

from __future__ import annotations

from datetime import date

ACTION_LABEL = {
    "buy": "매수", "add": "비중 확대", "hold": "홀드", "trim": "비중 축소", "sell": "매도",
}

DISCLAIMER = (
    "> ⚠️ 본 리포트는 정보 제공용이며 투자 자문이 아닙니다. "
    "모든 투자 결정과 그 결과는 본인의 책임입니다."
)


def build_report(
    run_date: date,
    decisions: list[dict],       # ticker, action, confidence, rationale, revisit_days
    opinions: list[dict],        # agent, ticker, direction, confidence, rationale
    tax_alerts: dict,            # wash_sale_risk: {ticker: msg}, transitions: [{ticker, days, ...}]
    narrative: str | None,
    portfolio_as_of: str | None,
) -> str:
    lines = [f"# 일일 포트폴리오 브리핑 — {run_date}", "", DISCLAIMER, ""]
    if portfolio_as_of:
        lines += [f"_포트폴리오 상태 최신일: {portfolio_as_of}_", ""]

    if narrative:
        lines += ["## 오늘의 요약", "", narrative.strip(), ""]

    lines += ["## 최종 결정", ""]
    if decisions:
        lines += ["| 종목 | 결정 | 확신도 | 근거 |", "|---|---|---|---|"]
        for d in sorted(decisions, key=lambda d: d["ticker"]):
            action = ACTION_LABEL.get(d["action"], d["action"])
            if d.get("revisit_days"):
                action += f" ({d['revisit_days']}일 후 재평가)"
            lines.append(
                f"| {d['ticker']} | **{action}** | {d['confidence']:.0%} | {d['rationale']} |"
            )
        lines.append("")
    else:
        lines += ["오늘은 결정이 없습니다.", ""]

    if tax_alerts.get("wash_sale_risk"):
        lines += ["## ⚠️ 워시세일 주의", ""]
        for ticker, msg in sorted(tax_alerts["wash_sale_risk"].items()):
            lines.append(f"- **{ticker}**: {msg}")
        lines.append("")
    if tax_alerts.get("transitions"):
        lines += ["## 장기 양도세율 전환 임박", ""]
        for t in sorted(tax_alerts["transitions"], key=lambda t: t["days"]):
            lines.append(f"- **{t['ticker']}**: {t['days']}일 후 장기 세율 적용")
        lines.append("")

    lines += ["## 에이전트 의견 상세", ""]
    for agent in sorted({o["agent"] for o in opinions}):
        lines.append(f"### {agent}")
        for o in sorted((o for o in opinions if o["agent"] == agent), key=lambda o: o["ticker"]):
            lines.append(
                f"- **{o['ticker']}** {o['direction']} ({o['confidence']:.0%}, {o['timeframe']}): "
                f"{o['rationale']}"
            )
        lines.append("")

    lines += ["---", DISCLAIMER, ""]
    return "\n".join(lines)
