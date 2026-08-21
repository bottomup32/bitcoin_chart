/** Domain types mirroring db/migrations/*.sql. Kept hand-written rather than
 *  generated, so the shapes the UI actually needs stay obvious. */

export type Direction = "buy" | "hold" | "sell" | "trim" | "add";
export type Timeframe = "days" | "weeks" | "months" | "quarters";
export type Horizon = "1d" | "5d" | "21d" | "63d";
export type AgentName = "daily_signal" | "allocation" | "risk" | "tax" | "fundamental";

export interface Decision {
  ticker: string;
  action: Direction;
  confidence: number;
  rationale: string;
  rulesApplied: string[];
  revisitDays: number | null;
  priceAtDecision: number | null;
}

export interface Opinion {
  agent: AgentName;
  ticker: string;
  direction: Direction;
  confidence: number;
  timeframe: Timeframe;
  rationale: string;
  usedKnowledge: number[];
}

export interface Position {
  ticker: string;
  qty: number;
  avgCost: number;
  lastClose: number | null;
  marketValue: number | null;
  weightPct: number | null;
  unrealizedPnl: number | null;
}

export interface TaxLot {
  ticker: string;
  lotId: string;
  openQty: number;
  costBasis: number;
  acquiredAt: string;
  daysToLongterm: number;
  unrealizedPnl: number | null;
  accountTaxType: "taxable" | "ira" | "roth";
}

export interface TaxAlerts {
  washSaleRisk: Record<string, string>;
  transitions: { ticker: string; days: number }[];
  realizedYtd: { short: number; long: number };
}

export interface AgentWeightPoint {
  agent: AgentName;
  weight: number;
  nEff: number;
  sampleN: number;
  asOf: string;
}

export interface Lesson {
  agent: AgentName;
  ticker: string | null;
  tier: "provisional" | "established";
  body: string;
  n: number;
  nEff: number;
  asOf: string;
}

export interface EvaluationPoint {
  evalDate: string;
  agent: AgentName;
  horizon: Horizon;
  hitRate: number;
  meanExcess: number;
  n: number;
}

export interface NewsItem {
  ticker: string;
  title: string;
  summary: string;
  url: string | null;
  publishedAt: string;
}

export interface KnowledgeChunk {
  id: number;
  sourceId: number;
  sourceName: string;
  body: string;
  kind: "principle" | "heuristic" | "caution";
  horizons: Timeframe[];
  agents: AgentName[];
  tags: string[];
  layer: "core" | "situational";
  approved: boolean;
  shownCount: number;
  citedCount: number;
}

export interface LlmCallDay {
  runDate: string;
  calls: number;
  failedCalls: number;
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  estKnowledgeTokens: number;
  estShortTermTokens: number;
  estLongTermTokens: number;
}

export interface RunRow {
  runDate: string;
  status: "running" | "succeeded" | "failed";
  promptVersion: string | null;
  modelId: string | null;
  startedAt: string;
  finishedAt: string | null;
}

export interface RecentCall {
  ticker: string;
  agent: AgentName;
  sessionsAgo: number;
  direction: Direction;
  confidence: number;
  excess: number | null;
  hit: boolean | null;
  orchestratorAction: Direction | null;
}

/** Everything the Today page needs, in one shape. */
export interface DailyBrief {
  session: string;
  status: RunRow["status"];
  narrative: string | null;
  decisions: Decision[];
  opinions: Opinion[];
  taxAlerts: TaxAlerts;
  news: NewsItem[];
  portfolioValue: number | null;
  portfolioDayChange: number | null;
  costToday: { inputTokens: number; outputTokens: number; usd: number } | null;
}
