# CLAUDE.md — quant-pm 작업 지침

개인 포트폴리오용 멀티 에이전트 퀀트 자문 시스템. 설계 원본은 [PLAN.md](PLAN.md),
현재 구현 범위는 [README.md](README.md)에 있다. **둘이 이 문서보다 우선한다** —
충돌하면 PLAN.md를 따르고, 이 문서를 고쳐라.

## 절대 규칙 (어기면 되돌릴 수 없다)

1. **포트폴리오 데이터는 절대 커밋하지 않는다.** 리포는 public이고 DB에는 실제 랏·기초가액·
   계좌 활동이 들어 있다. `*.csv`, `data/`, `.env`는 .gitignore에 있고 `git add -f`는
   PreToolUse 훅이 차단한다. 우회하지 말 것 (PLAN.md §6).
   저작권 우려가 있는 `knowledge/` 원문도 같은 취급이다 — DB에만 넣고 리포에는 두지 않는다.
2. **리포트·보유 내역을 stdout/CI 로그로 흘리지 않는다.** 리포트는 `reports` 테이블과
   이메일로만 나간다. 디버그 출력에 티커·수량·금액을 넣지 말 것.
3. **룩어헤드 금지.** 페이퍼 체결은 *다음 거래일 시가*, 채점 기준 스냅샷은 결정 당일 종가다.
   결정 시점에 존재하지 않았던 가격을 쓰는 코드는 조용한 버그가 아니라 시스템 무효화다.
   메모리도 같은 규칙 아래 있다 — 프롬프트에 들어가는 회상은 세션 거래일 이후 데이터를
   담을 수 없고, `core/memory.py`의 `assert_as_of()`가 런타임에 강제한다. 우회하지 말 것.
4. **결정은 코드가, 서술은 LLM이.** 매수/매도/홀드는 `core/conflict_rules.py`의 결정론적
   규칙이 정하고 LLM은 설명만 쓴다. 에이전트가 최종 결정을 내리도록 배선하지 말 것.
5. **에이전트는 코드가 계산한 숫자만 읽는다.** 지표·상관·워시세일·메모리 선별은 `core/`에서
   계산해 프롬프트에 넣는다. LLM에게 계산을 시키지 않는다 (환각 방지).
   에이전트는 자기 예측의 **결과(outcome)**를 보되 **점수(Brier)**는 보지 않는다 —
   점수를 보여주면 정확해지는 대신 잘 보이려 하게 된다 (`core/memory.py` 참조).
6. **모든 잡은 멱등이다.** 재실행·중복 슬롯·밀린 날 캐치업이 전부 안전해야 한다.
   새 잡이나 새 패스를 추가하면 결측 스캔 + 업서트 패턴을 유지하라.
7. **리포트 하단 면책 고지("정보 제공용, 투자 자문 아님")를 제거하지 않는다.**

## 레이아웃

| 경로 | 역할 |
|------|------|
리포에는 런타임이 둘 있다 — 파이썬 엔진(CI가 게이트한다)과 Next.js 대시보드.

**파이썬 엔진**

| 경로 | 역할 |
|------|------|
| `core/` | 순수 로직·수학. DB·네트워크 없음, 전부 단위 테스트 대상 |
| `agents/` | LLM 호출 4개 (daily_signal / allocation / tax / risk) + 에이전트별 메모리 조립 |
| `adapters/` | 외부 I/O — 가격(yfinance→Stooq 폴백), 뉴스 RSS, Fidelity Activity CSV, Resend 이메일 |
| `jobs/` | 진입점(`python -m jobs.*`). 세션 가드 → 인제스트 → advise → evaluate → reflect |
| `db/` | psycopg 커넥션 + `migrations/*.sql` (append-only, 번호순) |
| `tests/` | pytest. 외부 네트워크·DB 없이 전부 통과해야 한다 |

핵심 불변식이 사는 곳: `core/trade_date.py`(모든 날짜 기준), `core/scoring.py`(채점 수학),
`core/wash_sale.py`(61일 창 규칙), `core/conflict_rules.py`(T1/T2/T3/R1 규칙),
`core/memory.py`(as-of 룩어헤드 가드 + "에이전트는 결과를 보고 점수는 못 본다"),
`core/llm_log.py`(토큰 회계), `core/claude_cli.py`(구독 결제 경로 트랜스포트).

**대시보드 (Next.js 16 / React 19 / Tailwind v4)**

| 경로 | 역할 |
|------|------|
| `app/` | 라우트 5개 — Today / portfolio / learning / memory / ops |
| `components/` | `ui/`는 손으로 쓴 shadcn 프리미티브, 나머지는 화면별 컴포넌트 |
| `lib/` | Supabase 클라이언트(RLS), 타입, 차트 테마, 샘플 데이터 폴백 |

Next.js에는 **Node API 라우트를 두지 않는다** — 루트 `/api`는 Vercel의 파이썬 함수 몫이고
둘을 섞으면 `next dev`가 깨진다. 세금·채점·지표 로직을 TypeScript로 포팅하지 않는다
(테스트가 붙어 있는 쪽이 진실이다).

## 명령어

