# 퀀트 멀티 에이전트 포트폴리오 매니저 — 개발 플랜 v1.1

> 개인 주식 포트폴리오를 위한 멀티 에이전트 자문 시스템.
> 외부 퀀트 리서치를 매일 수집하고, 실제 보유 자산(Fidelity)과 세금 상황을 고려해
> 단기·중장기·세금 세 시간축의 조언을 종합한다. 매일 페이퍼 트레이딩으로 조언을 채점하고
> 그 결과를 다음 조언에 반영하는 클로즈드 루프 학습 시스템이다.
>
> ⚠️ **면책**: 이 시스템은 정보 제공용이며 투자 자문이 아니다. 최종 결정은 사용자 본인의 책임이다.
>
> v1.1: 초안(v1)을 도메인(퀀트·세금) 관점과 아키텍처(실현 가능성) 관점에서 각각 독립 리뷰한 뒤
> 발견 사항 35건을 반영한 버전. 변경 요지는 0장 참조.

---

## 0. 원안 → v1.1 검토 요약

원안의 5층 아키텍처와 개발 순서는 그대로 유지한다. 두 차례 검토에서 수정·보강한 핵심:

**데이터 소스 현실성**
- Zacks는 공식 개인용 API가 없고 스크레이핑은 ToS 위반 소지 → 어댑터 슬롯만 정의, 유료 소스는 나중에.
- Alpha Vantage 무료 티어는 현재 25콜/일로 축소되어 일일 소스로 부적합. **yfinance(버전 고정)를 1차, Stooq/Tiingo 무료 티어를 폴백 어댑터**로.
- FMP 무료 티어의 어닝스 캘린더 엔드포인트는 구현 전 사용 가능 여부 재확인.

**Fidelity 연동 — 원안의 치명적 가정 수정**
- Fidelity **Positions CSV에는 랏(lot) 단위 데이터가 없다** (포지션당 집계 1행). 랏을 원본으로 삼는 설계와 맞지 않음.
- → 최초 1회는 Fidelity 웹의 랏 상세 화면을 보고 수동 시딩, 이후에는 **Activity/History CSV(거래 단위)** 로 랏을 유지하고, Positions CSV는 대사(reconciliation)용으로만 사용.
- CSV가 GitHub Actions까지 갈 경로도 없었음 → **로컬 CLI 명령이 CSV를 파싱해 Supabase에 직접 업서트**. 민감한 보유 데이터는 절대 git에 커밋하지 않는다.

**데이터 모델**
- `tax_lots`(랏)가 원본, `holdings`는 뷰 — 유지. 단, 부분 매도를 표현할 수 있게 `realized_events.qty` 추가.
- 파생값(`days_to_longterm`, `unrealized_pnl`)은 저장하지 않고 뷰로 계산.
- **일급 `prices` 테이블 신설** — 채점·스냅샷·세금 뷰가 전부 여기에 조인한다. JSONB 아카이브에 조인하지 않는다.
- 배당은 랏 조정이 아니라 현금 이벤트. DRIP은 새 랏. 랏 조정은 분할/스핀오프/자본환급/정정만.

**채점·학습 루프 — 통계적 결함 수정**
- **룩어헤드 제거**: 당일 종가로 결정하고 당일 종가로 체결하면 미래 참조. 페이퍼 체결은 **다음 거래일 시가**.
- **수정주가 일관성**: 분할·배당으로 과거 시계열이 재조정되므로, 평가 시 외부 재조회 금지 — 자체 저장한 `adj_close` 시계열로만 수익률 계산. SPY도 총수익 기준으로 통일.
- **에이전트별 채점**: 오케스트레이터 결정만 채점하면 어느 에이전트가 맞았는지 알 수 없다 → **의견(opinion) 단위 평가** 추가.
- **Tax·Risk 에이전트는 방향 채점에서 제외** — 세금 매도는 "주가가 SPY를 밑돈다"는 예측이 아니다. v1에서는 이 둘의 가중치 학습 없음.
- Brier는 **의견의 timeframe과 일치하는 시계 1개에서만** 가중치에 반영, 나머지 시계는 진단용.
- 겹치는 평가 윈도우로 표본이 부풀지 않게 **유효 표본 수(n_eff ≈ n/시계일수)** 로 수축.
- 상장폐지·인수합병 종목의 평가를 조용히 누락하면 생존 편향 → 종결 규칙 명시.

