---
target: "https://bitcoin-chart-murex.vercel.app/"
total_score: 22
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 3
timestamp: 2026-08-21T15-08-28Z
slug: bitcoin-chart-murex-vercel-app
---
# Quant PM (bitcoin-chart-murex.vercel.app) 디자인 크리틱

Method: dual-agent (A: design review · B: detector/browser evidence)

**평가 방식 주석**: 샌드박스 프록시가 vercel.app 접속을 차단(CONNECT 403)하여, 동일 커밋 소스를 로컬 빌드/서빙(샘플 데이터 모드 — 배포본과 동일한 no-Supabase 상태)해 헤드리스 Chromium(1440×900, 390×844)으로 검증함. CDN 폰트(Pretendard/Poppins)는 프록시 차단으로 폴백 렌더링.

## Design Health Score: 22/40 (Acceptable)

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | 상태 배지·스켈레톤 양호, 런 피드백은 토스트뿐이고 failed 런에 상세 없음 |
| 2 | Match System / Real World | 2 | 파이프라인 원시 용어 노출(n_eff, Brier, snake_case 에이전트명), 내러티브 "규칙 R1" vs 테이블 "Risk veto" 이중 표기 |
| 3 | User Control and Freedom | 2 | Memory Discard가 확인/undo 없이 영구 삭제, 런 취소 불가 |
| 4 | Consistency and Standards | 2 | 동일 라벨 "Run now" 두 개가 다르게 동작(하나는 404, 하나는 가짜 성공 토스트), 죽은 버튼 다수 |
| 5 | Error Prevention | 2 | 티커 입력 검증 없음, 비가역 Discard 무확인 |
| 6 | Recognition Rather Than Recall | 3 | 룰 배지·캡션 우수, "cited 1"이 클릭 불가라 /memory에서 수동 대조 필요 |
| 7 | Flexibility and Efficiency | 1 | 단축키·검색·정렬·일괄승인·내보내기 전무, 필터 상태 URL 미반영 |
| 8 | Aesthetic and Minimalist Design | 3 | 절제된 시스템, 다만 Today 페이지가 길고 마무리 없이 끝남 |
| 9 | Error Recovery | 1 | 주요 CTA 실패 시 "Check the function logs." 개발자 메시지, 재시도 경로 없음 |
| 10 | Help and Documentation | 3 | 카드 설명이 메커니즘을 잘 가르침, 온보딩/용어 툴팁은 없음 |
| **Total** | | **22/40** | **Acceptable (20–27)** |

## Design Specificity Verdict

**LLM 평가**: 콘텐츠 설계(도메인 카피, 룰 번역, 에이전트 내러티브)는 명백히 이 제품 고유 — 희소한 수준의 고급 도메인 라이팅. 그러나 비주얼은 TecAce 표준 스킨 + 전형적 shadcn 대시보드 문법으로 카테고리 교체 가능. 최대 격차는 언어 정체성: `<html lang="ko">`·한국어 내러티브 vs 영어 크롬/라벨/테이블.

**결정론적 스캔**: CLI 디텍터 2건(side-tab: app/page.tsx:78, app/learning/page.tsx:32 — 런타임 재확인됨). 브라우저 주입 디텍터: `/`에서 nested-cards ×11, line-length ×1(면책 문구 ~148자/줄), /learning에서 line-length ×3, nested-cards ×2. gradient-text·layout-transition 전 라우트 검출은 Next dev 오버레이 아티팩트로 오탐 판정. 앱 발생 JS 에러/하이드레이션 경고/4xx는 0건(폰트 CDN 프록시 차단 제외).

**시각 오버레이**: 헤드리스 원격 세션이라 사용자 브라우저 오버레이 표시는 불가(폴백: 헤드리스 주입 실행으로 대체).

## Priority Issues

