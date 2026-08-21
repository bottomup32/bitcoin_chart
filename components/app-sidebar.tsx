"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Brain, CalendarCheck, LineChart, Settings2, Wallet,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Today", icon: CalendarCheck,
    hint: "Decisions and the opinions behind them" },
  { href: "/portfolio", label: "Portfolio", icon: Wallet,
    hint: "Holdings, tax lots, wash-sale exposure" },
  { href: "/learning", label: "Learning", icon: LineChart,
    hint: "Scoring outcomes and agent weights" },
  { href: "/memory", label: "Memory", icon: Brain,
    hint: "What each agent recalls, and the corpus" },
  { href: "/ops", label: "Operations", icon: Settings2,
    hint: "Runs, cost, watchlist" },
];

export function AppSidebar() {
  const pathname = usePathname();
  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r bg-sidebar md:flex">
      <div className="flex h-14 items-center gap-2 border-b px-5">
        <div className="grid size-6 place-items-center rounded-sm bg-primary">
          <span className="ta-caption-1 font-semibold text-primary-foreground">Q</span>
        </div>
        <span className="ta-headline-2">Quant PM</span>
      </div>

      <nav className="flex flex-1 flex-col gap-0.5 p-3">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link key={href} href={href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 ta-label-1 transition-colors duration-150",
                active ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground"
              )}>
              <Icon className="size-4" strokeWidth={2} />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t p-4">
        <p className="ta-caption-1 text-muted-foreground">
          Informational only. Not investment advice.
        </p>
      </div>
    </aside>
  );
}
