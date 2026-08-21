"use client";

import { useState } from "react";
import { Play, Plus, X } from "lucide-react";
import { toast } from "sonner";

import { ChartCard, PageHeader, StatCard } from "@/components/shared";
import { ClientChart } from "@/components/charts/client-chart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { mockCosts, mockRuns, mockWatchlist } from "@/lib/mock";
import { usd } from "@/lib/utils";

// Sonnet 5 list price, USD per million tokens. Output bills at 5x input, which
// is why the chart splits the two rather than showing a single token count.
const IN_PRICE = 3.0, OUT_PRICE = 15.0, CACHE_READ = 0.1;

function dayCost(d: (typeof mockCosts)[number]) {
  return (d.inputTokens * IN_PRICE
    + d.cacheReadTokens * IN_PRICE * CACHE_READ
    + d.outputTokens * OUT_PRICE) / 1_000_000;
}

export default function OpsPage() {
  const [watchlist, setWatchlist] = useState(mockWatchlist);
  const [draft, setDraft] = useState("");
  const [memoryOn, setMemoryOn] = useState(true);
  const [newsOn, setNewsOn] = useState(true);

  const monthCost = mockCosts.reduce((s, d) => s + dayCost(d), 0);
  const perDay = monthCost / mockCosts.length;
  const failed = mockCosts.reduce((s, d) => s + d.failedCalls, 0);

  function addTicker() {
    const t = draft.trim().toUpperCase();
    if (!t) return;
    if (watchlist.includes(t)) { toast.error(`${t} is already on the watchlist.`); return; }
    setWatchlist([...watchlist, t]);
    setDraft("");
    toast.success(`${t} added. It joins the universe on the next run.`);
  }

  return (
    <>
      <PageHeader
        title="Operations"
        subtitle="Runs, cost, and what the pipeline looks at."
        actions={<Button onClick={() => toast.success("Run started.")}>
          <Play className="size-4" />Run now
        </Button>}
      />

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatCard title="Cost per session" value={usd(perDay, 3)}
          caption={`~${usd(perDay * 21, 2)} per month at 21 sessions`} />
        <StatCard title="Last 21 sessions" value={usd(monthCost, 2)}
          caption={`${mockCosts.reduce((s, d) => s + d.calls, 0)} calls`} />
        <StatCard title="Failed calls" value={String(failed)}
          caption="Refusals and timeouts still cost input tokens" />
        <StatCard title="Universe" value={String(watchlist.length)}
          caption="Holdings plus watchlist, benchmark excluded" />
      </div>

      <ChartCard title="Token spend by session"
        description="Output bills at five times input, so a rising output bar means rationales are getting longer — the regression worth watching.">
        <ClientChart kind="bar" height={260}
          data={(t) => ({
            labels: mockCosts.map((d) => d.runDate.slice(5)),
            datasets: [
              { label: "Input", data: mockCosts.map((d) => d.inputTokens),
                backgroundColor: t.colors[0], borderRadius: 4, stack: "a" },
              { label: "Cache read", data: mockCosts.map((d) => d.cacheReadTokens),
                backgroundColor: t.colors[1], borderRadius: 4, stack: "a" },
              { label: "Output", data: mockCosts.map((d) => d.outputTokens),
                backgroundColor: t.colors[6], borderRadius: 4, stack: "a" },
            ],
          })}
          options={{
            maintainAspectRatio: false,
            scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true } },
            plugins: { legend: { position: "bottom" } },
          }}
        />
      </ChartCard>

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-3 md:gap-6">
        <ChartCard className="lg:col-span-2" title="Recent runs"
          description="Each job is idempotent and missing-scan driven, so a failed day catches up on the next run."
          bodyClassName="px-0 pb-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-5">Session</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden lg:table-cell">Model</TableHead>
                <TableHead className="hidden xl:table-cell">Prompt</TableHead>
                <TableHead className="pr-5 text-right">Finished</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {mockRuns.map((r) => (
                <TableRow key={r.runDate}>
                  <TableCell className="pl-5 tabular-nums">{r.runDate}</TableCell>
                  <TableCell>
                    <Badge variant={r.status === "succeeded" ? "positive"
                      : r.status === "failed" ? "negative" : "caution"}>
                      {r.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="hidden text-muted-foreground lg:table-cell">{r.modelId}</TableCell>
                  <TableCell className="hidden text-muted-foreground xl:table-cell">{r.promptVersion}</TableCell>
                  <TableCell className="pr-5 text-right tabular-nums text-muted-foreground">
                    {r.finishedAt?.slice(11, 19) ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ChartCard>

        <div className="space-y-4 md:space-y-6">
          <ChartCard title="Watchlist" description="Tickers analysed alongside your holdings">
            <div className="flex gap-2">
              <Input value={draft} onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addTicker()}
                placeholder="Add ticker" className="h-9" />
              <Button size="sm" className="h-9" onClick={addTicker}>
                <Plus className="size-4" />
              </Button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {watchlist.map((t) => (
                <Badge key={t} variant="neutral" className="gap-1 py-1 pl-2.5 pr-1.5">
                  {t}
                  <button aria-label={`Remove ${t}`}
                    onClick={() => setWatchlist(watchlist.filter((x) => x !== t))}
                    className="rounded-full p-0.5 transition-colors duration-150 hover:bg-background">
                    <X className="size-3" />
                  </button>
                </Badge>
              ))}
            </div>
          </ChartCard>

          <ChartCard title="Pipeline" description="Takes effect on the next run">
            <div className="space-y-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="ta-label-1">Memory</p>
                  <p className="ta-caption-1 text-muted-foreground">
                    Recent calls, lessons, and endorsed principles in the prompt.
                  </p>
                </div>
                <Switch checked={memoryOn} onCheckedChange={setMemoryOn} />
              </div>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="ta-label-1">News</p>
                  <p className="ta-caption-1 text-muted-foreground">
                    Per-ticker RSS headlines, filtered to the session.
                  </p>
                </div>
                <Switch checked={newsOn} onCheckedChange={setNewsOn} />
              </div>
            </div>
          </ChartCard>
        </div>
      </div>
    </>
  );
}
