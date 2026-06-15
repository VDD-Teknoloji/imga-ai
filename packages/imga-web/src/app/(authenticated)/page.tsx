"use client";

// Sprint 12 — C-level ana sayfa: sakin, tek-cevaplı rapor.
//
// Tasarım ilkesi (ürün sahibi): "C-level yönetici için her şey en
// basit haliyle, çok net değerler. Aydınlık, korkutmayan, Apple
// gibi. Bir aptal bile anlasın; işten anlayan detaya inebilsin."
//
// Akış — yukarıdan aşağı, giderek derinleşir:
//
//   DURUM      ExecutiveHero      "Müşterileriniz memnun mu?" (cevap)
//   AKSİYON    PriorityAction     "Bu ay ne yapmalıyım?" (tek adım)
//   SORUNLAR   TopProblems        "Neyden şikayetçiler?"
//   KANIT      VoiceOfCustomer    "Kendi cümleleriyle"
//   DERİNLİK   Özet + SWOT + OKR  işten anlayan buraya iner
//
// Sağ ray (sticky): yerinde toplu yükleme + dört hızlı kapı.
// Tüm üst veri TEK round-trip'ten gelir (useExecutiveOverview).

import { AiInsightStrip } from "@/components/dashboard/ai-insight-strip";
import { ClassificationQualityChip } from "@/components/dashboard/classification-quality-chip";
import { ExecutiveHero } from "@/components/dashboard/executive-hero";
import { PriorityAction } from "@/components/dashboard/priority-action";
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

  const tenantName = activeContext?.tenant_name ?? "Aktif kurum yok";
  const firstName = user?.full_name?.split(" ")[0] ?? "";
  const isLoading = overview.isLoading;
  const data = overview.data;

  return (
    <main className="mx-auto w-full max-w-6xl space-y-8 px-4 py-6 md:px-8 md:py-10">
      <header className="flex flex-wrap items-end justify-between gap-2">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {firstName ? `Merhaba, ${firstName}` : "Merhaba"}
          </h1>
          <p className="text-muted-foreground text-sm">{tenantName}</p>
        </div>
        {/* Rapor tarihi. SSG/client farkı olabilir; uyarıyı bastır. */}
        <p
          className="text-muted-foreground text-sm tabular-nums"
          suppressHydrationWarning
        >
          {DATE_FORMATTER.format(new Date())}
        </p>
      </header>

      {/* DURUM — tek cümle cevap. */}
      <ExecutiveHero overview={data} isLoading={isLoading} />

      {/* AKSİYON — bu ayki tek öncelik (varsa). */}
      <PriorityAction swot={data?.latest_swot} />

      {/* Rapor (sol) + işlem rayı (sağ). */}
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-8">
          <div className="rise-in" style={{ animationDelay: "80ms" }}>
            <TopProblems problems={data?.top_problems} isLoading={isLoading} />
          </div>

          <div className="rise-in" style={{ animationDelay: "160ms" }}>
            <VoiceOfCustomer
              quotes={data?.voice_of_customer}
              isLoading={isLoading}
            />
          </div>

          <div className="rise-in" style={{ animationDelay: "240ms" }}>
            <AiInsightStrip
              briefing={data?.latest_briefing}
              isLoading={isLoading}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
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