**운영**
- cron은 UTC 자정 넘김 + DST 문제 → UTC로 두 슬롯 걸고 **잡 첫 단계에서 NYSE 세션 가드**로 일괄 해결.
- GitHub Actions 스케줄은 best-effort(지연·스킵·60일 자동 비활성) → 모든 잡을 **멱등 + 캐치업** 구조로.
- RLS는 서비스 키 경로에서 무력(바이패스) → 실제 통제는 시크릿 관리·anon 키 비노출. RLS·Auth는 대시보드 단계의 선행 조건.
- 리포트를 리포에 커밋하지 않는다(보유 데이터가 git 이력에 영구 잔류) → 이메일/DB로만 전달.
- LangGraph 불채택 유지 — 잡 스크립트 3개 + `runs` 테이블이면 충분. 실제 어려운 부분은 재시도·부분 실패 정책.

---

## 1. 아키텍처 — 5개 층 (확정)

```
┌─────────────────────────────────────────────────────────────┐
│ 스케줄러: GitHub Actions cron (UTC 00:30/01:30, 화–토)        │
│  └─ 첫 단계: "완결된 NYSE 세션인가?" 가드 → 아니면 exit 0      │
└───────────────┬─────────────────────────────────────────────┘
                ▼
  [1] 데이터 인제스천 ──▶ Supabase (prices + daily_ingest 아카이브)
                              │
  [2] 포트폴리오·세금 상태 ────┤  (로컬 CLI: Fidelity CSV → Supabase 직접 업서트)
                              ▼
  [3] 분석 에이전트 × 5  ──▶ agent_opinions (구조화 JSON)
                              ▼
  [4] 오케스트레이터    ──▶ 일일 리포트(이메일) + 가상 결정 기록
                              ▼
  [5] 시뮬레이션·학습   ──▶ 다음 시가 체결 → 시계별 채점 → 가중치 갱신
                              └──────(다음 날 [4]에 반영)──────┘
```

### [1] 데이터 인제스천 층

매 거래일 마감 후(미 동부 20:30 ET 목표 — 종가 데이터 정착 이후) 실행.

| 데이터 | 1단계 소스 | 폴백/확장 |
|--------|-----------|-----------|
| OHLCV (close + **adj_close**) | yfinance (버전 고정) | Stooq / Tiingo 무료 티어 (폴백 어댑터를 처음부터 구현) |
| 펀더멘털·실적 | SEC EDGAR / FMP 무료 티어(엔드포인트 가용성 사전 확인) | FMP 유료 |
| 정량 스코어 | (1단계 생략 — 어댑터 인터페이스만 정의) | Zacks 구독 데이터 수동 입력 등 라이선스 소스 |
| 리서치 아이디어 | QuantSeeker·Alpha Architect RSS/공개 글 요약(LLM 태깅) | 뉴스레터 구독분 수동 투입 |
| 매크로 | FRED API(금리), VIX, 섹터 ETF 상대강도 | — |
| 캘린더 | `pandas-market-calendars`(NYSE 세션·휴장일) | 어닝스 캘린더 |

원칙:
- **`trade_date`는 잡 내부에서 `today()`로 계산하지 않는다.** "America/New_York 기준 가장 최근 완결된 NYSE 세션"을 한 곳(코어 함수)에서 계산해 모든 잡에 주입. (20:30 ET = UTC 다음 날 00:30/01:30이므로 UTC 날짜를 쓰면 하루 밀린다.)
- 가격은 일급 `prices` 테이블에 `(ticker, trade_date)` 유니크로 저장하고, **평가·채점은 자체 저장 시계열만 사용** (외부 소스의 소급 재조정·장애로부터 절연).
- 소스마다 신뢰도 사전값(prior)을 메타데이터로 저장, 학습 층이 **종목 단위 적중률**로 조정 (뉴스레터 "소수 대박" 착시 방지).
- 원본 payload는 JSONB로 보존(재채점·백필용 아카이브 — 조인 대상 아님).
- 어댑터 인터페이스 통일: `fetch(trade_date) -> list[IngestRecord]`. 소스 추가 = 어댑터 1개.

### [2] 사용자 상태 층 (Portfolio & Tax State)

