# 퀀트 멀티 에이전트 포트폴리오 매니저 — 개발 플랜 v1

> 개인 주식 포트폴리오를 위한 멀티 에이전트 자문 시스템.
> 외부 퀀트 리서치를 매일 수집하고, 실제 보유 자산(Fidelity)과 세금 상황을 고려해
> 단기·중장기·세금 세 시간축의 조언을 종합한다. 매일 페이퍼 트레이딩으로 조언을 채점하고
> 그 결과를 다음 조언에 반영하는 클로즈드 루프 학습 시스템이다.
>
> ⚠️ **면책**: 이 시스템은 정보 제공용이며 투자 자문이 아니다. 최종 결정은 사용자 본인의 책임이다.

---

## 0. 원안 검토 요약 — 무엇을 바꿨나

원안의 5층 아키텍처와 개발 순서는 그대로 유지한다. 검토 결과 수정·보강한 핵심 사항:

| # | 원안 | 검토 결과 → 변경 |
|---|------|------------------|
| 1 | Zacks Rank 류 스코어 수집 | Zacks는 공식 개인용 API가 없고 스크레이핑은 ToS 위반 소지. **1단계에서는 무료·합법 소스(가격/펀더멘털 API)로 시작**하고, 유료 스코어 소스는 어댑터 슬롯만 먼저 만들어 둔다. |
| 2 | `holdings`가 기본, `tax_lots`가 부속 | **`tax_lots`(매수 랏)가 원본 데이터**여야 한다. 같은 종목을 여러 번 사면 랏마다 취득일·단가·세금 상태가 다르다. `holdings`는 랏의 집계 뷰로 강등. |
| 3 | `days_to_longterm`, `unrealized_pnl`을 컬럼으로 저장 | 파생값은 저장하지 않고 **뷰/쿼리로 계산**. 저장하면 매일 갱신해야 하고 정합성이 깨진다. `realized_ytd`도 랏이 아닌 **연도 단위 테이블**로 분리. |
| 4 | hit_score로 채점 | "적중"의 정의가 없으면 학습 루프 전체가 흔들린다. **벤치마크(SPY) 대비 초과수익 + Brier score(확신도 보정)** 로 정의를 먼저 확정 (5장). |
| 5 | 적중률로 가중치 업데이트 | 일 단위 샘플은 노이즈가 크다. **베이지안 수축(shrinkage) + EMA**로 소표본 과잉반응을 방지. 가중치는 덮어쓰지 않고 **이력 테이블**로 보존. |
| 6 | LangGraph 등 프레임워크 | 이 파이프라인은 사이클 없는 일일 배치라 그래프 프레임워크가 과하다. **플레인 Python + Claude API 구조화 출력**으로 시작, 필요해지면 도입. |
| 7 | (누락) | **의사결정 시점 가격 스냅샷** 저장 — 이게 없으면 시뮬레이션 채점 자체가 불가능. |
| 8 | (누락) | **기업 액션(분할·배당) 처리**, 거래소 휴장일 캘린더, 리포트 전달 채널(이메일/대시보드) 명시. |

---

## 1. 아키텍처 — 5개 층 (확정)

```
┌────────────────────────────────────────────────────────┐
│  스케줄러 (GitHub Actions cron, 미국장 마감 후 평일)      │
└───────────────┬────────────────────────────────────────┘
                ▼
  [1] 데이터 인제스천 ──▶ Supabase (Postgres)
                              │
  [2] 포트폴리오·세금 상태 ────┤  (CSV 업로드 → 어댑터)
                              ▼
  [3] 분석 에이전트 × 5  ──▶ agent_opinions (구조화 JSON)
                              ▼
  [4] 오케스트레이터    ──▶ 일일 리포트 + 가상 결정 기록
                              ▼
  [5] 시뮬레이션·학습   ──▶ 채점 → 에이전트/소스 가중치 갱신
                              └──(다음 날 [4]에 반영)──┘
```

### [1] 데이터 인제스천 층

매 거래일 마감 후(권장: 미 동부 20:30 ET — 종가 데이터 정착 이후) 실행.

| 데이터 | 1단계 소스 (무료·합법) | 확장 슬롯 |
|--------|------------------------|-----------|
| OHLCV·기술지표 | yfinance 또는 Alpha Vantage(무료 티어) | Polygon.io (유료) |
| 펀더멘털·실적 | Financial Modeling Prep 무료 티어 / SEC EDGAR | FMP 유료 |
| 정량 스코어 | (1단계 생략 — 어댑터 인터페이스만 정의) | Zacks 구독 데이터 수동 입력, 기타 라이선스 소스 |
| 리서치 아이디어 | QuantSeeker·Alpha Architect **RSS/공개 글 요약**(LLM 태깅) | 뉴스레터 구독분 수동 투입 |
| 매크로 | FRED API(금리), CBOE VIX, 섹터 ETF 상대강도 | — |
| 캘린더 | `pandas-market-calendars`(휴장일), 어닝스 캘린더(FMP) | — |

