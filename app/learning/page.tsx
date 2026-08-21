"use client";

import { Info } from "lucide-react";

import { ChartCard, PageHeader, StatCard } from "@/components/shared";
import { ClientChart } from "@/components/charts/client-chart";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { mockEvaluations, mockLessons, mockWeights } from "@/lib/mock";
import { pct } from "@/lib/utils";

/** Same constant as jobs/run_evaluate.py:MIN_N_EFF — below it, nothing is
 *  treated as evidence. Surfacing it stops the charts reading as conclusions. */
const MIN_N_EFF = 30;

export default function LearningPage() {
  const latest = new Map(
    mockWeights.map((w) => [w.agent, w] as const) // last write per agent wins
  );
  const agents = Array.from(latest.values());
  const maxNEff = Math.max(...agents.map((a) => a.nEff));
  const dates = Array.from(new Set(mockWeights.map((w) => w.asOf)));

  return (
    <>
      <PageHeader
        title="Learning"
        subtitle="Opinions are scored against SPY, shrunk by effective sample size, then folded into agent weights."
      />

      <Card className="rounded-xl border-l-2 border-l-warning shadow-none">
        <CardContent className="flex gap-3 px-5 py-4">
          <Info className="mt-0.5 size-4 shrink-0 text-warning" />
          <p className="ta-body-2 text-[--label-neutral]">
            Effective sample size is still under {MIN_N_EFF}, so every weight below is
            dominated by its prior rather than by evidence. Overlapping evaluation windows
            inflate the raw count — 5-day horizons overlap fivefold — which is why n_eff, not n,
            gates the learning. Read these as accumulating, not as conclusions.
          </p>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        {agents.map((a) => (
          <StatCard key={a.agent}
            title={a.agent.replace("_", " ")}
            value={a.weight.toFixed(3)}
            caption={`n_eff ${a.nEff.toFixed(1)} of ${MIN_N_EFF} · n ${a.sampleN}`}
          />
        ))}
        <StatCard title="Evidence progress"
          value={`${Math.round((maxNEff / MIN_N_EFF) * 100)}%`}
          caption="Best agent's n_eff against the evidence bar" />
        <StatCard title="Lessons written" value={String(mockLessons.length)}
          caption={`${mockLessons.filter((l) => l.tier === "established").length} established`} />
      </div>

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-3 md:gap-6">
        <ChartCard className="lg:col-span-2" title="Agent weights"
          description="Append-only; each point is a new row, and a weight only moves when the sample actually changes.">
          <ClientChart kind="line" height={280}
            data={(t) => ({
              labels: dates,
              datasets: Array.from(new Set(mockWeights.map((w) => w.agent))).map((agent, i) => ({
                label: agent.replace("_", " "),
                data: mockWeights.filter((w) => w.agent === agent).map((w) => w.weight),
                borderColor: t.colors[i],
                backgroundColor: t.colors[i] + "1F",
                tension: 0.35, borderWidth: 2, pointRadius: 0, fill: false,
              })),
            })}
            options={{
              maintainAspectRatio: false,
              scales: {
                y: { min: 0.4, max: 0.6, ticks: { stepSize: 0.05 } },
                x: { ticks: { maxTicksLimit: 8 } },
              },
              plugins: { legend: { position: "bottom" } },
            }}
          />
        </ChartCard>

        <ChartCard title="Evidence accrual" description={`Progress toward n_eff ${MIN_N_EFF}`}>
          <div className="space-y-5">
            {agents.map((a) => (
              <div key={a.agent}>
                <div className="mb-2 flex items-center justify-between">
                  <span className="ta-label-1">{a.agent.replace("_", " ")}</span>
                  <span className="ta-numeric text-[13px] tabular-nums text-muted-foreground">
                    {a.nEff.toFixed(1)} / {MIN_N_EFF}
                  </span>
                </div>
                <Progress value={(a.nEff / MIN_N_EFF) * 100} />
              </div>
            ))}
            <p className="ta-caption-1 text-muted-foreground">
              At roughly two scorable opinions a day, the 5-day horizon needs about 75 sessions
              to clear the bar.
            </p>
          </div>
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2 md:gap-6">
        <ChartCard title="Hit rate" description="Share of calls that cleared the benchmark-relative bar">
          <ClientChart kind="line" height={240}
            data={(t) => ({
              labels: Array.from(new Set(mockEvaluations.map((e) => e.evalDate))),
              datasets: Array.from(new Set(mockEvaluations.map((e) => e.agent))).map((agent, i) => ({
                label: agent.replace("_", " "),
                data: mockEvaluations.filter((e) => e.agent === agent).map((e) => e.hitRate),
                borderColor: t.colors[i],
                backgroundColor: t.colors[i] + "1F",
                tension: 0.35, borderWidth: 2, pointRadius: 0, fill: true,
              })),
            })}
            options={{
              maintainAspectRatio: false,
              scales: { y: { min: 0.2, max: 0.8 }, x: { ticks: { maxTicksLimit: 6 } } },
              plugins: { legend: { position: "bottom" } },
            }}
          />
        </ChartCard>

        <ChartCard title="Lessons"
          description="Written by a template from code-computed statistics — no LLM call.">
          <div className="space-y-3">
            {mockLessons.map((l, i) => (
              <div key={i} className="rounded-lg border p-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="ta-label-1">
                    {l.agent.replace("_", " ")}{l.ticker ? ` · ${l.ticker}` : ""}
                  </span>
                  <Badge variant={l.tier === "established" ? "positive" : "caution"}>
                    {l.tier}
                  </Badge>
                </div>
                <p className="mt-2 ta-caption-1 leading-relaxed text-muted-foreground">{l.body}</p>
                <div className="mt-2 ta-caption-1 tabular-nums text-muted-foreground">
                  n {l.n} · n_eff {l.nEff} · as of {l.asOf}
                </div>
              </div>
            ))}
            <p className="ta-caption-1 text-muted-foreground">
              Agents see outcomes, never their own Brier score. Showing a proper scoring rule
              to the thing being scored turns it into a target.
            </p>
          </div>
        </ChartCard>
      </div>
    </>
  );
}