- **인제스천 경로**: 로컬 CLI `python -m jobs.ingest_portfolio <csv>` 가 파싱 후 Supabase에 직접 업서트. CSV·보유 데이터는 git에 절대 커밋하지 않는다. GitHub Actions는 DB만 읽는다.
- **랏 시딩·유지**:
  - 최초 1회: Fidelity 웹 포지션별 cost-basis(랏 상세) 화면 기준 수동 시딩 (Positions CSV에는 랏 정보가 없음).
  - 이후: **Activity/History CSV**(거래 단위: 일자·수량·가격)로 랏 생성/차감. Positions CSV는 주기적 대사용.
  - 파서는 Fidelity CSV의 머리말/면책 꼬리행·컬럼명 변경에 관대하게.
- **세금 상태**: 장기 양도세율 요건은 **보유 1년 초과**(취득일 다음 날부터 기산). 랏별 잔여일수·미실현 손익은 뷰로 계산(당일 `prices` 조인). 연도별 실현 누계는 `realized_events` 집계.
- **기업 액션**: 분할/스핀오프/자본환급/정정만 `lot_adjustments`. 현금 배당은 `cash_events`, DRIP 매수는 **새 랏**(각 DRIP 매수도 워시세일 판정 대상).
- 업로드가 밀려도 시스템이 깨지지 않게 리포트에 "포트폴리오 상태 최신일" 표시.

### [3] 분석 에이전트 층 — 5개

각 에이전트는 Claude API 호출 1회(역할 프롬프트 + 해당 데이터 컨텍스트)로 구조화 JSON 의견을 낸다.

| 에이전트 | 시간축 | 관점 | 가중치 학습 |
|----------|--------|------|------------|
| Daily Signal | 일~주 | 기술지표·모멘텀·거래량·이벤트 | ✅ 방향+Brier |
| Fundamental | 분기 | 밸류에이션·실적·EDGAR | ✅ 방향+Brier (63d 시계) |
| Mid/Long-term Allocation | 월~분기 | 배분·리밸런싱·매크로 | ✅ 방향+Brier |
| Risk | 상시 | 집중도·변동성·드로다운·상관 | ❌ v1 학습 제외 (거부권 역할) |
| Tax | 상시 | 하베스팅·장기 전환·워시세일 | ❌ v1 학습 제외 (별도 목적함수) |

의견 스키마 (JSON Schema로 강제):

```json
{
  "ticker": "AAPL",
  "direction": "buy | hold | sell | trim | add",
  "confidence": 0.0,   // "이 종목이 timeframe 동안 SPY를 이길(sell이면 밑돌) 확률"로 명시적 유도
  "timeframe": "days | weeks | months | quarters",
  "rationale": "…",
  "ref_source_ids": [1, 4],
  "suggested_size_pct": null
}
```

- confidence는 막연한 확신도가 아니라 **채점될 사건의 확률**로 프롬프트에서 유도한다 — 그래야 Brier가 proper score가 된다.
- **후보 유니버스 명시**: v1 = 현재 보유 종목 + 리서치 인제스천이 표면화한 종목. 매 run의 유니버스 구성원을 기록한다 (이게 없으면 학습 루프가 보유 종목만 영원히 채점한다).
- **워시세일 검증은 코드 레벨** (LLM 판단 금지). 규칙:
  - **손실 매도에만** 적용 (이익 매도 61일 창 플래그는 오탐 스팸).
  - 매도 전후 각 30일 = **61일 창**, 실질적 동일 증권, **전 계좌 합산(IRA·배우자 계좌 포함)**.
  - 과세 계좌 워시세일 → 불허 손실은 **대체 랏 기초가액에 가산 + 보유 기간 승계** (랏 데이터에 반영, 아니면 이후 세금 계산이 전부 틀어진다).
  - **IRA에서 재매수 시 손실 영구 소멸** — 일반 플래그보다 강한 경고로 처리.

### [4] 오케스트레이터

- 입력: 5개 의견 + 에이전트 가중치 + 소스 가중치. 출력: 최종 조언 + 가상 결정 레코드.
- **명시적 규칙(코드) 우선, LLM은 종합 서술 담당** (재현성):
  - 시간축 충돌: Daily=SELL + Tax="14일 후 장기 전환" → "14일 홀드 후 재평가".
  - Risk Agent는 거부권: 집중도/변동성 한도 초과 시 buy/add 차단.
- 구현은 그래프 프레임워크 없이 **잡 스크립트 3개**(`run_ingest` / `run_advise` / `run_evaluate`) + `runs` 테이블이 상태. 실제 설계 포인트는:
  - LLM 호출별 재시도(백오프), 에이전트 부분 실패 정책(5개 중 4개로 진행 vs 중단 — 기본: Risk/Tax 실패 시 중단, 나머지는 결측 표기 후 진행).
  - 프롬프트·모델 버전을 `runs`에 기록 (재현성).
