import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Percent with an explicit sign — used everywhere returns are shown. */
export function pct(value: number | null | undefined, digits = 1) {
  if (value === null || value === undefined) return "—";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;
}

export function usd(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-US", { style: "currency", currency: "USD",
    minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function compactUsd(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-US", { style: "currency", currency: "USD",
    notation: "compact", maximumFractionDigits: 1 });
}
