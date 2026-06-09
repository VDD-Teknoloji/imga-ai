"use client";

// Sprint 10.2 — C-level ana sayfa: yönetici raporu.
//
// Tasarım ilkesi (ürün sahibinin sözleriyle): "her şey çok net,
// çok büyük, çok anlaşılır ve çok basit olmalı. Basit yapmak
// zordur — biz zoru başarıp bu işi çok basit hale getireceğiz."
//
// Bilgi mimarisi, yukarıdan aşağı — her blok rapor değeri taşır:
//
//   1. Selamlama + rapor tarihi (minimal).
//   2. ExecutiveHero — DURUM: memnuniyet göstergesi + durum
//      damgası + trend + tek cümle Türkçe anlatı + 2 CTA.
//   3. TopProblems — NEDENLER: olumsuzluğun kaynağı top 3.
//   4. AiInsightStrip — AI İÇGÖRÜSÜ: son yönetici özeti.
//   5. VoiceOfCustomer — MÜŞTERİ SESİ: gerçek alıntılar.
//   6. SwotSnapshotCard | OkrSnapshotCard — STRATEJİ.
//   7. ClassificationQualityChip — kalite sinyali (kendini gizler).
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
import {
  OkrSnapshotCard,
  SwotSnapshotCard,
} from "@/components/dashboard/strategy-snapshots";
import { TopProblems } from "@/components/dashboard/top-problems";
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

      {/* Sprint 10.1 — Ana Sorunlar: olumsuzluğun kaynağı, hero'nun
          hemen altında. Yönetici durumu gördükten sonra "neden"i
          ve "ne yapacağım"ı burada bulur. */}
      <TopProblems problems={data?.top_problems} isLoading={isLoading} />

      <AiInsightStrip briefing={data?.latest_briefing} isLoading={isLoading} />

      <VoiceOfCustomer quotes={data?.voice_of_customer} isLoading={isLoading} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SwotSnapshotCard swot={data?.latest_swot} isLoading={isLoading} />
        <OkrSnapshotCard okr={data?.latest_okr} isLoading={isLoading} />
      </div>

      <ClassificationQualityChip />
    </main>
  );
}
