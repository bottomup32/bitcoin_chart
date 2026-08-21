"use client";

import { useState } from "react";
import { BookOpen, Check, Plus, X } from "lucide-react";
import { toast } from "sonner";

import { ChartCard, PageHeader, StatCard } from "@/components/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { mockChunks, mockLessons, mockRecentCalls } from "@/lib/mock";
import { cn, pct } from "@/lib/utils";

export default function MemoryPage() {
  const [chunks, setChunks] = useState(mockChunks);
  const live = chunks.filter((c) => c.approved);
  const pending = chunks.filter((c) => !c.approved);
  const core = live.filter((c) => c.layer === "core");
  const shown = live.reduce((s, c) => s + c.shownCount, 0);
  const cited = live.reduce((s, c) => s + c.citedCount, 0);
  const citationRate = shown ? cited / shown : 0;

  function decide(id: number, approved: boolean) {
    setChunks((prev) => approved
      ? prev.map((c) => (c.id === id ? { ...c, approved: true } : c))
      : prev.filter((c) => c.id !== id));
    toast.success(approved ? "Approved. It can now be retrieved." : "Discarded.");
  }

  return (
    <>
      <PageHeader
        title="Memory"
        subtitle="What each agent recalls, and the principles it is allowed to draw on."
      />

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatCard title="Live chunks" value={String(live.length)}
          caption={`${core.length} core · ${live.length - core.length} situational`} />
        <StatCard title="Awaiting review" value={String(pending.length)}
          caption="Nothing reaches a prompt until approved" />
        <StatCard title="Citation rate" value={pct(citationRate, 0)}
          caption={`${cited} cited of ${shown} shown`} />
        <StatCard title="Lessons" value={String(mockLessons.length)}
          caption="Long-term memory, template-written" />
      </div>

      <Tabs defaultValue="corpus">
        <TabsList className="h-9">
          <TabsTrigger value="corpus">Knowledge corpus</TabsTrigger>
          <TabsTrigger value="review">
            Review{pending.length > 0 && ` (${pending.length})`}
          </TabsTrigger>
          <TabsTrigger value="recall">Short-term recall</TabsTrigger>
        </TabsList>

        <TabsContent value="corpus" className="mt-4 space-y-4 md:mt-6 md:space-y-6">
          <ChartCard title="Approved principles"
            description="Retrieval matches tags against code-computed market state, so what an agent sees is deterministic and replayable."
            bodyClassName="px-0 pb-0"
            action={<Button variant="outline" size="sm"><Plus className="size-4" />Add source</Button>}>
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="pl-5">Principle</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead className="hidden xl:table-cell">Tags</TableHead>
                  <TableHead className="hidden lg:table-cell">Horizons</TableHead>
                  <TableHead className="pr-5 text-right">Shown / cited</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {live.map((c) => (
                  <TableRow key={c.id} className="align-top">
                    <TableCell className="max-w-md pl-5 pt-3">
                      <p className="leading-relaxed">{c.body}</p>
                      <div className="mt-1 flex items-center gap-2">
                        <Badge variant={c.layer === "core" ? "default" : "neutral"}>{c.layer}</Badge>
                        <span className="ta-caption-1 text-muted-foreground">{c.kind}</span>
                      </div>
                    </TableCell>
                    <TableCell className="pt-3 text-muted-foreground">{c.sourceName}</TableCell>
                    <TableCell className="hidden pt-3 xl:table-cell">
                      <div className="flex flex-wrap gap-1">
                        {c.tags.length
                          ? c.tags.map((t) => <Badge key={t} variant="outline">{t}</Badge>)
                          : <span className="ta-caption-1 text-muted-foreground">any</span>}
                      </div>
                    </TableCell>
                    <TableCell className="hidden pt-3 lg:table-cell">
                      <span className="ta-caption-1 text-muted-foreground">
                        {c.horizons.length ? c.horizons.join(", ") : "any"}
                      </span>
                    </TableCell>
                    <TableCell className="pr-5 pt-3 text-right tabular-nums">
                      {c.shownCount} / {c.citedCount}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ChartCard>
        </TabsContent>

        <TabsContent value="review" className="mt-4 space-y-4 md:mt-6">
          {pending.length === 0 ? (
            <ChartCard title="Review queue" description="Nothing waiting">
              <p className="ta-body-2 text-muted-foreground">
                Every drafted chunk has been reviewed. Add a document to draft more.
              </p>
            </ChartCard>
          ) : (
            pending.map((c) => (
              <ChartCard key={c.id} title={c.sourceName}
                description={`${c.kind} · drafted, not yet retrievable`}
                action={
                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" onClick={() => decide(c.id, false)}>
                      <X className="size-4" />Discard
                    </Button>
                    <Button size="sm" onClick={() => decide(c.id, true)}>
                      <Check className="size-4" />Approve
                    </Button>
                  </div>
                }>
                <p className="ta-body-2 leading-relaxed">{c.body}</p>
                <div className="mt-3 flex flex-wrap items-center gap-1">
                  {c.tags.map((t) => <Badge key={t} variant="outline">{t}</Badge>)}
                  <span className="ml-2 ta-caption-1 text-muted-foreground">
                    {c.horizons.length ? c.horizons.join(", ") : "any horizon"} ·{" "}
                    {c.agents.length ? c.agents.join(", ") : "all agents"} · {c.body.length}/400 chars
                  </span>
                </div>
              </ChartCard>
            ))
          )}
        </TabsContent>

        <TabsContent value="recall" className="mt-4 md:mt-6">
          <ChartCard title="What daily signal recalls"
            description="Its own prior calls and how they resolved. Unresolved rows are kept on purpose — those are the open positions."
            bodyClassName="px-0 pb-0">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="pl-5">Ticker</TableHead>
                  <TableHead className="text-right">Sessions ago</TableHead>
                  <TableHead>Its call</TableHead>
                  <TableHead className="text-right">Confidence</TableHead>
                  <TableHead className="text-right">Excess vs SPY</TableHead>
                  <TableHead>Outcome</TableHead>
                  <TableHead className="pr-5">Orchestrator</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {mockRecentCalls.map((r, i) => (
                  <TableRow key={i}>
                    <TableCell className="pl-5">{r.ticker}</TableCell>
                    <TableCell className="text-right tabular-nums">{r.sessionsAgo}</TableCell>
                    <TableCell><Badge variant="neutral">{r.direction}</Badge></TableCell>
                    <TableCell className="text-right tabular-nums">
                      {Math.round(r.confidence * 100)}%
                    </TableCell>
                    <TableCell className={cn("text-right tabular-nums",
                      r.excess === null ? "text-muted-foreground"
                        : r.excess >= 0 ? "text-success" : "text-destructive")}>
                      {r.excess === null ? "—" : pct(r.excess, 2)}
                    </TableCell>
                    <TableCell>
                      {r.hit === null
                        ? <Badge variant="neutral">still open</Badge>
                        : r.hit ? <Badge variant="positive">cleared</Badge>
                          : <Badge variant="negative">missed</Badge>}
                    </TableCell>
                    <TableCell className="pr-5 text-muted-foreground">
                      {r.orchestratorAction ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ChartCard>
        </TabsContent>
      </Tabs>
    </>
  );
}
