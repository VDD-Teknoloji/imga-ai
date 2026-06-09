"use client";

import { Menu } from "lucide-react";
import { useState } from "react";

import { PageTransition } from "@/components/layout/page-transition";
import { QuickActionFab } from "@/components/layout/quick-action-fab";
import { Sidebar } from "@/components/layout/sidebar";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

interface AppShellProps {
  children: React.ReactNode;
}

/**
 * Frame for every authenticated page. On md+ screens the desktop
 * sidebar sits as a fixed left rail; on smaller screens an icon
 * button opens the same sidebar in a Sheet.
 *
 * The topbar in the desktop view stays minimal — page titles and
 * per-page actions live inside each page's content area. A future
 * sprint can expand the topbar (search, notifications, breadcrumbs)
 * without touching this layout.
 */
export function AppShell({ children }: AppShellProps) {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-screen w-full">
      {/* Desktop sidebar — hidden below md. */}
      <div className="hidden md:flex">
        <Sidebar variant="desktop" />
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile-only topbar (visible below md). */}
        <header className="bg-background flex h-12 shrink-0 items-center gap-2 border-b px-3 md:hidden">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger
              render={
                <Button variant="ghost" size="icon" aria-label="Menüyü aç" className="size-9">
                  <Menu className="size-5" aria-hidden />
                </Button>
              }
            />
            <SheetContent side="left" className="w-[260px] p-0">
              <SheetTitle className="sr-only">Kenar çubuğu</SheetTitle>
              <Sidebar variant="mobile" onNavigate={() => setMobileOpen(false)} />
            </SheetContent>
          </Sheet>
          <span className="text-sm font-semibold tracking-tight">imga.ai</span>
        </header>

        {/* Each route page renders its own <main>; the shell's
            wrapper stays a <div> so we don't have two `main`
            landmarks on the same page (a11y guard).
            Sprint 10.3 — PageTransition: her rota geçişinde içerik
            fade+rise ile açılır (tüm sayfalara giriş animasyonu). */}
        <div className="min-w-0 flex-1">
          <PageTransition>{children}</PageTransition>
        </div>
      </div>

      {/* Sprint 9.6 redesign — universal floating action button.
          Sits over every authenticated page so the 4 primary
          actions (Yeni yükleme, Brifing üret, Aksiyonlar, Strateji)
          are 1 click from anywhere. Multi-entry pattern, like the
          iPhone camera surfacing on lock screen + control center
          + apps drawer. */}
      <QuickActionFab />
    </div>
  );
}
