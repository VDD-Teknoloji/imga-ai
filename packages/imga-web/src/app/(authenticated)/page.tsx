"use client";

// Sprint 10.3 — C-level ana sayfa: rapor + işlem merkezi.
//
// Tasarım ilkesi (ürün sahibinin sözleriyle): "her şey çok net,
// çok büyük, çok anlaşılır ve çok basit olmalı. Basit yapmak
// zordur — biz zoru başarıp bu işi çok basit hale getireceğiz."
//
// Düzen: hero tam genişlik; altında İKİ kolon —
//
//   SOL (rapor akışı):            SAĞ (işlem rayı, sticky):
//   TopProblems (NEDENLER)        UploadDock — yerinde toplu
//   AiInsightStrip (AI İÇGÖRÜ)      yükleme + canlı ilerleme
//   VoiceOfCustomer (MÜŞTERİ)     QuickLinks — 4 kapı
//   SWOT | OKR (STRATEJİ)
//
// "Hem kolayca işlem yapabilsin hem tüm analizi görebilsin":
// rapor sola akar, eller sağda. Bölümler stagger'lı rise-in ile
// sırayla açılır; hero göstergesi sıfırdan dolar (use-count-up).
//
// Tüm üst veri TEK round-trip'ten gelir (useExecutiveOverview) —
// eski sayfa 6+ ayrı HTTP çağrısı yapıyordu.
//
// Sayfadan çıkarılanlar (Sprint 10.0 + 10.2 sadeleştirme):
// HealthHero (ExecutiveHero'ya devretti), AttentionList (hero
// cümlesine katlandı), KpiGoalCards + RecentTicketsTable
// (operasyonel), QuickActions (FAB + sidebar zaten kapsıyor) ve
// NpsMonthlyTrend (yön bilgisi hero'daki trend pill'inde —
// 12 aylık çizgi "veri", pill "bilgi"). Ana ekranda yalnızca
// rapor değeri taşıyan bloklar kaldı: durum → nedenler → AI
// içgörüsü → müşteri sesi → strateji.

import { AiInsightStrip } from "@/components/dashboard/ai-insight-strip";
import { ClassificationQualityChip } from "@/components/dashboard/classification-quality-chip";
import { ExecutiveHero } from "@/components/dashboard/executive-hero";
import { QuickLinks } from "@/components/dashboard/quick-links";
import {
  OkrSnapshotCard,
  SwotSnapshotCard,
} from "@/components/dashboard/strategy-snapshots";
import { TopProblems } from "@/components/dashboard/top-problems";
import { UploadDock } from "@/components/dashboard/upload-dock";
import { VoiceOfCustomer } from "@/components/dashboard/voice-of-customer";
import { useExecutiveOverview } from "@/hooks/use-executive-overview";
import { useAuthStore } from "@/lib/auth-store";

const DATE_FORMATTER = new Intl.DateTimeFormat("tr-TR", {
  day: "numeric",
  month: "long",
  year: "numeric",
  weekday: "long",
});

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const activeContext = useAuthStore((s) => s.activeContext);
  const overview = useExecutiveOverview();

  const tenantName = activeContext?.tenant_name ?? "Aktif tenant yok";
  const firstName = user?.full_name?.split(" ")[0] ?? "";
  const isLoading = overview.isLoading;
  const data = overview.data;

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex flex-wrap items-end justify-between gap-2">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {firstName ? `Merhaba, ${firstName}` : "Merhaba"}
          </h1>
          <p className="text-muted-foreground text-sm">{tenantName}</p>
        </div>
        {/* Rapor tarihi — yönetici raporu hangi güne baktığını bilir.
            Build anındaki SSG çıktısı ile client tarihi farklı
            olabilir; metin client'ta güncellenir, uyarıyı bastır. */}
        <p
          className="text-muted-foreground text-sm tabular-nums"
          suppressHydrationWarning
        >
          {DATE_FORMATTER.format(new Date())}
        </p>
      </header>

      <ExecutiveHero overview={data} isLoading={isLoading} />

      {/* Rapor (sol) + işlem rayı (sağ). Bölümler stagger'lı
          rise-in ile sırayla yükselir — sayfa "canlanır". */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-6">
          <div className="rise-in" style={{ animationDelay: "60ms" }}>
            <TopProblems problems={data?.top_problems} isLoading={isLoading} />
          </div>

          <div className="rise-in" style={{ animationDelay: "140ms" }}>
            <AiInsightStrip
              briefing={data?.latest_briefing}
              isLoading={isLoading}
            />
          </div>

          <div className="rise-in" style={{ animationDelay: "220ms" }}>
            <VoiceOfCustomer
              quotes={data?.voice_of_customer}
              isLoading={isLoading}
            />
          </div>

          <div
            className="rise-in grid grid-cols-1 gap-4 xl:grid-cols-2"
            style={{ animationDelay: "300ms" }}
          >
            <SwotSnapshotCard swot={data?.latest_swot} isLoading={isLoading} />
            <OkrSnapshotCard okr={data?.latest_okr} isLoading={isLoading} />
          </div>
        </div>

        <aside className="space-y-4 lg:sticky lg:top-6 lg:self-start">
          <UploadDock />
          <QuickLinks />
        </aside>
      </div>

      <ClassificationQualityChip />
    </main>
  );
}
