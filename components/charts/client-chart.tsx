"use client";

import { useEffect, useState } from "react";
import { Bar, Doughnut, Line } from "react-chartjs-2";
import { useTheme } from "next-themes";

import { applyChartDefaults, readChartTheme } from "@/lib/chart-theme";
import { Skeleton } from "@/components/ui/skeleton";

type Kind = "line" | "bar" | "doughnut";
export type ChartTheme = ReturnType<typeof readChartTheme>;

/** Loose on purpose: Chart.js dataset shapes differ per chart type, and the
 *  three components below each want their own generic. Keeping the cast in
 *  this one file means call sites stay readable. */
export interface ChartDatasetLike extends Record<string, unknown> {
  data: number[];
}
export interface ChartDataLike {
  labels: (string | number)[];
  datasets: ChartDatasetLike[];
}
export type ChartOptionsLike = Record<string, unknown>;

/** Charts must re-read CSS variables after a dark toggle — Chart.js cannot
 *  resolve them itself — so the resolved theme is used as a remount key. */
export function ClientChart({ kind, data, options, height = 260 }: {
  kind: Kind;
  data: (theme: ChartTheme) => ChartDataLike;
  options?: ChartOptionsLike;
  height?: number;
}) {
  const { resolvedTheme } = useTheme();
  const [theme, setTheme] = useState<ChartTheme | null>(null);

  useEffect(() => {
    setTheme(applyChartDefaults());
  }, [resolvedTheme]);

  if (!theme) return <Skeleton style={{ height }} className="w-full" />;

  // Each react-chartjs-2 component is generic over its own chart type, so a
  // union of them has no common assignable prop shape. One cast here beats
  // duplicating this component three times.
  const Comp = (kind === "line" ? Line : kind === "bar" ? Bar : Doughnut) as unknown as
    React.ComponentType<{ data: ChartDataLike; options?: ChartOptionsLike }>;

  return (
    <div style={{ height }}>
      <Comp key={resolvedTheme} data={data(theme)} options={options} />
    </div>
  );
}