- 출력 2종:
  1. **일일 조언 리포트** — 이메일(Resend 무료 티어) 발송 + `reports` 테이블 저장. **리포에 커밋하지 않는다.** CI 로그에도 보유·랏 payload를 출력하지 않는다.
  2. **가상 결정 레코드** — `orchestrator_decisions` + 당일 종가/수정종가 스냅샷.

### [5] 시뮬레이션 & 학습 루프

4장에서 상세 설계. 핵심: 실제 자금 미투입, **다음 거래일 시가 체결**의 페이퍼 트레이딩, 시계별 채점, 에이전트·소스 가중치의 보수적 갱신.

---

## 2. 데이터 모델 v2 (Supabase / Postgres)

실 마이그레이션에서는 모든 테이블에 FK·NOT NULL·CHECK(`qty > 0`, `confidence BETWEEN 0 AND 1` 등)를 건다. 아래는 요약.

```sql
-- 시장 데이터 (채점·뷰의 조인 대상은 항상 이 테이블)
prices             (ticker, trade_date, close, adj_close, volume,
                    PRIMARY KEY (ticker, trade_date))
trading_sessions   (trade_date PRIMARY KEY, is_open bool)            -- NYSE 캘린더 캐시

-- 소스 및 인제스천 (JSONB는 아카이브 전용)
sources            (id, name, type, url, credibility_prior numeric, created_at)
source_weights     (id, source_id, ticker nullable,                  -- 종목 단위, 표본 부족 시 소스 평균 폴백
                    weight numeric, sample_n int, effective_from)    -- append-only
daily_ingest       (id, source_id, ticker nullable, kind,            -- price|fundamental|research|macro
                    payload jsonb, trade_date, ingested_at)

-- 포트폴리오 (랏이 원본, holdings는 뷰)
accounts           (id, name, broker, tax_type,                      -- taxable|ira (워시세일 합산·IRA 규칙용)
                    owner)                                           -- self|spouse
tax_lots           (id, account_id, ticker, qty, cost_basis,
                    acquired_at date,
                    wash_sale_adjusted bool default false)           -- 잔여 수량 = qty − Σ realized_events.qty
lot_adjustments    (id, lot_id, kind,                                -- split|spinoff|return_of_capital|correction
                    ratio, note, applied_at)                         -- 현금 배당은 여기 아님
cash_events        (id, account_id, ticker nullable, kind,           -- dividend|interest|deposit|withdrawal
                    amount, occurred_at)                             -- DRIP 매수는 새 tax_lots 행
realized_events    (id, lot_id, qty, sold_at, proceeds, gain,
                    term,                                            -- short|long
                    wash_sale bool default false)
-- view: holdings   = open qty > 0 인 랏을 ticker별 집계
-- view: tax_status = 랏별 days_to_longterm, unrealized_pnl (prices 조인)

-- 에이전트 및 결정 (전 단계 멱등: INSERT ... ON CONFLICT)
runs               (id, run_date UNIQUE, status, prompt_version,
                    model_id, started_at, finished_at)
run_universe       (run_id, ticker, origin)                          -- holding|research
agent_opinions     (id, run_id, agent, ticker, direction,
                    confidence, timeframe, rationale,
                    ref_source_ids int[], suggested_size_pct,
                    UNIQUE (run_id, agent, ticker))
orchestrator_decisions
                   (id, run_id, ticker, action, combined_rationale,
                    confidence,
                    price_at_decision, adj_price_at_decision,        -- 당일 종가 스냅샷 (채점 기준점)
                    benchmark_adj_price numeric,                     -- SPY 수정종가
                    UNIQUE (run_id, ticker))

-- 시뮬레이션 및 학습
sim_trades         (id, decision_id, fill_date, fill_price, qty)     -- 다음 거래일 시가 체결
-- 가상 포지션·NAV는 sim_trades + cash_events에서 파생
sim_evaluations    (id, opinion_id nullable, decision_id nullable,   -- ★ 에이전트별 채점 지원
                    horizon,                                         -- 1d|5d|21d|63d (거래일 기준)
                    eval_trade_date, actual_return, benchmark_return,
                    excess_return, brier nullable, hit nullable,
                    status,                                          -- scored|unresolved|terminal
                    UNIQUE (opinion_id, decision_id, horizon))
agent_weights      (id, agent, weight, sample_n, n_eff numeric,
                    effective_from)                                  -- append-only
reports            (id, run_id, body_md, sent_at)
```

