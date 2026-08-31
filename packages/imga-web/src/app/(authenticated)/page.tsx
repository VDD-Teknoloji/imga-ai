"use client";

// Sprint 13 — C-level ana sayfa, dönem-filtreli rapor.
//
// Tasarım ilkesi (ürün sahibi): "C-level yönetici için her şey en
// basit haliyle, çok net değerler. Aydınlık, korkutmayan, Apple
// gibi. Bir aptal bile anlasın; işten anlayan detaya inebilsin."
//
// Akış — yukarıdan aşağı, giderek derinleşir. Sprint 13.2 (A2) "kök
// neden önce" yeniden sıralaması: yönetici eskiden önce sayıları
// (grafikler), sonra nedeni görüyordu — ürün sahibi isteği tersini
// ister: önce "neden?" ve "ne yapmalıyım?", sayılar altta kalsın.
//
// Sprint 13.3 (2026-09-01) — ürün sahibi doğrudan talimatı: "önce
// kök neden" ExecutiveHero'nun bile önüne geçti. RootCauseCards artık
// UploadFirst'ün hemen altında, dönem filtresinden ve memnuniyet
// hero'sundan önce render edilir.
//
//   (VERİ YOK)  UploadFirst        24 saattir veri gelmediyse önce yükleme
//   NEDEN       RootCauseCards     "Neden? Ne yapmalısınız?" — en çok
//                                  şikayet edilen ≤3 kategori + kök
//                                  neden + önerilen aksiyon
//   DURUM       ExecutiveHero      "Müşterileriniz memnun mu?" (cevap)
//   FİLTRE      DashboardFilterBar dönem presetleri + özel aralık +
//                                  yükleme (URL: ?window / ?date_from /
//                                  ?date_to / ?batch_job_id)
//   AKSİYON     PriorityAction     "Bu ay ne yapmalıyım?" (tek adım)
//   KOÇ         DataQualityCoach   veri kalitesi sinyali (eski
//                                  ClassificationQualityChip'in yerine)
//   GRAFİKLER   NPS + Kategori     yönetim görünümü dağılımları
//   SORUNLAR    TopProblems        "Neyden şikayetçiler?"
//   KANIT       VoiceOfCustomer    "Kendi cümleleriyle"
//   DERİNLİK    Özet + SWOT + OKR  işten anlayan buraya iner
//
// Sağ ray (sticky): yerinde toplu yükleme + dört hızlı kapı.
// Dönem filtresi hero + NPS + kategori chart'larını pencereler;
// URL state Path B mirror (docs/agent-rules/url-state-patterns.md).

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AiInsightStrip } from "@/components/dashboard/ai-insight-strip";
import { CategorySentimentBreakdown } from "@/components/dashboard/category-sentiment-breakdown";
import { DashboardFilterBar } from "@/components/dashboard/dashboard-filter-bar";
import { DataQualityCoach } from "@/components/dashboard/data-quality-coach";
import { ExecutiveHero } from "@/components/dashboard/executive-hero";
import { ExperienceBreakdownCards } from "@/components/dashboard/experience-breakdown-cards";
import { NpsBreakdownCard } from "@/components/dashboard/nps-breakdown-card";
import { PriorityAction } from "@/components/dashboard/priority-action";
import { QuickLinks } from "@/components/dashboard/quick-links";
import { RootCauseCards } from "@/components/dashboard/root-cause-cards";
import {
  OkrSnapshotCard,
  SwotSnapshotCard,
} from "@/components/dashboard/strategy-snapshots";
import {
  isTimeWindowKey,
  timeWindowDateFrom,
  type TimeWindowKey,
} from "@/components/dashboard/time-window-filter";
import { TopProblems } from "@/components/dashboard/top-problems";
import { UploadDock } from "@/components/dashboard/upload-dock";
import { VoiceOfCustomer } from "@/components/dashboard/voice-of-customer";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type AnalyticsQueryFilters,
  useNpsSummary,
  useSentimentByCategory,
  useSentimentDistribution,
} from "@/hooks/use-analytics";
import {
  useExecutiveOverview,
  type ExecutiveOverview,
} from "@/hooks/use-executive-overview";
import { useExperienceDistribution } from "@/hooks/use-experience";
import { useRoleFlags } from "@/hooks/use-role-flags";
import { useAuthStore } from "@/lib/auth-store";
import { useTranslation } from "@/lib/i18n/use-translation";

