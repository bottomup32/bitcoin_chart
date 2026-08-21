"use client";

import { ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/* ---------- KPI card ---------- */
export function StatCard({ title, value, delta, up, caption, spark, className }: {
  title: string; value: string; delta?: string; up?: boolean; caption?: string;
  spark?: ReactNode; className?: string;
}) {
  return (
    <Card className={cn("rounded-xl border shadow-none", className)}>
      <CardContent className="px-5 py-4">
        <div className="flex items-center justify-between gap-2">
          <span className="ta-label-1 text-muted-foreground">{title}</span>
          {delta && (
            <Badge variant={up ? "positive" : "negative"} className="gap-0.5 px-1.5">
              {up ? <ArrowUpRight className="size-3" /> : <ArrowDownRight className="size-3" />}
              {delta}
            </Badge>
          )}
        </div>
        <div className="mt-2 flex items-end justify-between gap-3">
          <span className="ta-numeric text-[28px] leading-9">{value}</span>
          {spark && <div className="h-10 w-24 shrink-0">{spark}</div>}
        </div>
        {caption && <p className="mt-1 ta-caption-1 text-muted-foreground">{caption}</p>}
      </CardContent>
    </Card>
  );
}

/* ---------- Chart / section card ---------- */
export function ChartCard({ title, description, action, className, bodyClassName, children }: {
  title: string; description?: string; action?: ReactNode;
  className?: string; bodyClassName?: string; children: ReactNode;
}) {
  return (
    <Card className={cn("rounded-xl shadow-none", className)}>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0 pb-2">
        <div className="min-w-0">
          <CardTitle>{title}</CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </div>
        {action}
      </CardHeader>
      <CardContent className={cn("pt-2", bodyClassName)}>{children}</CardContent>
    </Card>
  );
}

/* ---------- Page title row ---------- */
export function PageHeader({ title, subtitle, actions }: {
  title: string; subtitle?: string; actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="ta-title-3">{title}</h1>
        {subtitle && <p className="ta-label-1 text-muted-foreground">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}

/* ---------- Empty state ---------- */
export function EmptyState({ icon, message, action }: {
  icon?: ReactNode; message: string; action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-10 text-center">
      {icon && <div className="text-muted-foreground">{icon}</div>}
      <p className="ta-body-2 text-muted-foreground max-w-sm">{message}</p>
      {action}
    </div>
  );
}

/* ---------- Domain badges ---------- */
const ACTION_VARIANT = {
  buy: "positive", add: "positive",
  sell: "negative", trim: "negative",
  hold: "neutral",
} as const;

export function ActionBadge({ action }: { action: string }) {
  const variant = ACTION_VARIANT[action as keyof typeof ACTION_VARIANT] ?? "neutral";
  return <Badge variant={variant} className="uppercase-none">{action}</Badge>;
}

/** Confidence rendered as a bar, because a bare 0.62 reads as noise in a table. */
export function ConfidenceBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-secondary">
        <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className="ta-numeric text-[13px] tabular-nums text-muted-foreground">
        {Math.round(value * 100)}%
      </span>
    </div>
  );
}
