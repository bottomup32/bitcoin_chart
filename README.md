# quant-pm — 퀀트 멀티 에이전트 포트폴리오 매니저

개인 주식 포트폴리오를 위한 멀티 에이전트 자문 시스템.
설계 전체는 [PLAN.md](PLAN.md) 참조. 현재 **1~5단계 + Risk 에이전트까지 구현 완료** —
클로즈드 루프(수집 → 분석 → 결정 → 리포트 → 페이퍼 체결 → 채점 → 가중치 학습)가 전부 돌아간다.

> ⚠️ **면책**: 이 시스템은 정보 제공용이며 투자 자문이 아닙니다. 모든 투자 결정과 그 결과는
> 사용자 본인의 책임입니다.

## 현재 동작하는 것

**1단계 — 데이터 기반:**

- Supabase(Postgres) 스키마 마이그레이션 (랏 중심 데이터 모델, PLAN.md §2)
- NYSE 세션 계산 코어 (`core/trade_date.py`) — 모든 잡의 날짜 기준점
- 채점 수학 확정 (`core/scoring.py`) — 초과수익 hit, hold 밴드, Brier, n_eff 수축
- 일일 가격 인제스트 (`jobs/run_ingest.py`) — yfinance 1차, Stooq 폴백, 멱등 업서트
- 로컬 포트폴리오 CLI (`jobs/ingest_portfolio.py`) — 랏 시딩 + Fidelity Activity CSV
- GitHub Actions 스케줄 (`.github/workflows/daily.yml`) — UTC 2슬롯 + 세션 가드

**2단계 — 분석 에이전트:**

- 분석 에이전트 3개 (`agents/`) — Daily Signal(단기), Allocation(중장기), Tax(세금).
  Claude API 구조화 출력(Pydantic 스키마 강제)으로 `agent_opinions`에 기록
- 워시세일 검증 (`core/wash_sale.py`) — 61일 창, 전 계좌(IRA 포함) 합산, 손실 매도 한정,
  기초가액 가산 + 보유기간 승계, IRA 재매수 영구 소멸. 전부 코드 + 단위 테스트,
  Activity CSV 인제스트 시 자동 스캔 (`wash-scan` 서브커맨드로 수동 실행도 가능)
- 기술 지표 계산 (`core/indicators.py`) — 에이전트는 코드가 계산한 숫자만 읽음
- 일일 advise 잡 (`jobs/run_advise.py`) — 세션 가드 → 유니버스 기록 → 에이전트 3개 실행.
  Tax 실패는 중단, 나머지는 결측 표기 후 진행 (PLAN.md 부분 실패 정책)

**3단계 — 오케스트레이터 + 리포트:**