1. **[P0] 모바일 내비게이션 부재** — app-sidebar.tsx:26 `hidden md:flex`, 햄버거/시트/바텀탭 없음. 768px 미만에서 5개 페이지가 고립됨. Fix: Sheet 드로어 또는 5-item 바텀 탭바. (/impeccable adapt)
2. **[P1] 주요 액션 "Run now" 이중 고장** — Today는 존재하지 않는 /api/run 호출 후 개발자용 에러 토스트, Ops는 요청 없이 가짜 success 토스트. Fix: 공용 런 액션, 샘플 모드에선 비활성+툴팁, 실패 시 인간적 메시지+재시도. (/impeccable harden)
3. **[P1] WCAG 대비 실패(돈 색상)** — success #0abe5c ≈2.5:1, warning #e18a0f ≈2.7:1, muted-foreground ≈3.7:1(지배적 캡션 색). Fix: 텍스트용 변형 토큰 도입. (/impeccable colorize)
4. **[P1] 390px에서 Agent opinions 카드 헤더 붕괴** — 6-트리거 TabsList가 타이틀을 한 단어씩 줄바꿈시킴. Fix: md 미만 수직 스택 + 탭 가로 스크롤. (/impeccable adapt)
5. **[P2] 샘플 데이터 정합성 붕괴** — 홈 $128.5K vs 포트폴리오 합계 $101,983(mock.ts:74 하드코딩), 내러티브 "보유 3종목" vs 실제 4종목, 21개 런 전부 01:13:38 종료. Fix: 모든 집계를 동일 mock 포지션에서 파생. (/impeccable harden)

## Persona Red Flags

**Alex (파워 유저)**: 단축키 전무, "cited 1" 클릭 불가, 테이블 정렬/failed 필터/CSV 내보내기 없음, 필터 상태 URL 미반영으로 매일 재클릭.

**Sam (접근성)**: 사이드바 링크 포커스 표시가 UA 기본 헤어라인뿐, 스킵 링크 없음, canvas 차트 4종 aria-label 없음(스크린리더에 무음), Ops 스위치 2개 접근성 이름 없음(+아이콘 전용 Plus 버튼), lang="ko"인데 본문 80% 영어로 한국어 스크린리더 오발성.

**Casey (모바일)**: 내비게이션 자체가 불가(P0), Positions/Tax lots 테이블이 중간에 잘리는데 스크롤 단서 없음. Ops의 `hidden lg:table-cell` 패턴은 좋으나 다른 곳에 미적용.

## Minor Observations

- Sonner 토스터 다크모드 미동기화(다크 UI 위 흰 토스트)
- "Sample data" 배지가 실제 리스크 배지와 동일한 caution 스타일 — 경고색 의미 희석
- Learning KPI 타이틀이 raw 키 소문자("daily signal") vs Title Case 혼재
- 행 hover 상태는 있는데 클릭 가능한 것이 없음(암시된 어포던스 무보상)
- 도넛 중앙 62% 공백 — 총액 표기 기회
- Decisions "Rules" 컬럼이 1024–1280px에서 대체재 없이 사라짐(제품 차별점인 거부권이 소실)
- 홈 "Cost today $0.060" vs Ops "Cost per session $0.054" 유사 스탯 라벨/값 불일치
- $0.060 3소수 통화 표기
- 에이전트 가중치 y축 0.4–0.6 고정으로 ±0.05 흔들림 과장

## Questions to Consider

1. 룰 파이프라인이 제품인데 왜 산문인가? 결정 행 확장 시 votes → weighted merge → veto → outcome 그래픽이 데모·신뢰·차별화 순간이 될 수 있다.
2. 독자는 누구이고 어떤 언어인가? 한국어 개인투자자라면 크롬·레슨·세금 설명까지 한국어로 커밋할 것.
3. 사용자는 결정으로 무엇을 하는가? "trim NVDA" 다음 단계(체크리스트/주문 티켓/완료 표시)가 없어 추천이 사용용이 아니라는 신호를 준다.