메모:
- **평가 잡은 날짜 산술이 아니라 결측 스캔으로 구동**: "N번째 후속 거래 세션이 이미 인제스트된 결정 중 평가 행이 없는 것"을 찾아 upsert → 실행이 며칠 밀려도 자동 캐치업, 재실행해도 중복 없음.
- 상폐·인수합병 종결 규칙: 인수 → 딜 가격, 상폐/파산 → 최종 체결가(≈0). 조용히 누락하지 않고 `status='terminal'`로 기록 (생존 편향 방지).
- 보안: 서비스 롤 키는 GitHub Actions Secrets에만. **RLS는 서비스 키 경로를 막지 못하므로** 실제 통제는 (a) anon 키 비노출, (b) 시크릿 관리, (c) CI 로그에 보유 데이터 미출력. RLS + Supabase Auth 정책 설계는 대시보드(6단계)의 선행 조건.

---

## 3. 기술 스택 (확정안)

| 구성요소 | 선택 | 이유 |
|----------|------|------|
| 언어 | Python 3.12 (uv) | 데이터/퀀트 생태계 |
| 오케스트레이션 | 플레인 Python 잡 3개 + `runs` 상태 | 사이클 없는 일일 배치. LangGraph는 과함 |
| LLM | Claude API `claude-sonnet-5` (구조화 출력) | 하루 6~7콜 수준, 소액. 프롬프트·모델 버전 기록 |
| 스토리지 | Supabase (Postgres) | 무료 티어로 충분 |
| 스케줄러 | GitHub Actions: `30 0,1 * * 2-6` (UTC) + `workflow_dispatch` | 두 슬롯 + 세션 가드로 DST·휴장 일괄 해결. 수동 재실행 지원 |
| 리포트 | 이메일(Resend) + `reports` 테이블 | 리포 커밋 금지 |
| 데이터 어댑터 | `adapters/` — fidelity_activity, prices(yf + stooq 폴백), fred, research_rss | 소스 교체 = 어댑터 1개 |

GitHub Actions 운영 주의:
- 스케줄 실행은 best-effort (15~60분 지연, 간혹 스킵) → 모든 잡 멱등 + 캐치업 필수 (스키마가 이를 보장).
- **60일간 커밋 없는 리포는 스케줄 자동 비활성** → keep-alive 커밋 또는 캘린더 리마인더.

레포 구조(안):

```
quant-pm/
├── adapters/          # fidelity_activity.py, prices_yf.py, prices_stooq.py, fred.py, research_rss.py
├── agents/            # daily_signal.py, fundamental.py, allocation.py, risk.py, tax.py
│   └── prompts/
├── core/              # trade_date.py, orchestrator.py, conflict_rules.py, wash_sale.py, scoring.py
├── db/                # migrations/ (번호 SQL + Supabase CLI), client.py
├── jobs/              # ingest_portfolio.py(로컬), run_ingest.py, run_advise.py, run_evaluate.py
├── tests/             # wash_sale, scoring, trade_date — 순수 함수 단위 테스트
└── .github/workflows/ # daily.yml
```

---

## 4. 평가·학습 루프 설계

### 페이퍼 체결 (룩어헤드 금지)

- 결정은 당일 종가 데이터 기반, **체결은 다음 거래일 시가** (`sim_trades.fill_price`). 당일 종가 체결은 존재하지 않았던 기회를 채점하는 것.
- `price_at_decision`은 체결가가 아니라 **채점 기준점**으로만 사용.
- 가상 포트폴리오는 실보유 복제본에서 시작, 슬리피지 0 가정(v1). 주간 리포트에 가상 장부 vs 실보유 vs SPY 3선 비교.

### 채점 (매 거래일, 결측 스캔 방식)

- **의견 단위 + 결정 단위 모두 채점.** 가중치 학습은 의견 단위가 원천 (오케스트레이터가 에이전트와 반대로 갈 수 있으므로).
- **시계**: 1d/5d/21d/63d — 전부 **거래일** 기준 (금요일 결정의 1d는 월요일).
- **수익률**: 자체 저장 `adj_close` 시계열로만 계산 (종목·SPY 모두 총수익 기준 — 한쪽만 총수익이면 매년 ~1.3% 가짜 초과수익 발생).
- **방향 적중(hit)**: `excess = 종목수익 − SPY수익` 기준.
  - buy/add → excess > 0, sell/trim → excess < 0.
  - hold → |excess| < **호라이즌 스케일 밴드** `±1% × √(h/1일)` (고정 ±1%는 21d에서 hold가 거의 무조건 miss가 되어 에이전트가 hold를 회피하게 학습된다).