원칙 (원안 유지 + 보강):
- 소스마다 `credibility_weight` 메타데이터. 초기값은 소스 유형별 사전값(prior)으로 설정하고, 학습 층이 **종목 단위 적중률**로 조정한다 (상업 뉴스레터의 "소수 대박" 착시 방지).
- 모든 인제스트는 원본 payload를 JSONB로 보존 (재채점·백필 가능하게).
- 어댑터 인터페이스 통일: `fetch() -> list[IngestRecord]`. 소스 추가 = 어댑터 1개 추가.

### [2] 사용자 상태 층 (Portfolio & Tax State)

- **Fidelity 연동**: 공식 개인용 실시간 API 없음 → **1단계는 Fidelity 웹의 "Positions" CSV 내보내기 업로드**. 어댑터로 추상화해 두고, 이후 SnapTrade/Plaid Investments 같은 애그리게이터로 교체 가능하게 한다.
- **랏(lot) 단위가 원본**: 종목·수량·매수단가·매수일을 랏 단위로 기록. 보유 기간(단기/장기 경계), 미실현 손익은 뷰로 계산.
- **세금 상태**: 장기 양도세율 요건은 **보유 1년 초과**(취득일 다음 날부터 기산). 연도별 실현 손익 누계는 `realized_events`에서 집계.
- **기업 액션**: 분할·배당 발생 시 랏의 수량/단가 조정 이벤트를 기록 (조정 이력 보존).

### [3] 분석 에이전트 층 — 5개 (시간축 3개)

각 에이전트는 Claude API 호출 1회(역할 시스템 프롬프트 + 해당 데이터 컨텍스트)로 구조화 JSON 의견을 낸다.

| 에이전트 | 시간축 | 입력 | 관점 |
|----------|--------|------|------|
| Daily Signal | 일~주 | 기술지표, 모멘텀, 거래량, 뉴스 이벤트 | 단기 신호 |
| Fundamental | 분기~ | 밸류에이션, 실적, EDGAR | 종목 펀더멘털 |
| Mid/Long-term Allocation | 월~년 | 포트폴리오 구성, 섹터/자산 배분, 매크로 | 리밸런싱 |
| Risk | 상시 | 집중도, 변동성, 드로다운, 상관관계 | 리스크 한도 |
| Tax | 상시 | 랏별 보유기간, 미실현 손익, 실현 누계 | 세금 최적화 |

의견 스키마 (모든 에이전트 공통, JSON Schema로 강제):

```json
{
  "ticker": "AAPL",
  "direction": "buy | hold | sell | trim | add",
  "confidence": 0.0,          // 0~1, 확률로 해석 (Brier 채점 대상)
  "timeframe": "days | weeks | months | quarters",
  "rationale": "…",
  "ref_source_ids": [1, 4],   // 근거로 쓴 소스 (소스 채점에 필요)
  "suggested_size_pct": null  // 선택: 포트폴리오 대비 제안 비중
}
```

- Tax Agent 하드 체크: **워시세일 30일 룰은 매도 전후 각 30일(총 61일 창), IRA 포함 전 계좌 합산** — LLM 판단이 아니라 코드 레벨 검증 함수로 구현하고 에이전트는 그 결과를 인용만 한다.

### [4] 오케스트레이터

- 5개 의견 + 현재 에이전트 가중치 + 소스 가중치를 입력으로 최종 조언 산출.
- 충돌 조율 규칙(코드) + LLM 종합(설명 생성)의 하이브리드:
  - 예: Daily=SELL, Tax="14일 후 장기 세율" → "14일 홀드 후 재평가"와 같은 시간축 조율은 **명시적 규칙**으로 우선 처리하고, LLM은 서술과 잔여 판단만 담당 (재현성 확보).
  - Risk Agent는 거부권(veto) 성격: 집중도/변동성 한도 초과 시 buy/add를 차단.
- 출력 2종:
  1. **일일 조언 리포트** (Markdown → 이메일/대시보드)
  2. **가상 결정 레코드** (`orchestrator_decisions` + 당일 종가 스냅샷) — 시뮬레이션 채점의 원천

### [5] 시뮬레이션 & 학습 루프

5장에서 상세 설계. 핵심: 실제 자금 미투입, 매일 가상 결정을 기록하고 1일/5일/21일 후 실제 수익률과 대조해 채점.

---

## 2. 데이터 모델 v2 (Supabase / Postgres)

원안 스키마에서 파생값 제거, 랏 중심 재편, 스냅샷·이력 테이블 추가.

