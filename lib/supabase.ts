"use client";
import { createBrowserClient } from "@supabase/ssr";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

/** True once the project has Supabase env vars; until then the UI renders
 *  sample data so `npm run dev` works with no setup. */
export const isLive = Boolean(url && key);

export function supabase() {
  if (!isLive) throw new Error("Supabase is not configured");
  return createBrowserClient(url!, key!);
}
