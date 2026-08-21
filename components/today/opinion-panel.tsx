"use client";

import { useState } from "react";
import { BookOpen } from "lucide-react";

import { ChartCard, ConfidenceBar } from "@/components/shared";
import { ActionBadge } from "@/components/shared";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { AgentName, Opinion } from "@/lib/types";
import { cn } from "@/lib/utils";

const AGENT_LABEL: Record<AgentName, string> = {
  daily_signal: "Daily signal",
  allocation: "Allocation",
  risk: "Risk",
  tax: "Tax",
  fundamental: "Fundamental",
};

/** risk and tax are deliberately excluded from Brier scoring (PLAN.md §4) —
 *  a tax sale is not a market prediction — so the screen says so rather than
 *  letting the reader assume every agent is graded the same way. */
const UNSCORED: AgentName[] = ["risk", "tax"];

export function OpinionPanel({ opinions }: { opinions: Opinion[] }) {
  const agents = Array.from(new Set(opinions.map((o) => o.agent)));
  const [active, setActive] = useState<string>("all");
  const shown = active === "all" ? opinions : opinions.filter((o) => o.agent === active);

  return (
    <ChartCard
      title="Agent opinions"
      description="Each agent votes independently; the orchestrator combines them by learned weight."
      action={
        <Tabs value={active} onValueChange={setActive}>
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            {agents.map((a) => (
              <TabsTrigger key={a} value={a}>{AGENT_LABEL[a]}</TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      }
    >
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {shown.map((o, i) => (
          <div key={`${o.agent}-${o.ticker}-${i}`}
            className="rounded-lg border p-4 transition-colors duration-150 hover:bg-accent">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="ta-label-1">{o.ticker}</span>
                <ActionBadge action={o.direction} />
              </div>
              <Badge variant="neutral">{o.timeframe}</Badge>
            </div>

            <div className="mt-3">
              <ConfidenceBar value={o.confidence} />
            </div>

            <p className="mt-3 ta-caption-1 leading-relaxed text-muted-foreground">
              {o.rationale}
            </p>

            <div className="mt-3 flex items-center justify-between gap-2">
              <span className={cn("ta-caption-1",
                UNSCORED.includes(o.agent) ? "text-muted-foreground" : "text-primary")}>
                {AGENT_LABEL[o.agent]}
                {UNSCORED.includes(o.agent) && " · not scored on direction"}
              </span>
              {o.usedKnowledge.length > 0 && (
                <span className="flex items-center gap-1 ta-caption-1 text-muted-foreground">
                  <BookOpen className="size-3" />
                  cited {o.usedKnowledge.length}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </ChartCard>
  );
}