// Son veri girişi bundan eskiyse yükleme alanı sayfanın tepesine
// alınır (ürün sahibi: "24 saattir veri yüklememiş adam ilk olarak
// veri yükleme alanını görecek").
const UPLOAD_FIRST_THRESHOLD_MS = 24 * 60 * 60 * 1000;

export default function DashboardPage() {
  return (
    <Suspense fallback={<DashboardSkeleton />}>
      <DashboardInner />
    </Suspense>
  );
}

function DashboardSkeleton() {
  return (
    <main className="mx-auto w-full max-w-6xl space-y-8 px-4 py-6 md:px-8 md:py-10">
      <Skeleton className="h-10 w-64" />
      <Skeleton className="h-72 w-full rounded-3xl" />
      <Skeleton className="h-56 w-full rounded-3xl" />
    </main>
  );
}

function DashboardInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const user = useAuthStore((s) => s.user);
  const activeContext = useAuthStore((s) => s.activeContext);
  const { canWrite } = useRoleFlags();
  const { t, locale } = useTranslation();

  // URL → local state mirror (Path B — url-state-patterns.md).
  // Tek gerçek kaynak: özel tarih girilince ?window silinir, preset
  // seçilince ?date_from/?date_to silinir; ?batch_job_id bağımsız.
  const [windowKey, setWindowKey] = useState<TimeWindowKey>(() => {
    const raw = searchParams.get("window");
    return isTimeWindowKey(raw) ? raw : "all";
  });
  const [customDateFrom, setCustomDateFrom] = useState<string>(
    () => searchParams.get("date_from") ?? "",
  );
  const [customDateTo, setCustomDateTo] = useState<string>(
    () => searchParams.get("date_to") ?? "",
  );
  const [batchJobId, setBatchJobId] = useState<string>(
    () => searchParams.get("batch_job_id") ?? "",
  );
  // 2026-08-18 (Dalga 3, WS2) — "Düşük kaliteli veriyi dahil et" switch.
  // Varsayılan kapalı (backend include_flagged=false default'uyla aynı).
  const [includeFlagged, setIncludeFlagged] = useState<boolean>(
    () => searchParams.get("include_flagged") === "1",
  );
  /* eslint-disable react-hooks/set-state-in-effect */
  // INTENT: URL is source of truth; mirror onto local state on
  // navigation events. Path B pattern (Sprint 8.3.4 round-2).
  useEffect(() => {
    const raw = searchParams.get("window");
    const fromUrl: TimeWindowKey = isTimeWindowKey(raw) ? raw : "all";
    setWindowKey((prev) => (prev === fromUrl ? prev : fromUrl));
    const urlFrom = searchParams.get("date_from") ?? "";
    setCustomDateFrom((prev) => (prev === urlFrom ? prev : urlFrom));
    const urlTo = searchParams.get("date_to") ?? "";
    setCustomDateTo((prev) => (prev === urlTo ? prev : urlTo));
    const urlBatch = searchParams.get("batch_job_id") ?? "";
    setBatchJobId((prev) => (prev === urlBatch ? prev : urlBatch));
    const urlIncludeFlagged = searchParams.get("include_flagged") === "1";
    setIncludeFlagged((prev) => (prev === urlIncludeFlagged ? prev : urlIncludeFlagged));
  }, [searchParams]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function pushParams(updates: Record<string, string | null>) {
    const params = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === "") params.delete(key);
      else params.set(key, value);
    }
    const qs = params.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  function handleWindowChange(next: TimeWindowKey) {
    setWindowKey(next);
    setCustomDateFrom("");
    setCustomDateTo("");
    pushParams({
      window: next === "all" ? null : next,
      date_from: null,
      date_to: null,
    });
  }

  function handleDateFromChange(next: string) {
    setCustomDateFrom(next);
    setWindowKey("all");
    pushParams({ date_from: next || null, window: null });
  }

  function handleDateToChange(next: string) {
    setCustomDateTo(next);
    setWindowKey("all");
    pushParams({ date_to: next || null, window: null });
  }

  function handleBatchChange(next: string | undefined) {
    setBatchJobId(next ?? "");
    pushParams({ batch_job_id: next ?? null });
  }

  function handleIncludeFlaggedChange(next: boolean) {
    setIncludeFlagged(next);
    pushParams({ include_flagged: next ? "1" : null });
  }

  function handleClearFilters() {
    setWindowKey("all");
    setCustomDateFrom("");
    setCustomDateTo("");
    setBatchJobId("");
    setIncludeFlagged(false);
    pushParams({
      window: null,
      date_from: null,
      date_to: null,
      batch_job_id: null,
      include_flagged: null,
    });
  }

  // Efektif aralık: özel tarih varsa o, yoksa dönem preseti.
  // Hepsi YYYY-MM-DD taşır; ISO genişletmesi fetch hook'larında.
  const filters = {
    date_from: customDateFrom || timeWindowDateFrom(windowKey),
    date_to: customDateTo || undefined,
    batch_job_id: batchJobId || undefined,
  };
  // 2026-08-18 (Dalga 3, WS2) — include_flagged yalnız ham analitik
  // uçlarına gider (dist/nps/byCategory/experience). useExecutiveOverview
  // her zaman temiz veri döner (backend FX2: 7 yüzeyde quality_flag IS
  // NULL sabit filtre, include_flagged param'ı hiç kabul etmiyor) — bu
  // yüzden AKSİYON/SORUNLAR/KANIT/DERİNLİK bölümleri toggle'dan etkilenmez.
  const queryFilters: AnalyticsQueryFilters = {
    ...filters,
    include_flagged: includeFlagged || undefined,
  };
  const overview = useExecutiveOverview(filters);
  const dist = useSentimentDistribution(queryFilters);
  const nps = useNpsSummary(queryFilters);
  const byCategory = useSentimentByCategory(queryFilters, 10);
  // Deneyim dağılımı yalnız tarih aralığı alır — uç henüz
  // batch_job_id kabul etmiyor; yükleme filtresi bu kartlara işlemez.
  const experience = useExperienceDistribution({
    date_from: filters.date_from,
    date_to: filters.date_to,
    include_flagged: includeFlagged || undefined,
  });

  const sentimentCounts = toSentimentCounts(dist.data);
  // hasAnyData filtreye duyarsız olmalı (boş-pencere ≠ boş-tenant);
  // filtreli overview'da sentiment.total artık pencereli, last_data_at
  // ise tüm-zamanlar — ayrımı o yapar.
  const hasAnyData =
    overview.data !== undefined && overview.data.last_data_at !== null;

  // 24 saat kuralı: yalnız yükleme yetkisi olan roller için (viewer
  // yükleyemez — backend 403; ona bu çağrıyı yapmak anlamsız).
  const lastDataAt = overview.data?.last_data_at ?? null;
  const uploadFirst =
    canWrite &&
    overview.data !== undefined &&
    (lastDataAt === null ||
      Date.now() - new Date(lastDataAt).getTime() > UPLOAD_FIRST_THRESHOLD_MS);
  // Hiç veri yüklenmemiş kurum, 24 saattir sessiz kalmış kurumdan ayrı
  // bir karşılama metni alır (uploadFirst.title yerine titleNew).
  const neverUploaded = lastDataAt === null;

  const dateFormatter = new Intl.DateTimeFormat(
    locale === "en" ? "en-US" : "tr-TR",
    {
      day: "numeric",
      month: "long",
      year: "numeric",
      weekday: "long",
    },
  );

  const tenantName = activeContext?.tenant_name ?? t("dashboard.home.noTenant");
  const firstName = user?.full_name?.split(" ")[0] ?? "";
  const isLoading = overview.isLoading;
  const data = overview.data;

  return (
    <main className="mx-auto w-full max-w-6xl space-y-8 px-4 py-6 md:px-8 md:py-10">
      <header className="flex flex-wrap items-end justify-between gap-2">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {firstName
              ? t("dashboard.home.greetingNamed", { name: firstName })
              : t("dashboard.home.greeting")}
          </h1>
          <p className="text-muted-foreground text-sm">{tenantName}</p>
        </div>
        {/* Rapor tarihi. SSG/client farkı olabilir; uyarıyı bastır. */}
        <p
          className="text-muted-foreground text-sm tabular-nums"
          suppressHydrationWarning
        >
          {dateFormatter.format(new Date())}
        </p>
      </header>

      {/* VERİ YOK — 24 saattir veri gelmediyse önce yükleme alanı. */}
      {uploadFirst && (
        <section className="rise-in ring-primary/25 bg-primary/5 rounded-3xl p-5 ring-2 md:p-6">
          <div className="mb-4">
            <h2 className="text-lg font-semibold tracking-tight">
              {neverUploaded
                ? t("dashboard.uploadFirst.titleNew")
                : t("dashboard.uploadFirst.title")}
            </h2>
            <p className="text-muted-foreground mt-1 max-w-2xl text-sm leading-relaxed">
              {neverUploaded
                ? t("dashboard.uploadFirst.descNew")
                : t("dashboard.uploadFirst.desc")}
            </p>
          </div>
          <UploadDock />
        </section>
      )}

      {/* NEDEN — en çok şikayet edilen ≤3 kategori + kök neden + aksiyon.
          Ürün sahibi talimatı (2026-09-01): hero'dan önce gelir.
          Sayfanın aktif dönemi taşınır; yeni bir filtre eklenmiyor. */}
      <RootCauseCards filters={filters} categories={byCategory.data} />

      {/* DURUM — tek cümle cevap (seçili döneme göre). */}
      <ExecutiveHero
        sentiment={sentimentCounts}
        trend={data?.trend}
        npsScore={nps.data?.score}
        isLoading={isLoading || dist.isLoading}
        hasAnyData={hasAnyData}
        batchFilterActive={batchJobId !== ""}
        dateFrom={filters.date_from}
        dateTo={filters.date_to}
        canWrite={canWrite}
        hideOwnUpload={uploadFirst}
      />

      {/* FİLTRE — hero'nun hemen altında dönem + özel aralık + yükleme. */}
      <DashboardFilterBar
        windowKey={windowKey}
        onWindowChange={handleWindowChange}
        dateFrom={customDateFrom}
        dateTo={customDateTo}
        onDateFromChange={handleDateFromChange}
        onDateToChange={handleDateToChange}
        batchJobId={batchJobId}
        onBatchChange={handleBatchChange}
        includeFlagged={includeFlagged}
        onIncludeFlaggedChange={handleIncludeFlaggedChange}
        onClear={handleClearFilters}
      />

      {/* AKSİYON — bu ayki tek öncelik (varsa). */}
      <PriorityAction swot={data?.latest_swot} />

      {/* KOÇ — veri kalitesi sinyali (eski ClassificationQualityChip'in
          yerine; bkz. data-quality-coach.tsx). */}
      <DataQualityCoach dateFrom={filters.date_from} dateTo={filters.date_to} />

      {/* GRAFİKLER — yönetim görünümü: NPS + deneyim + kategori×duygu.
          "Kök neden önce" sıralamasında (A2) sayılar aşağı indi. */}
      <div className="rise-in space-y-6" style={{ animationDelay: "60ms" }}>
        <NpsBreakdownCard data={nps.data} isLoading={nps.isLoading} />
        <ExperienceBreakdownCards
          data={experience.data}
          isLoading={experience.isLoading}
        />
        <CategorySentimentBreakdown
          data={byCategory.data}
          isLoading={byCategory.isLoading}
          filters={queryFilters}
        />
      </div>

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

          {/* Sıfır veride SWOT/OKR/özet üretim daveti anlamsız — bu
              bloklar yalnız yükleme bekleniyorken (iskelet) veya
              gerçek veri varken render edilir. */}
          {(isLoading || hasAnyData) && (
            <div className="rise-in" style={{ animationDelay: "240ms" }}>
              <AiInsightStrip
                briefing={data?.latest_briefing}
                isLoading={isLoading}
              />
            </div>
          )}

          {(isLoading || hasAnyData) && (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <SwotSnapshotCard swot={data?.latest_swot} isLoading={isLoading} />
              <OkrSnapshotCard okr={data?.latest_okr} isLoading={isLoading} />
            </div>
          )}
        </div>

        <aside className="space-y-4 lg:sticky lg:top-6 lg:self-start">
          {/* Yükleme tepede öne alındıysa rayda tekrarlama; viewer
              hiç görmez (yükleme yetkisi yok). */}
          {canWrite && !uploadFirst && <UploadDock />}
          <QuickLinks />
        </aside>
      </div>
    </main>
  );
}

/** SentimentDistResponse satırlarını hero'nun beklediği sabit
 *  anahtar setine indirger. */
function toSentimentCounts(
  dist: { total: number; data: Array<{ label: string; count: number }> } | undefined,
): ExecutiveOverview["sentiment"] | undefined {
  if (!dist) return undefined;
  const counts: ExecutiveOverview["sentiment"] = {
    POZITIF: 0,
    NEGATIF: 0,
    "NÖTR": 0,
    total: dist.total,
  };
  for (const row of dist.data) {
    if (row.label === "POZITIF") counts.POZITIF = row.count;
    else if (row.label === "NEGATIF") counts.NEGATIF = row.count;
    else if (row.label === "NÖTR") counts["NÖTR"] = row.count;
  }
  return counts;
}
