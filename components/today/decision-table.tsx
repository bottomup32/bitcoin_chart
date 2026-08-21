"use client";

import { ActionBadge, ConfidenceBar } from "@/components/shared";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Decision } from "@/lib/types";
import { usd } from "@/lib/utils";

/** Rule codes come from core/conflict_rules.py — spelling them out here keeps
 *  the screen readable without the reader holding the rulebook in their head. */
const RULE_LABEL: Record<string, string> = {
  R1: "Risk veto",
  T1: "Long-term deferral",
  T2: "Wash-sale block",
  T3: "Harvest nudge",
};

export function DecisionTable({ decisions }: { decisions: Decision[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="pl-5">Ticker</TableHead>
          <TableHead>Action</TableHead>
          <TableHead>Confidence</TableHead>
          <TableHead className="hidden xl:table-cell">Rules</TableHead>
          <TableHead className="hidden text-right lg:table-cell">Close at decision</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {decisions.map((d) => (
          <TableRow key={d.ticker} className="align-top">
            <TableCell className="pl-5 pt-3">
              <div className="ta-label-1">{d.ticker}</div>
              <p className="mt-1 max-w-md ta-caption-1 leading-relaxed text-muted-foreground">
                {d.rationale}
              </p>
            </TableCell>
            <TableCell className="pt-3">
              <ActionBadge action={d.action} />
              {d.revisitDays !== null && (
                <div className="mt-1 ta-caption-1 text-muted-foreground tabular-nums">
                  revisit in {d.revisitDays}d
                </div>
              )}
            </TableCell>
            <TableCell className="pt-3">
              <ConfidenceBar value={d.confidence} />
            </TableCell>
            <TableCell className="hidden pt-3 xl:table-cell">
              {d.rulesApplied.length ? (
                <div className="flex flex-wrap gap-1">
                  {d.rulesApplied.map((r) => (
                    <Badge key={r} variant="caution">{RULE_LABEL[r] ?? r}</Badge>
                  ))}
                </div>
              ) : (
                <span className="ta-caption-1 text-muted-foreground">—</span>
              )}
            </TableCell>
            <TableCell className="hidden pt-3 text-right lg:table-cell">
              <span className="ta-numeric text-[13px] tabular-nums">
                {usd(d.priceAtDecision)}
              </span>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
