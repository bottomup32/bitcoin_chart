/** Sample data so the UI renders before Supabase is wired up.
 *  Shapes match lib/types.ts exactly, so swapping in real queries is a
 *  drop-in change. Numbers are illustrative, not real market data. */

import type {
  AgentWeightPoint, DailyBrief, EvaluationPoint, KnowledgeChunk, Lesson,
  LlmCallDay, Position, RecentCall, RunRow, TaxLot,
} from "./types";

const SESSION = "2026-08-07";

export const mockBrief: DailyBrief = {
  session: SESSION,
  status: "succeeded",
  narrative:
    "오늘 유니버스는 보유 3종목과 관찰 1종목입니다. Daily Signal은 NVDA의 21일 초과수익이 SPY를 8.1%p 앞선다고 봤고, Risk는 NVDA 비중이 31%로 집중도 한도를 넘었다고 판단해 축소를 권고했습니다. 두 의견이 충돌해 규칙 R1(리스크 거부권)이 매수를 차단했고 최종 결정은 비중 축소입니다. TSLA는 장기보유 전환까지 12일 남아 규칙 T1로 홀드가 유지됩니다.",
  decisions: [
    { ticker: "NVDA", action: "trim", confidence: 0.64,
      rationale: "risk: trim (0.72); daily_signal: buy (0.68); R1 risk veto blocks add → trim",
      rulesApplied: ["R1"], revisitDays: null, priceAtDecision: 178.42 },
    { ticker: "TSLA", action: "hold", confidence: 0.58,
      rationale: "allocation: add (0.61); T1 long-term transition in 12 days → hold",
      rulesApplied: ["T1"], revisitDays: 12, priceAtDecision: 342.15 },
    { ticker: "MSFT", action: "hold", confidence: 0.55,
      rationale: "daily_signal: hold (0.57); allocation: hold (0.54); weighted vote +0.04 → hold",
      rulesApplied: [], revisitDays: null, priceAtDecision: 512.88 },
    { ticker: "PLTR", action: "buy", confidence: 0.61,
      rationale: "daily_signal: buy (0.63); allocation: buy (0.58); weighted vote +0.42 → buy",
      rulesApplied: [], revisitDays: null, priceAtDecision: 84.30 },
  ],
  opinions: [
    { agent: "daily_signal", ticker: "NVDA", direction: "buy", confidence: 0.68, timeframe: "weeks",
      rationale: "21일 수익률이 SPY를 8.1%p 상회하고 거래량이 5일 평균 대비 1.3배입니다. 63일 고점 대비 -2.1%로 추세 훼손 신호는 없습니다.",
      usedKnowledge: [2] },
    { agent: "daily_signal", ticker: "TSLA", direction: "hold", confidence: 0.55, timeframe: "days",
      rationale: "5일 초과수익 +0.4%p로 방향성이 약합니다. 연율 변동성 58%가 높아 확신도를 낮게 잡습니다.", usedKnowledge: [] },
    { agent: "daily_signal", ticker: "MSFT", direction: "hold", confidence: 0.57, timeframe: "days",
      rationale: "지표가 전반적으로 중립입니다. 21일 초과수익 -0.6%p는 밴드 안입니다.", usedKnowledge: [] },
    { agent: "daily_signal", ticker: "PLTR", direction: "buy", confidence: 0.63, timeframe: "weeks",
      rationale: "5일·21일 초과수익이 모두 양수이고 거래량이 늘었습니다.", usedKnowledge: [] },
    { agent: "allocation", ticker: "NVDA", direction: "trim", confidence: 0.60, timeframe: "months",
      rationale: "비중 31%는 단일 포지션 한도 20%를 크게 넘습니다. 추세와 무관하게 사이즈 조정이 필요합니다.",
      usedKnowledge: [1] },
    { agent: "allocation", ticker: "TSLA", direction: "add", confidence: 0.61, timeframe: "months",
      rationale: "비중 14%로 여력이 있고 중기 추세가 벤치마크를 앞섭니다.", usedKnowledge: [] },
    { agent: "allocation", ticker: "MSFT", direction: "hold", confidence: 0.54, timeframe: "quarters",
      rationale: "비중 22%로 상한 근처지만 변동성이 낮아 즉각 조정 필요는 낮습니다.", usedKnowledge: [] },
    { agent: "risk", ticker: "NVDA", direction: "trim", confidence: 0.72, timeframe: "weeks",
      rationale: "비중 31%에 연율 변동성 52%, TSLA와 63일 상관 0.81입니다. 두 포지션이 사실상 하나의 큰 베팅으로 움직입니다.",
      usedKnowledge: [1, 3] },
    { agent: "risk", ticker: "TSLA", direction: "hold", confidence: 0.58, timeframe: "weeks",
      rationale: "변동성은 높지만 비중 14%로 관리 가능한 범위입니다.", usedKnowledge: [] },
    { agent: "tax", ticker: "TSLA", direction: "hold", confidence: 0.70, timeframe: "days",
      rationale: "장기 전환까지 12일 남았고 미실현 이익이 있습니다. 지금 매도하면 단기 세율이 적용됩니다.", usedKnowledge: [] },
    { agent: "tax", ticker: "PLTR", direction: "hold", confidence: 0.65, timeframe: "days",
      rationale: "미실현 손실이 있으나 30일 내 매수 기록이 있어 워시세일에 걸립니다. 손실 실현을 보류합니다.", usedKnowledge: [] },
  ],
  taxAlerts: {
    washSaleRisk: { PLTR: "wash sale if sold at a loss now (recent purchase in window)" },
    transitions: [{ ticker: "TSLA", days: 12 }, { ticker: "MSFT", days: 38 }],
    realizedYtd: { short: 1240.5, long: 3180.2 },
  },
  news: [
    { ticker: "NVDA", title: "Nvidia lifts data-center outlook after supply constraints ease",
      summary: "The company said capacity additions should support shipments through the next two quarters.",
      url: "#", publishedAt: SESSION },
    { ticker: "NVDA", title: "Analyst raises price target citing accelerator demand",
      summary: "Target lifted following channel checks.", url: "#", publishedAt: "2026-08-06" },
    { ticker: "TSLA", title: "Deliveries land in line with guidance",
      summary: "Quarterly deliveries matched the company's prior range.", url: "#", publishedAt: SESSION },
    { ticker: "PLTR", title: "New government contract announced",
      summary: "Multi-year award covering analytics deployment.", url: "#", publishedAt: "2026-08-05" },
  ],
  portfolioValue: 128_450.32,
  portfolioDayChange: 0.0184,
  costToday: { inputTokens: 9_240, outputTokens: 2_180, usd: 0.0604 },
};

