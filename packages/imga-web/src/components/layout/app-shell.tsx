"use client";

import { Menu } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { PageTransition } from "@/components/layout/page-transition";
import { QuickActionFab } from "@/components/layout/quick-action-fab";
import { Sidebar } from "@/components/layout/sidebar";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { useAuthStore } from "@/lib/auth-store";
import { useTranslation } from "@/lib/i18n/use-translation";

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
  const { t } = useTranslation();
  // W1-A — sadece tenant_id'yi seçiyoruz (activeContext'in tamamı
  // değil) ki tenant değişmeyen her diğer alan güncellemesi bu
  // bileşeni gereksiz yere yeniden render etmesin.
  const tenantId = useAuthStore((s) => s.activeContext?.tenant_id);
  const pathname = usePathname();
  const contentRef = useRef<HTMLDivElement>(null);

  // Next.js'in scroll-to-top davranışı <body> üzerinde çalışır; içerik
  // scroll'unu bu bölmeye taşıdığımız için (bkz. aşağıdaki
  // overflow-y-auto) rota değişiminde kendi elimizle sıfırlamamız
  // gerekiyor, yoksa yeni sayfa bir önceki sayfanın scroll konumunda açılır.
  // tenantId da bağımlılıkta: aynı rotada kurum değiştirildiğinde de
  // içerik en başa dönsün (yeni kurumun sayfası eski scroll'da açılmasın).
  useEffect(() => {
    contentRef.current?.scrollTo(0, 0);
  }, [pathname, tenantId]);

  return (
    <div className="flex h-dvh w-full overflow-hidden">
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
                <Button variant="ghost" size="icon" aria-label={t("shell.header.openMenu")} className="size-9">
                  <Menu className="size-5" aria-hidden />
                </Button>
              }
            />
            <SheetContent side="left" className="w-[260px] p-0">
              <SheetTitle className="sr-only">{t("shell.sidebar.label")}</SheetTitle>
              <Sidebar variant="mobile" onNavigate={() => setMobileOpen(false)} />
            </SheetContent>
          </Sheet>
          <span className="text-sm font-semibold tracking-tight">imga.ai</span>
        </header>

        {/* Each route page renders its own <main>; the shell's
            wrapper stays a <div> so we don't have two `main`
            landmarks on the same page (a11y guard).
            Sprint 10.3 — PageTransition: her rota geçişinde içerik
            fade+rise ile açılır (tüm sayfalara giriş animasyonu).
            W1-A — min-h-0 zorunlu: flex item'ların varsayılan
            min-height:auto değeri, açıkça sıfırlanmadıkça
            overflow-y-auto'nun devreye girmesini engeller. Bu bölme
            artık kendi scroll'unu taşıyor (sidebar zaten kendi
            scroll'unu taşıyordu — bkz. sidebar.tsx), böylece sidebar
            sabit kalırken içerik bağımsız kayar. */}
        <div ref={contentRef} className="min-h-0 min-w-0 flex-1 overflow-y-auto">
          {/* W1-A — key=tenant_id: tenant değişince alt ağaç yeniden
              mount olur. React Query önbelleği resetQueries() ile zaten
              tazeleniyor (auth-store.ts); bu key, React Query DIŞINDAKİ
              hook'ları da (ör. useBatchProgressStream'in SSE/local
              state'i) sıfırlayarak eski tenant'a ait bağlantı/durumun
              yeni tenant'ta sızmasını önler. */}
          <PageTransition key={tenantId ?? "no-tenant"}>{children}</PageTransition>
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
