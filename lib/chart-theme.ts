"use client";
import {
  ArcElement, BarElement, CategoryScale, Chart, Filler, Legend, LineElement,
  LinearScale, PointElement, Tooltip,
} from "chart.js";

export const CHART_SERIES = 7; // --chart-1 .. --chart-7

let registered = false;
export function registerChartJs() {
  if (registered) return;
  Chart.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement,
    ArcElement, Tooltip, Legend, Filler);
  registered = true;
}

/** Chart.js cannot resolve CSS variables, so read them at render time. */
export function readChartTheme() {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();
  return {
    colors: Array.from({ length: CHART_SERIES }, (_, i) => v(`--chart-${i + 1}`)),
    fg: v("--foreground"),
    mutedFg: v("--muted-foreground"),
    grid: "rgba(112, 115, 124, 0.12)",
    card: v("--card"),
    border: v("--border"),
    success: v("--success"),
    destructive: v("--destructive"),
    warning: v("--warning"),
    fontSans: v("--font-sans"),
  };
}

export function applyChartDefaults() {
  registerChartJs();
  const t = readChartTheme();
  Chart.defaults.font.family = t.fontSans;
  Chart.defaults.font.size = 12;
  Chart.defaults.color = t.mutedFg;
  Chart.defaults.borderColor = t.grid;
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  Chart.defaults.plugins.legend.labels.boxHeight = 8;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.tooltip.backgroundColor = t.card;
  Chart.defaults.plugins.tooltip.titleColor = t.fg;
  Chart.defaults.plugins.tooltip.bodyColor = t.mutedFg;
  Chart.defaults.plugins.tooltip.borderColor = t.border;
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.plugins.tooltip.cornerRadius = 10;
  Chart.defaults.plugins.tooltip.padding = 12;
  Chart.defaults.animation = { duration: 150, easing: "easeOutQuad" };
  return t;
}

/** Series color with alpha, for area fills. */
export function fade(hex: string, alpha = 0.12) {
  return `color-mix(in srgb, ${hex} ${Math.round(alpha * 100)}%, transparent)`;
}