```sql
-- 소스 및 인제스천
sources            (id, name, type, url, credibility_prior numeric,  -- 초기 사전값
                    created_at)
source_weights     (id, source_id, ticker nullable,                  -- 종목 단위 채점 지원
                    weight numeric, sample_n int, effective_from)    -- 이력 보존, 덮어쓰기 금지
daily_ingest       (id, source_id, ticker nullable, kind,            -- price|fundamental|research|macro
                    payload jsonb, ingested_at, trade_date)

-- 포트폴리오 (랏이 원본, holdings는 뷰)
accounts           (id, name, broker, tax_type)                      -- taxable|ira 등 (워시세일 합산용)
tax_lots           (id, account_id, ticker, qty numeric,
                    cost_basis numeric, acquired_at date,
                    closed_at date nullable, close_price nullable)
lot_adjustments    (id, lot_id, kind,                                -- split|dividend|correction
                    ratio, note, applied_at)
realized_events    (id, lot_id, sold_at, proceeds, gain, term)       -- short|long, 연간 누계는 집계
-- view: holdings        = open lots를 ticker별 집계
-- view: tax_status      = lot별 days_to_longterm, unrealized_pnl (당일 종가 join)

-- 에이전트 및 결정
runs               (id, run_date, status, started_at, finished_at)   -- 배치 실행 단위, 재실행 추적
agent_opinions     (id, run_id, agent, ticker, direction,
                    confidence numeric, timeframe, rationale,
                    ref_source_ids int[], suggested_size_pct nullable)
orchestrator_decisions
                   (id, run_id, ticker, action, combined_rationale,
                    confidence numeric,
                    price_at_decision numeric,                       -- ★ 채점의 기준점
                    benchmark_price_at_decision numeric)             -- SPY 종가

-- 시뮬레이션 및 학습
sim_evaluations    (id, decision_id, horizon,                        -- 1d|5d|21d
                    eval_date, actual_return numeric,
                    benchmark_return numeric,
                    excess_return numeric,
                    brier numeric,                                   -- (confidence - outcome)^2
                    hit boolean)
agent_weights      (id, agent, weight numeric, sample_n int,
                    effective_from)                                  -- 이력 보존
reports            (id, run_id, body_md, sent_at)
```

메모:
- `daily_ingest`는 월 수천 행 수준이라 파티셔닝 불요. JSONB 원본 보존으로 재채점 가능.
- Supabase RLS 활성화 + 서비스 역할 키는 GitHub Actions Secrets에만 저장. 보유 자산·세금 데이터는 민감 정보다.

---

## 3. 기술 스택 (확정안)

| 구성요소 | 선택 | 이유 |
|----------|------|------|
| 언어 | Python 3.12 (uv) | 데이터/퀀트 생태계, 어댑터 작성 용이 |
| 오케스트레이션 | 플레인 Python 상태 기계 | 사이클 없는 일일 배치에 LangGraph는 과함. 에이전트 5개 병렬 호출 + 순차 종합이면 충분. 필요해지면 교체 |
| LLM | Claude API — 분석 에이전트: `claude-sonnet-5`, 오케스트레이터 종합: `claude-sonnet-5` (비용 보고 필요시 상향) | 구조화 출력(JSON Schema) 지원, 에이전트당 1콜/일이라 비용 소액 |
| 스토리지 | Supabase (Postgres) | 원안 유지. RLS + 무료 티어로 충분 |
| 스케줄러 | GitHub Actions cron (평일 20:30 ET) + 휴장일 체크 후 조기 종료 | 무료, 리포와 같은 곳, Secrets 관리 용이 |
| 리포트 전달 | 1단계: 리포에 Markdown 커밋 + 이메일(Resend 무료 티어) / 이후: Netlify 대시보드 | 단순한 것부터 |
| 데이터 어댑터 | `adapters/` 패키지 — Fidelity CSV, yfinance, FRED, RSS 각각 독립 모듈 | 소스 교체·추가가 어댑터 1개 단위 |

레포 구조(안):

```
quant-pm/
├── adapters/          # fidelity_csv.py, prices_yf.py, fred.py, research_rss.py
├── agents/            # daily_signal.py, fundamental.py, allocation.py, risk.py, tax.py
│   └── prompts/       # 에이전트별 역할 프롬프트
├── core/              # orchestrator.py, conflict_rules.py, wash_sale.py, scoring.py
├── db/                # migrations/ (SQL), client.py
├── jobs/              # run_ingest.py, run_advise.py, run_evaluate.py
├── reports/           # 일일 리포트 출력 (md)
├── .github/workflows/ # daily.yml (cron)
└── PLAN.md
```

---

## 4. 평가·학습 루프 설계 (hit_score 정의)

