"use client";

import { ChartCard, PageHeader, StatCard } from "@/components/shared";
import { ClientChart } from "@/components/charts/client-chart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { mockBrief, mockLots, mockPositions } from "@/lib/mock";
import { cn, pct, usd } from "@/lib/utils";
import { Upload } from "lucide-react";

const CONCENTRATION_LIMIT = 20;

export default function PortfolioPage() {
  const total = mockPositions.reduce((s, p) => s + (p.marketValue ?? 0), 0);
  const unrealized = mockPositions.reduce((s, p) => s + (p.unrealizedPnl ?? 0), 0);
  const overweight = mockPositions.filter((p) => (p.weightPct ?? 0) >= CONCENTRATION_LIMIT);
  const { washSaleRisk, realizedYtd } = mockBrief.taxAlerts;

  return (
    <>
      <PageHeader
        title="Portfolio"
        subtitle="Tax lots are the source of truth; holdings and tax status are views over them."
        actions={<Button variant="outline"><Upload className="size-4" />Import activity CSV</Button>}
      />

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatCard title="Market value" value={usd(total, 0)} caption={`${mockPositions.length} positions`} />
        <StatCard title="Unrealized P&L" value={usd(unrealized, 0)}
          delta={pct(unrealized / (total - unrealized))} up={unrealized >= 0}
          caption="Across all open lots" />
        <StatCard title="Over concentration limit" value={String(overweight.length)}
          caption={overweight.length ? overweight.map((p) => p.ticker).join(", ") : `All under ${CONCENTRATION_LIMIT}%`} />
        <StatCard title="Realized YTD" value={usd(realizedYtd.short + realizedYtd.long, 0)}
          caption={`${usd(realizedYtd.short, 0)} short · ${usd(realizedYtd.long, 0)} long`} />
      </div>

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-3 md:gap-6">
        <ChartCard className="lg:col-span-2" title="Positions"
          description="Weights above 20% are flagged; the risk agent treats that as a sizing question, not a conviction one."
          bodyClassName="px-0 pb-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-5">Ticker</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">Avg cost</TableHead>
                <TableHead className="text-right">Last</TableHead>
                <TableHead className="text-right">Value</TableHead>
                <TableHead className="text-right">Weight</TableHead>
                <TableHead className="pr-5 text-right">Unrealized</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {mockPositions.map((p) => (
                <TableRow key={p.ticker}>
                  <TableCell className="pl-5">{p.ticker}</TableCell>
                  <TableCell className="text-right tabular-nums">{p.qty}</TableCell>
                  <TableCell className="text-right tabular-nums">{usd(p.avgCost)}</TableCell>
                  <TableCell className="text-right tabular-nums">{usd(p.lastClose)}</TableCell>
                  <TableCell className="text-right tabular-nums">{usd(p.marketValue, 0)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    <span className={cn((p.weightPct ?? 0) >= CONCENTRATION_LIMIT && "text-warning")}>
                      {p.weightPct?.toFixed(1)}%
                    </span>
                  </TableCell>
                  <TableCell className={cn("pr-5 text-right tabular-nums",
                    (p.unrealizedPnl ?? 0) >= 0 ? "text-success" : "text-destructive")}>
                    {usd(p.unrealizedPnl, 0)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ChartCard>

        <ChartCard title="Allocation" description="Share of market value">
          <ClientChart kind="doughnut" height={240}
            data={(t) => ({
              labels: mockPositions.map((p) => p.ticker),
              datasets: [{
                data: mockPositions.map((p) => p.marketValue ?? 0),
                backgroundColor: t.colors.slice(0, mockPositions.length),
                borderWidth: 0,
              }],
            })}
            options={{
              maintainAspectRatio: false,
              cutout: "62%",
              plugins: { legend: { position: "bottom" } },
            }}
          />
        </ChartCard>
      </div>

      <ChartCard title="Tax lots"
        description="Long-term means held MORE than one year. days_to_longterm counts down to that."
        bodyClassName="px-0 pb-0">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pl-5">Ticker</TableHead>
              <TableHead>Lot</TableHead>
              <TableHead>Acquired</TableHead>
              <TableHead>Account</TableHead>
              <TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">Basis / sh</TableHead>
              <TableHead className="text-right">Unrealized</TableHead>
              <TableHead className="pr-5">Term</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {mockLots.map((l) => (
              <TableRow key={l.lotId}>
                <TableCell className="pl-5">
                  {l.ticker}
                  {washSaleRisk[l.ticker] && (
                    <Badge variant="negative" className="ml-2">wash sale</Badge>
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground">{l.lotId}</TableCell>
                <TableCell className="tabular-nums">{l.acquiredAt}</TableCell>
                <TableCell><Badge variant="neutral">{l.accountTaxType}</Badge></TableCell>
                <TableCell className="text-right tabular-nums">{l.openQty}</TableCell>
                <TableCell className="text-right tabular-nums">{usd(l.costBasis)}</TableCell>
                <TableCell className={cn("text-right tabular-nums",
                  (l.unrealizedPnl ?? 0) >= 0 ? "text-success" : "text-destructive")}>
                  {usd(l.unrealizedPnl, 0)}
                </TableCell>
                <TableCell className="pr-5">
                  {l.daysToLongterm === 0
                    ? <Badge variant="positive">long-term</Badge>
                    : l.daysToLongterm <= 45
                      ? <Badge variant="caution">{l.daysToLongterm}d to long-term</Badge>
                      : <span className="ta-caption-1 text-muted-foreground tabular-nums">{l.daysToLongterm}d</span>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </ChartCard>
    </>
  );
}
