import type { Metadata } from "next";
import "./globals.css";
import { AppSidebar } from "@/components/app-sidebar";
import { AppHeader } from "@/components/app-header";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "sonner";
import { mockBrief } from "@/lib/mock";
import { isLive } from "@/lib/supabase";

export const metadata: Metadata = {
  title: "Quant PM",
  description: "Personal multi-agent portfolio advisor. Informational only.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <body className="antialiased">
        <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
          <div className="flex min-h-svh">
            <AppSidebar />
            <div className="flex min-w-0 flex-1 flex-col">
              <AppHeader session={mockBrief.session} live={isLive} />
              <main className="flex-1 space-y-4 p-4 md:space-y-6 md:p-6">{children}</main>
            </div>
          </div>
          <Toaster position="bottom-right" />
        </ThemeProvider>
      </body>
    </html>
  );
}
