"use client";

import { useState } from "react";
import { AlertTriangle, Newspaper, Play, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import { ChartCard, PageHeader, StatCard } from "@/components/shared";
import { DecisionTable } from "@/components/today/decision-table";
import { OpinionPanel } from "@/components/today/opinion-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { mockBrief } from "@/lib/mock";
import { compactUsd, pct, usd } from "@/lib/utils";

export default function TodayPage() {
  const brief = mockBrief;
  const [running, setRunning] = useState(false);

  const actionable = brief.decisions.filter((d) => d.action !== "hold");
  const vetoed = brief.decisions.filter((d) => d.rulesApplied.length > 0);

  async function runNow() {
    setRunning(true);
    try {
      const res = await fetch("/api/run", { method: "POST" });
      if (!res.ok) throw new Error(String(res.status));
      toast.success("Run started. Results appear when it finishes.");
    } catch {
      toast.error("Could not start the run. Check the function logs.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Today"
        subtitle={`Session ${brief.session} · ${brief.decisions.length} decisions · informational only`}
        actions={
          <Button onClick={runNow} disabled={running}>
            <Play className="size-4" />
            {running ? "Starting…" : "Run now"}
          </Button>
        }
      />

      {/* ② KPI row */}
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatCard
          title="Portfolio value"
          value={compactUsd(brief.portfolioValue)}
          delta={pct(brief.portfolioDayChange)}
          up={(brief.portfolioDayChange ?? 0) >= 0}
          caption="Marked at the session close"
        />
        <StatCard
          title="Actionable decisions"
          value={String(actionable.length)}
          caption={`${brief.decisions.length - actionable.length} hold · ${brief.decisions.length} total`}
        />
        <StatCard
          title="Rules fired"
          value={String(vetoed.length)}
          caption={vetoed.length ? vetoed.map((d) => d.rulesApplied.join(",")).join(" · ") : "No overrides today"}
        />
        <StatCard
          title="Cost today"
          value={usd(brief.costToday?.usd ?? 0, 3)}
          caption={`${(brief.costToday?.inputTokens ?? 0).toLocaleString()} in · ${(brief.costToday?.outputTokens ?? 0).toLocaleString()} out`}
        />
      </div>

      {/* ③ Narrative + decisions */}
      {brief.narrative && (
        <Card className="rounded-xl border-l-2 border-l-primary shadow-none">
          <CardContent className="px-5 py-4">
            <p className="ta-body-2 text-[--label-neutral]">{brief.narrative}</p>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-3 md:gap-6">
        <ChartCard
          className="lg:col-span-2"
          title="Decisions"
          description="Produced by deterministic rules, not by the model. Rationale shows the vote and any rule that overrode it."
          bodyClassName="px-0 pb-0"
        >
          <DecisionTable decisions={brief.decisions} />
        </ChartCard>

        <div className="space-y-4 md:space-y-6">
          <ChartCard
            title="Tax alerts"
            description="Computed in code from actual lots, never by the model"
          >
            <div className="space-y-4">
              {Object.entries(brief.taxAlerts.washSaleRisk).map(([ticker, msg]) => (
                <div key={ticker} className="flex gap-3">
                  <ShieldAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
                  <div className="min-w-0">
                    <p className="ta-label-1">{ticker} — wash sale</p>
                    <p className="ta-caption-1 text-muted-foreground">{msg}</p>
                  </div>
                </div>
              ))}
              {brief.taxAlerts.transitions.map((t) => (
                <div key={t.ticker} className="flex gap-3">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
                  <div className="min-w-0">
                    <p className="ta-label-1">
                      {t.ticker} — long-term in {t.days} days
                    </p>
                    <p className="ta-caption-1 text-muted-foreground">
                      Selling before then is taxed at the short-term rate.
                    </p>
                  </div>
                </div>
              ))}
              <Separator />
              <div className="flex items-center justify-between">
                <span className="ta-caption-1 text-muted-foreground">Realized YTD</span>
                <span className="ta-numeric text-[13px] tabular-nums">
                  {usd(brief.taxAlerts.realizedYtd.short, 0)} short ·{" "}
                  {usd(brief.taxAlerts.realizedYtd.long, 0)} long
                </span>
              </div>
            </div>
          </ChartCard>

          <ChartCard title="News" description="Headlines the agents saw, filtered to this session">
            <div className="space-y-4">
              {brief.news.slice(0, 4).map((n, i) => (
                <div key={i} className="flex gap-3">
                  <Newspaper className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">{n.ticker}</Badge>
                      <span className="ta-caption-1 text-muted-foreground tabular-nums">
                        {n.publishedAt === mockBrief.session ? "today" : n.publishedAt}
                      </span>
                    </div>
                    <p className="mt-1 ta-label-1 leading-snug">{n.title}</p>
                  </div>
                </div>
              ))}
            </div>
          </ChartCard>
        </div>
      </div>

      {/* ④ Agent opinions */}
      <OpinionPanel opinions={brief.opinions} />
    </>
  );
}