- **Brier**: `(confidence − hit)²`. 단, **의견의 timeframe과 일치하는 시계에서만 가중치에 반영** (days/weeks→5d, months→21d, quarters→63d). 나머지 시계는 진단용. 한 확신도를 세 시계에 모두 채점하면 상관된 표본으로 가중치가 오염된다.
- **Tax·Risk 제외**: 방향 예측이 아니므로 Brier 부적용. v1은 학습 없음, v2에서 자체 목적함수(실현 세금 절감 vs 단순 랏 선택, 거부권이 회피한 드로다운) 검토.

### 가중치 업데이트 (소표본·자기상관 과잉반응 방지)

```
raw_skill  = 1 − mean(brier)                          # timeframe 일치 평가만
n_eff      = n / horizon_days                          # 겹치는 윈도우 보정 (일일 결정 × 21d 채점은 ~21배 중복)
posterior  = (prior_n × prior_skill + n_eff × raw_skill) / (prior_n + n_eff)
new_weight = EMA(α=0.1) of posterior
```

- 에이전트 가중치: 에이전트 단위. 소스 가중치: **소스 × 종목** 단위, 표본 부족 시 소스 평균 폴백.
- n_eff < 30이면 가중치 변경 폭 제한. 모든 갱신은 append-only (감사·롤백 가능).
- 가중치는 오케스트레이터의 **참고 입력**일 뿐 강제 규칙이 아니다 (원안 원칙 유지).

---

## 5. 개발 순서

| 단계 | 산출물 | 완료 기준 |
|------|--------|-----------|
| **1. 스키마 + 어댑터** | 마이그레이션(제약 포함), `trade_date` 코어 함수, prices 인제스트(yf+폴백), 랏 수동 시딩 + Activity CSV 로컬 인제스트, 세션 가드 워크플로 | 실제 랏이 DB에 있고 매일 가격이 쌓인다. 채점 정의(4장)는 이 단계에서 코드·테스트로 확정 |
| **2. 에이전트 3개** | Daily / Allocation / Tax + 워시세일 검증 함수(테스트 포함) | 3개 에이전트가 구조화 의견을 DB에 기록 |
| **3. 오케스트레이터** | 충돌 규칙 + 종합, 부분 실패 정책, 이메일 리포트 | 매일 아침 조언 리포트 도착 |
| **4. 시뮬레이션 기록** | sim_trades(다음 시가 체결), 스냅샷 | 결정이 페이퍼 트레이드로 기록 |
| **5. 평가 + 학습** | 결측 스캔 채점(1d/5d/21d/63d), Brier, n_eff 수축 가중치 | 주 단위로 가중치가 데이터 기반으로 움직인다 |
| **6. 확장** | Fundamental·Risk 에이전트, 소스 확장, (선택) Netlify 대시보드 (RLS+Auth 설계 선행) | — |

각 단계는 독립 배포 가능. 단계 1이 끝나는 순간부터 실제 데이터가 흐른다.

---

## 6. 리스크 & 주의점

- **면책 고지**: 모든 리포트 하단에 "정보 제공용, 투자 자문 아님" 삽입.
- **Fidelity**: 공식 개인 API 없음. 랏 시딩은 수동 1회 + Activity CSV 유지보수. 업로드 지연 시 "상태 최신일" 표시로 완화.
- **워시세일**: 손실 매도 한정, 61일 창, 전 계좌(IRA·배우자) 합산, 기초가액 가산 + 보유기간 승계, IRA 재매수 = 영구 소멸. 전부 코드 + 단위 테스트.
- **데이터 라이선스**: 유료 소스 스크레이핑 금지. yfinance는 비공식(ToS-그레이) — 개인용 v1로 한정하고 폴백 어댑터 유지.
- **학습 루프 과적합**: n_eff 수축 + EMA + timeframe 일치 채점. 그래도 초기 몇 달은 가중치를 "참고 표시"만 하고 오케스트레이터 반영 강도를 낮게.
- **데이터 유출 방지**: 보유·랏·CSV를 git에 커밋 금지, CI 로그 출력 금지, 리포트는 이메일/DB로만.
- **LLM 비용·재현성**: 하루 6~7콜 소액. 프롬프트·모델 버전을 `runs`에 기록.
