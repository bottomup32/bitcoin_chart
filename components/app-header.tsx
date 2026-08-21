"use client";

import { usePathname } from "next/navigation";
import { ModeToggle } from "@/components/mode-toggle";
import { Badge } from "@/components/ui/badge";

const TITLES: Record<string, string> = {
  "/": "Today",
  "/portfolio": "Portfolio",
  "/learning": "Learning",
  "/memory": "Memory",
  "/ops": "Operations",
};

export function AppHeader({ session, live }: { session: string; live: boolean }) {
  const pathname = usePathname();
  const title = TITLES[pathname] ?? "Quant PM";
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b bg-background px-4 md:px-6">
      <div className="flex items-center gap-2 ta-label-1 text-muted-foreground">
        <span>Quant PM</span>
        <span aria-hidden>/</span>
        <span className="text-foreground">{title}</span>
      </div>
      <div className="flex items-center gap-3">
        {!live && (
          <Badge variant="caution">Sample data — Supabase not connected</Badge>
        )}
        <span className="ta-caption-1 text-muted-foreground tabular-nums">
          Session {session}
        </span>
        <ModeToggle />
      </div>
    </header>
  );
}
