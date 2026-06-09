"use client";

// Sprint 10.0 — C-level ana sayfa, ikinci nesil.
//
// Tasarım ilkesi (ürün sahibinin sözleriyle): "her şey çok net,
// çok büyük, çok anlaşılır ve çok basit olmalı. Basit yapmak
// zordur — biz zoru başarıp bu işi çok basit hale getireceğiz."
//
// Bilgi mimarisi, yukarıdan aşağı:
//
//   1. Selamlama (minimal).
//   2. ExecutiveHero — "Müşterileriniz ne söylüyor?" Üç dev sayı
//      (Pozitif/Nötr/Negatif) + oran barı + tek cümle Türkçe yorum.
//   3. AiInsightStrip — son yapay zeka yönetici özeti (headline +
//      3 kritik içgörü). Yoksa 1-dakika CTA.
//   4. VoiceOfCustomer — gerçek müşteri alıntıları. "Veri değil
//      bilgi": yönetici rakam yerine müşterisinin cümlesini okur.
//   5. SwotSnapshotCard | OkrSnapshotCard — son stratejik durum.
//   6. NpsMonthlyTrend + QuickActions — yön + hızlı girişler.
//   7. ClassificationQualityChip — kalite sinyali (kendini gizler).
//
// Tüm üst veri TEK round-trip'ten gelir (useExecutiveOverview) —
// eski sayfa 6+ ayrı HTTP çağrısı yapıyordu.
//
// Sayfadan çıkarılanlar: HealthHero (ExecutiveHero'ya devretti),
// AttentionList (hero cümlesine katlandı), KpiGoalCards +
// RecentTicketsTable (operasyonel — /settings/kpi-goals ve
// /tickets bir tık uzakta; C-level ilk ekranında yer kaplamasın).

import { AiInsightStrip } from "@/components/dashboard/ai-insight-strip";
import { ClassificationQualityChip } from "@/components/dashboard/classification-quality-chip";
import { ExecutiveHero } from "@/components/dashboard/executive-hero";
import { NpsMonthlyTrend } from "@/components/dashboard/nps-monthly-trend";
import { QuickActions } from "@/components/dashboard/quick-actions";
import {
  OkrSnapshotCard,
  SwotSnapshotCard,
} from "@/components/dashboard/strategy-snapshots";
import { TopProblems } from "@/components/dashboard/top-problems";
import { VoiceOfCustomer } from "@/components/dashboard/voice-of-customer";
import { useExecutiveOverview } from "@/hooks/use-executive-overview";
import { useAuthStore } from "@/lib/auth-store";

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
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {firstName ? `Merhaba, ${firstName}` : "Merhaba"}
        </h1>
        <p className="text-muted-foreground text-sm">{tenantName}</p>
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

      <QuickActions />

      <NpsMonthlyTrend />

      <ClassificationQualityChip />
    </main>
  );
}