export const mockPositions: Position[] = [
  { ticker: "NVDA", qty: 224, avgCost: 121.4, lastClose: 178.42, marketValue: 39_966.08, weightPct: 31.1, unrealizedPnl: 12_772.48 },
  { ticker: "MSFT", qty: 55, avgCost: 431.2, lastClose: 512.88, marketValue: 28_208.4, weightPct: 22.0, unrealizedPnl: 4_492.4 },
  { ticker: "TSLA", qty: 52, avgCost: 298.7, lastClose: 342.15, marketValue: 17_791.8, weightPct: 13.9, unrealizedPnl: 2_259.4 },
  { ticker: "PLTR", qty: 190, avgCost: 91.2, lastClose: 84.3, marketValue: 16_017.0, weightPct: 12.5, unrealizedPnl: -1_311.0 },
];

export const mockLots: TaxLot[] = [
  { ticker: "NVDA", lotId: "L-0012", openQty: 120, costBasis: 98.4, acquiredAt: "2024-11-18", daysToLongterm: 0, unrealizedPnl: 9_602.4, accountTaxType: "taxable" },
  { ticker: "NVDA", lotId: "L-0031", openQty: 104, costBasis: 147.9, acquiredAt: "2026-03-02", daysToLongterm: 208, unrealizedPnl: 3_170.08, accountTaxType: "taxable" },
  { ticker: "MSFT", lotId: "L-0019", openQty: 55, costBasis: 431.2, acquiredAt: "2025-07-01", daysToLongterm: 38, unrealizedPnl: 4_492.4, accountTaxType: "taxable" },
  { ticker: "TSLA", lotId: "L-0024", openQty: 52, costBasis: 298.7, acquiredAt: "2025-08-19", daysToLongterm: 12, unrealizedPnl: 2_259.4, accountTaxType: "taxable" },
  { ticker: "PLTR", lotId: "L-0040", openQty: 190, costBasis: 91.2, acquiredAt: "2026-07-14", daysToLongterm: 341, unrealizedPnl: -1_311.0, accountTaxType: "taxable" },
];

const days = (n: number) =>
  Array.from({ length: n }, (_, i) => {
    const d = new Date("2026-08-07");
    d.setDate(d.getDate() - (n - 1 - i));
    return d.toISOString().slice(0, 10);
  });

export const mockWeights: AgentWeightPoint[] = days(30).flatMap((asOf, i) => [
  { agent: "daily_signal" as const, weight: 0.5 + Math.sin(i / 6) * 0.035 + i * 0.0015, nEff: 2 + i * 0.18, sampleN: 10 + i * 2, asOf },
  { agent: "allocation" as const, weight: 0.5 - Math.sin(i / 5) * 0.028 + i * 0.0008, nEff: 1.6 + i * 0.15, sampleN: 8 + i * 2, asOf },
]);

export const mockEvaluations: EvaluationPoint[] = days(30).flatMap((evalDate, i) => [
  { evalDate, agent: "daily_signal" as const, horizon: "5d" as const,
    hitRate: 0.5 + Math.sin(i / 4) * 0.14, meanExcess: Math.sin(i / 3) * 0.012, n: 2 },
  { evalDate, agent: "allocation" as const, horizon: "21d" as const,
    hitRate: 0.5 + Math.cos(i / 5) * 0.11, meanExcess: Math.cos(i / 4) * 0.009, n: 2 },
]);

