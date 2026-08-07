from datetime import date

from core.report import build_report

DECISIONS = [
    {"ticker": "AAPL", "action": "hold", "confidence": 0.9,
     "rationale": "daily_signal: sell (0.80); T1: hold", "revisit_days": 30},
    {"ticker": "NVDA", "action": "trim", "confidence": 0.7,
     "rationale": "T3 harvest", "revisit_days": None},
]
OPINIONS = [
    {"agent": "daily_signal", "ticker": "AAPL", "direction": "sell",
     "confidence": 0.8, "timeframe": "days", "rationale": "momentum broke"},
    {"agent": "tax", "ticker": "AAPL", "direction": "hold",
     "confidence": 0.9, "timeframe": "months", "rationale": "30 days to long-term"},
]
ALERTS = {
    "wash_sale_risk": {"NVDA": "recent purchase in window"},
    "transitions": [{"ticker": "AAPL", "days": 30}],
}


def test_report_contains_all_sections():
    md = build_report(date(2026, 8, 6), DECISIONS, OPINIONS, ALERTS,
                      narrative="오늘은 요약입니다.", portfolio_as_of="2026-08-01")
    assert "일일 포트폴리오 브리핑 — 2026-08-06" in md
    assert md.count("투자 자문이 아닙니다") == 2      # header + footer disclaimer
    assert "| AAPL | **홀드 (30일 후 재평가)** | 90% |" in md
    assert "| NVDA | **비중 축소** | 70% |" in md
    assert "워시세일 주의" in md and "recent purchase in window" in md
    assert "장기 양도세율 전환 임박" in md and "30일 후 장기 세율" in md
    assert "### daily_signal" in md and "### tax" in md
    assert "오늘의 요약" in md and "포트폴리오 상태 최신일: 2026-08-01" in md


def test_report_without_decisions_or_narrative():
    md = build_report(date(2026, 8, 6), [], [], {"wash_sale_risk": {}, "transitions": []},
                      narrative=None, portfolio_as_of=None)
    assert "오늘은 결정이 없습니다" in md
    assert "오늘의 요약" not in md
    assert "워시세일" not in md