학습 루프가 시스템의 핵심 차별점이므로 채점 정의를 먼저 못 박는다.

### 채점 (매 거래일, 지난 결정들을 재평가)

- **다중 시계**: 각 결정을 1d / 5d / 21d 후에 각각 채점. 시간축이 `days`인 의견은 1d·5d에, `months`는 21d에 주로 반영.
- **벤치마크 상대**: `excess_return = 종목수익률 − SPY수익률`. 시장이 다 오를 때 buy 적중으로 착각하는 것을 방지.
- **방향 적중(hit)**: buy/add → excess_return > 0, sell/trim → excess_return < 0, hold → |excess_return| < 임계값(예: ±1%).
- **확신도 보정(Brier)**: `brier = (confidence − hit)²`. 낮을수록 좋음. "항상 confidence 0.9"를 내는 에이전트를 자동 페널티.

### 가중치 업데이트 (소표본 과잉반응 방지)

```
raw_skill  = 1 − mean(brier)                        # 최근 N개 평가
posterior  = (prior_n × prior_skill + n × raw_skill) / (prior_n + n)   # 베이지안 수축
new_weight = EMA(α=0.1) of posterior                # 급변 방지
```

- 에이전트 가중치: 에이전트 단위. 소스 가중치: **소스 × 종목** 단위(뉴스레터 대박 착시 방지), 표본 부족 시 소스 전체 평균으로 폴백.
- 가중치는 오케스트레이터의 **참고 입력**일 뿐 강제 규칙이 아니다 (원안 원칙 유지). 모든 갱신은 이력 테이블에 append.

### 시뮬레이션 장부

- 가상 포트폴리오 1개(실보유 복제본으로 시작)를 유지하고 오케스트레이터 결정을 그대로 체결(당일 종가 기준, 슬리피지 0 가정).
- 주간 리포트에 가상 장부 vs 실제 보유 vs SPY 누적 성과 3선 비교를 포함.

---

## 5. 개발 순서 (원안 유지, 일부 조정)

원안의 6단계를 유지하되, **채점 정의(4장)를 스텝 1에 포함**시키고 평가 하네스를 앞당긴다.

| 단계 | 산출물 | 완료 기준 |
|------|--------|-----------|
| **1. 스키마 + 어댑터** | Supabase 마이그레이션, Fidelity CSV 업로드, yfinance 가격 인제스트, 휴장일 캘린더 | 실제 보유 랏이 DB에 들어가고 매일 가격이 쌓인다 |
| **2. 에이전트 3개** | Daily / Allocation / Tax (+ 워시세일 검증 함수) | 3개 에이전트가 구조화 의견을 DB에 기록 |
| **3. 오케스트레이터** | 충돌 규칙 + 종합, 일일 Markdown 리포트, 이메일 발송 | 매일 아침 조언 리포트가 도착한다 |
| **4. 시뮬레이션 기록** | 가상 장부, 결정 시 가격 스냅샷 | 결정이 페이퍼 트레이드로 기록된다 |
| **5. 평가 + 학습** | 1d/5d/21d 채점, Brier, 가중치 갱신 | 주 단위로 에이전트/소스 가중치가 데이터 기반으로 움직인다 |
| **6. 확장** | Fundamental·Risk 에이전트, 매크로/리서치 소스, (선택) Netlify 대시보드 | — |

각 단계는 독립적으로 배포 가능하며, 단계 1이 끝나는 순간부터 실제 데이터가 흐른다 (원안 원칙 유지).

---

## 6. 리스크 & 주의점

- **면책 고지**: 모든 리포트 하단에 "정보 제공용, 투자 자문 아님" 고지 삽입.
- **Fidelity 제약**: 공식 개인 API 없음. CSV 수동 업로드로 시작 — 업로드가 며칠 밀려도 시스템이 깨지지 않게 "상태 최신일" 표시.
- **워시세일**: 매도 전후 30일(61일 창), 전 계좌(IRA 포함) 합산, 코드 레벨 검증. "substantially identical" 판단(예: 동일 지수 ETF)은 보수적으로.
- **데이터 라이선스**: 유료 소스 스크레이핑 금지. 구독 콘텐츠는 수동 투입 슬롯으로.
- **학습 루프 과적합**: 일 단위 노이즈에 가중치가 출렁이지 않도록 수축+EMA. 표본 30개 미만이면 가중치 변경 폭 제한.
- **LLM 비용·재현성**: 에이전트 호출은 하루 5~6콜 수준으로 소액. 프롬프트·모델 버전을 `runs`에 기록해 재현성 확보.
- **비밀정보**: API 키·서비스 키는 GitHub Actions Secrets, DB는 RLS. 보유 자산 데이터는 개인 민감 정보로 취급.