```bash
uv sync                 # 파이썬 의존성 (세션 시작 훅이 이미 실행한다)
uv run pytest           # 전체 테스트 — 커밋 전 필수, 네트워크 불필요
uv run ruff check .     # 린트 — 커밋 전 필수, CI가 같은 명령으로 게이트한다
uv run ruff check . --fix

npm install             # 대시보드 의존성 (세션 시작 훅이 이미 실행한다)
npm run lint            # app/·components/·lib/를 건드렸다면 필수
npm run build           # 배포 전 확인. CI에는 없다
```

`npm run lint`는 지금 **기준선이 깨져 있다** — `components/charts/client-chart.tsx:37`의
`react-hooks/set-state-in-effect` 오류 1건 + 미사용 변수 경고 2건. 대시보드를 고칠 때
이 3건을 정리하고 CI에 린트를 붙이면 좋지만, 무관한 작업의 PR을 넓히지는 말 것.
새로 만든 오류인지 기준선인지 헷갈리면 `git stash && npm run lint`로 비교한다.

`jobs.*` 실행은 실제 DB에 쓰거나 LLM 토큰을 쓴다. 그래서 권한 설정상 **매번 확인을 받는다**.
사용자가 명시적으로 시키지 않으면 돌리지 말 것:

```bash
uv run python -m jobs.apply_migrations   # 스키마 변경 (Supabase에 직접 쓴다)
uv run python -m jobs.run_ingest         # 가격·뉴스 수집
uv run python -m jobs.run_advise         # LLM 호출 — 토큰 또는 구독 쿼터 소모
uv run python -m jobs.run_evaluate       # 체결·채점·가중치 갱신
uv run python -m jobs.run_reflect        # 교훈 축약 (LLM 0회, DB 쓰기)
uv run python -m jobs.ingest_portfolio   # 로컬 전용 — 랏·Activity CSV
uv run python -m jobs.ingest_knowledge   # 로컬 전용 — 지식 코퍼스, LLM 비용 발생
uv run python -m jobs.show_report        # 리포트 출력/재발송 (보유 내역 노출 주의)
uv run python -m jobs.show_costs         # 토큰 지출 조회 (건수만, 내용 없음)
```

## 코드 컨벤션

- 주석·문서·리포트 문구는 한국어, 식별자와 커밋 메시지는 영어.
- 타입 힌트를 붙이고, 새 `core/` 로직에는 반드시 테스트를 함께 쓴다.
- 마이그레이션은 기존 파일을 고치지 말고 새 번호 파일을 추가한다 (`db/migrations/0003_*.sql`).
- 스키마 변경 시 PLAN.md §2의 데이터 모델도 같이 갱신한다.
- 실패 정책: Tax 에이전트 실패는 중단 사유, 나머지는 "결측" 표기 후 진행 (PLAN.md 부분 실패 정책).

## 환경 변수

**목록의 진실은 [.env.example](.env.example)이다** — 변수를 추가하면 거기부터 갱신한다.
`SUPABASE_DB_URL`(필수, Session pooler URI), `LLM_TRANSPORT`(`claude_cli`=구독 쿼터 결제,
미설정=`ANTHROPIC_API_KEY`로 토큰 과금), `WATCHLIST`, `MODEL_ID`, `RESEND_API_KEY`,
`REPORT_EMAIL_TO`, `REPORT_EMAIL_FROM`, 스위치 `MEMORY_ENABLED`·`MEMORY_SHORT_TERM_SESSIONS`·
`NEWS_ENABLED`, 대시보드용 `NEXT_PUBLIC_SUPABASE_URL`·`NEXT_PUBLIC_SUPABASE_ANON_KEY`.

세 곳에 나뉘어 산다: 로컬 `.env`(CLI), claude.ai 환경 설정(매일 Routine), Vercel(대시보드).
값은 절대 출력하거나 커밋하지 않는다.

## 하네스 (`.claude/`)

- `hooks/session-start.sh` — 원격 세션 시작 시 `uv sync --frozen` + `npm install`을 돌리고
  `.venv`를 PATH에 올린다. npm 실패는 경고만 남기고 넘어가므로(파이썬이 CI 게이트다),
  대시보드를 건드리기 전에 경고가 있었는지 확인할 것.
- `hooks/guard-portfolio-data.sh` — 포트폴리오·시크릿·지식 코퍼스 파일의 스테이징/커밋과
  `git add -f`를 차단한다. `.env.example`은 값이 없는 참조 파일이라 통과시킨다.
  **이 훅은 고치면 반드시 `.claude/hooks/test-guard.sh`를 돌린다** — 패턴이 넓으면
  `core/lots.py` 같은 소스 파일까지 막아 작업이 그 자리에서 멈춘다 (실제로 두 번 그랬다).
- `settings.json` — 위 훅 등록 + 읽기/테스트/빌드 명령 허용, `jobs.*`와 `npm run dev` 실행은
  확인, `.env*`·`data/`·`knowledge/` 읽기 차단.
  차단 규칙은 `.env.example`에도 걸리므로 내용을 봐야 하면 `git show HEAD:.env.example`을 쓴다.