export const mockLessons: Lesson[] = [
  { agent: "daily_signal", ticker: "NVDA", tier: "provisional",
    body: "daily_signal / NVDA: your bullish calls cleared the benchmark bar 8 of 11 times. Stated confidence has averaged 0.68 against a 0.73 rate you actually achieved. (n_eff 2.2 — below the evidence bar; treat as weak.)",
    n: 11, nEff: 2.2, asOf: "2026-08-06" },
  { agent: "allocation", ticker: null, tier: "provisional",
    body: "allocation: your hold calls cleared the benchmark bar 6 of 14 times. Stated confidence has averaged 0.59 against a 0.43 rate you actually achieved. (n_eff 2.8 — below the evidence bar; treat as weak.)",
    n: 14, nEff: 2.8, asOf: "2026-08-05" },
];

export const mockChunks: KnowledgeChunk[] = [
  { id: 1, sourceId: 3, sourceName: "Howard Marks memos",
    body: "Never let one position dominate the book. Above roughly a fifth of capital, the question stops being conviction and starts being survival.",
    kind: "heuristic", horizons: [], agents: [], tags: ["concentration", "position_sizing"],
    layer: "situational", approved: true, shownCount: 42, citedCount: 11 },
  { id: 2, sourceId: 3, sourceName: "Howard Marks memos",
    body: "In a drawdown with elevated volatility, ask whether price fell more than value. If so, reduce sizing rather than exiting.",
    kind: "principle", horizons: ["weeks", "months"], agents: [], tags: ["drawdown", "high_volatility"],
    layer: "situational", approved: true, shownCount: 38, citedCount: 6 },
  { id: 3, sourceId: 4, sourceName: "Ray Dalio — principles",
    body: "Correlated positions are one position wearing several names. Count exposures by driver, not by ticker.",
    kind: "caution", horizons: [], agents: ["risk", "allocation"], tags: ["correlation", "concentration"],
    layer: "situational", approved: true, shownCount: 22, citedCount: 9 },
  { id: 4, sourceId: 5, sourceName: "Peter Lynch — One Up on Wall Street",
    body: "Our favourite holding period is long. Short-term price action is noise against the underlying business trajectory.",
    kind: "principle", horizons: ["months", "quarters"], agents: [], tags: ["time_horizon"],
    layer: "situational", approved: true, shownCount: 14, citedCount: 2 },
  { id: 5, sourceId: 4, sourceName: "Ray Dalio — principles",
    body: "Risk is the permanent loss of capital, not the wiggle of a price chart.",
    kind: "principle", horizons: [], agents: [], tags: [], layer: "core",
    approved: true, shownCount: 0, citedCount: 0 },
  { id: 6, sourceId: 5, sourceName: "Peter Lynch — One Up on Wall Street",
    body: "When a thesis rests on a story rather than a number you can check, size it as entertainment.",
    kind: "caution", horizons: [], agents: [], tags: ["position_sizing"],
    layer: "situational", approved: false, shownCount: 0, citedCount: 0 },
];

export const mockCosts: LlmCallDay[] = days(21).map((runDate, i) => ({
  runDate,
  calls: 5,
  failedCalls: i === 12 ? 1 : 0,
  inputTokens: 7_800 + Math.round(Math.sin(i / 3) * 900) + i * 60,
  outputTokens: 1_900 + Math.round(Math.cos(i / 4) * 260),
  cacheReadTokens: i > 9 ? 3_400 : 0,
  estKnowledgeTokens: i > 6 ? 900 + i * 12 : 0,
  estShortTermTokens: i > 2 ? 700 + i * 8 : 0,
  estLongTermTokens: i > 14 ? 240 : 0,
}));

export const mockRuns: RunRow[] = days(10).reverse().map((runDate, i) => ({
  runDate,
  status: i === 3 ? "failed" : "succeeded",
  promptVersion: "v1",
  modelId: "claude-sonnet-5",
  startedAt: `${runDate}T01:12:04Z`,
  finishedAt: `${runDate}T01:13:38Z`,
}));

export const mockRecentCalls: RecentCall[] = [
  { ticker: "NVDA", agent: "daily_signal", sessionsAgo: 1, direction: "buy", confidence: 0.68, excess: null, hit: null, orchestratorAction: "trim" },
  { ticker: "NVDA", agent: "daily_signal", sessionsAgo: 2, direction: "buy", confidence: 0.65, excess: null, hit: null, orchestratorAction: "hold" },
  { ticker: "NVDA", agent: "daily_signal", sessionsAgo: 6, direction: "hold", confidence: 0.55, excess: 0.0121, hit: true, orchestratorAction: "hold" },
  { ticker: "NVDA", agent: "daily_signal", sessionsAgo: 7, direction: "buy", confidence: 0.71, excess: -0.0043, hit: false, orchestratorAction: "add" },
  { ticker: "TSLA", agent: "daily_signal", sessionsAgo: 1, direction: "hold", confidence: 0.55, excess: null, hit: null, orchestratorAction: "hold" },
  { ticker: "TSLA", agent: "daily_signal", sessionsAgo: 6, direction: "buy", confidence: 0.62, excess: 0.0087, hit: true, orchestratorAction: "hold" },
];

export const mockWatchlist = ["NVDA", "MSFT", "TSLA", "PLTR"];
