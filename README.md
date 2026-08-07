# quant-pm — 퀀트 멀티 에이전트 포트폴리오 매니저

개인 주식 포트폴리오를 위한 멀티 에이전트 자문 시스템.
설계 전체는 [PLAN.md](PLAN.md) 참조. 현재 **2단계(분석 에이전트 3개 + 워시세일 검증)** 구현 상태.

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

이후 평일 미국장 마감 후 자동으로 가격이 쌓인다. Actions 탭에서 `daily` 워크플로를
`workflow_dispatch`로 수동 실행해 첫 백필을 트리거할 수 있다.

## 다음 단계

PLAN.md §5의 로드맵:

3. 오케스트레이터 + 일일 이메일 리포트
4. 페이퍼 트레이딩 기록 (다음 시가 체결)
5. 평가·학습 루프 (결측 스캔 채점, 가중치 갱신)
6. Fundamental·Risk 에이전트, 소스 확장, 대시보드