- 충돌 조율 규칙 (`core/conflict_rules.py`) — 코드로 결정, LLM은 서술만:
  가중 투표(방향×확신도×에이전트 가중치) + T1 장기전환 유예("매도 표결이어도 N일 후
  장기 세율이면 홀드 후 재평가") + T2 워시세일 차단 + T3 하베스트 넛지
- 결정 스냅샷 (`core/orchestrator.py`) — `orchestrator_decisions`에 당일 종가·수정종가·SPY
  스냅샷과 함께 저장 (채점 기준점, 룩어헤드 금지)
- 일일 리포트 (`core/report.py`) — 한국어 마크다운: 최종 결정 테이블, 워시세일 경고,
  장기전환 임박, 에이전트 의견 상세, 면책 고지. LLM 요약(선택)은 실패해도 리포트는 발행
- 이메일 발송 (`adapters/resend_email.py`) — Resend 무료 티어, 미설정 시 DB 저장만

**4~5단계 — 시뮬레이션 + 학습 루프 (`jobs/run_evaluate.py`):**

- 페이퍼 체결 — hold 이외의 결정을 **다음 거래일 시가**로 체결 (`sim_trades`, 룩어헤드 금지).
  매도=전량, 축소=절반, 신규 매수=포트폴리오 5%, 확대=+25% (`core/simulation.py`)
- 채점 — 결측 스캔 방식: 자체 저장 `adj_close` 시계열로 1d/5d/21d/63d 시계별
  SPY 대비 초과수익 hit + Brier. Brier는 의견의 timeframe과 일치하는 시계에서만
  가중치에 반영, 나머지는 진단용. Tax·Risk는 방향 채점에서 제외 (PLAN.md §4)
- 가중치 학습 — 에이전트별 Brier → n_eff(겹침 보정) 베이지안 수축 → EMA.
  n_eff < 30이면 변경 폭 ±0.05 제한, append-only 이력. **새 평가가 있을 때만 갱신**
- 실행이 밀려도 자동 캐치업 (모든 패스가 멱등 + 결측 스캔)

**6단계 (일부) — Risk 에이전트:**

- `agents/risk.py` — 집중도·변동성·드로다운·63일 상관행렬(코드 계산)을 읽는 거부권 역할.
  오케스트레이터 규칙 R1: Risk가 trim/sell이면 buy/add 표결을 홀드로 차단

## 셋업

### 1. Supabase

1. [supabase.com](https://supabase.com)에서 프로젝트 생성 (무료 티어).
2. Settings → Database에서 **Connection string (URI)** 복사 (Direct connection, 비밀번호 포함).

### 2. 로컬

```bash
uv sync                                   # https://docs.astral.sh/uv/
export SUPABASE_DB_URL='postgresql://...' # .env에 저장해도 됨 (git 제외됨)

uv run python -m jobs.apply_migrations    # 스키마 생성
uv run pytest                             # 전부 통과해야 정상
```

### 3. 계좌·보유 랏 입력 (로컬에서만)

보유 데이터는 **절대 git에 커밋하지 않는다** — CSV·`data/`는 .gitignore에 있음.

```bash
uv run python -m jobs.ingest_portfolio account-add --name brokerage --tax-type taxable

# 최초 1회: Fidelity 웹의 포지션별 랏 상세 화면을 보고 CSV 작성
# (Positions CSV에는 랏 정보가 없음 — PLAN.md §0)
# lots.csv: account,ticker,qty,cost_basis,acquired_at   (cost_basis = 주당, 날짜 YYYY-MM-DD)
uv run python -m jobs.ingest_portfolio seed-lots lots.csv

# 이후 유지보수: Fidelity Activity/History CSV 다운로드 후
uv run python -m jobs.ingest_portfolio activity Activity.csv --account brokerage
```

### 4. GitHub Actions

리포 Settings에서:

- **Secrets** → `SUPABASE_DB_URL` = 위 연결 문자열
- **Secrets** → `ANTHROPIC_API_KEY` = Claude API 키 (없으면 에이전트 단계는 자동 스킵)
- **Variables** (선택) → `WATCHLIST` = `NVDA,MSFT,...` (보유 외 추적 종목)
- **Variables** (선택) → `MODEL_ID` = 에이전트 모델 오버라이드 (기본 `claude-sonnet-5`)
- **Secrets** (선택) → `RESEND_API_KEY` + **Variables** `REPORT_EMAIL_TO` = 일일 리포트 이메일
  수신 설정 (없으면 리포트는 `reports` 테이블에만 저장)

이후 평일 미국장 마감 후 자동으로 가격이 쌓인다. Actions 탭에서 `daily` 워크플로를
`workflow_dispatch`로 수동 실행해 첫 백필을 트리거할 수 있다.

## 남은 확장 (PLAN.md §5 6단계)

- **Fundamental 에이전트** — SEC EDGAR / FMP 펀더멘털 인제스트 어댑터가 선행 조건
  (데이터 없이 켜면 환각 위험이라 의도적으로 보류; 투표·채점 배선은 이미 준비됨)
- **매크로·리서치 소스** — FRED, VIX, 리서치 RSS 어댑터 + 소스×종목 가중치 학습
- **주간 리포트** — 가상 장부 vs 실보유 vs SPY 3선 누적 비교
- **대시보드** — Netlify + Supabase RLS/Auth 설계 선행
