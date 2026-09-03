"use client";

// 2026-09-03 redesign — hero-style manşet kartı + KPI kutucuk sırası.
//
// Ürün sahibi talimatı: "her şey çok fazla metin" — eski BriefingViewer
// KPI'ları büyük bir liste kartı içinde, ikonsuz düz metin olarak
// gösteriyordu (bkz. eski KpiCard). Bu bileşen ana sayfanın
// ExecutiveHero/RootCauseCards diliyle aynı örüntüyü izler: tek çarpıcı
// cümle + ikonlu kutucuklar, ayrıntı yok — her kutucuk tek sayı + tek
// etiket taşır.
//
// Metrik ikon eşlemesi satır içi tablo indekslemesi kullanır
// (`METRIC_ICONS[key]`), fonksiyondan JSX etiketi DÖNDÜRMEZ —
// lib/category-icons.ts dosya üstü notundaki react-hooks/
// static-components kısıtı burada da geçerli.

import {
  CalendarRange,
  ChartColumn,
  Gauge,
  MessageSquare,
  Smile,
  TrendingDown,
  type LucideIcon,
} from "lucide-react";

import { useTranslation } from "@/lib/i18n/use-translation";
import {
  BRIEFING_PERIOD_LABELS,
  type BriefingKpiChange,
  type ExecutiveBriefing,
} from "@/lib/types";
import { formatDateTr } from "@/lib/relative-time";

type MetricKey = "total" | "nps" | "sentiment" | "negative" | "other";

/** Backend her zaman sabit dört Türkçe etiketten birini gönderir
 *  (executive_briefing_service.py _KPI_METRICS) — UI dilinden bağımsız.
 *  Anahtarlar metin eşleşmesiyle çıkarılır, çeviri anahtarı DEĞİLDİR. */
function metricKey(label: string): MetricKey {
  if (label.includes("Toplam")) return "total";
  if (label.includes("NPS")) return "nps";
  if (label.includes("Duygu")) return "sentiment";
  if (label.includes("Negatif")) return "negative";
  return "other";
}

const METRIC_ICONS: Readonly<Record<MetricKey, LucideIcon>> = {
  total: MessageSquare,
  nps: Gauge,
  sentiment: Smile,
  negative: TrendingDown,
  other: ChartColumn,
};

type Tone = "positive" | "negative" | "neutral";

const TONE_CLASSES: Readonly<Record<Tone, { bg: string; fg: string; badge: string }>> = {
  positive: {
    bg: "bg-emerald-500/15",
    fg: "text-emerald-700 dark:text-emerald-400",
    badge: "text-emerald-700 dark:text-emerald-400",
  },
  negative: {
    bg: "bg-red-500/15",
    fg: "text-red-700 dark:text-red-400",
    badge: "text-red-700 dark:text-red-400",
  },
  neutral: {
    bg: "bg-muted",
    fg: "text-muted-foreground",
    badge: "text-muted-foreground",
  },
};

/** Ton, ham farktan (current - previous) türetilir; sunucunun
 *  `direction`/`change_pct` alanı YÜZDE üzerinden hesaplanıyor ve
 *  negatif tabanlı metriklerde yanıltıyor: ortalama duygu -0.10'dan
 *  -0.28'e düşünce yüzde +198 çıkıyor ve "yukarı" görünüyor, oysa
 *  kötüleşme. "Negatif Yorum Oranı"nda düşük iyi, diğerlerinde yüksek
 *  iyi. */
function kpiDelta(kpi: BriefingKpiChange): number {
  return kpi.current - kpi.previous;
}

function toneForKpi(kpi: BriefingKpiChange): Tone {
  const delta = kpiDelta(kpi);
  if (Math.abs(delta) < 1e-9) return "neutral";
  const lowerIsBetter = metricKey(kpi.metric) === "negative";
  const good = lowerIsBetter ? delta < 0 : delta > 0;
  return good ? "positive" : "negative";
}

function arrowFor(kpi: BriefingKpiChange): string {
  const delta = kpiDelta(kpi);
  return Math.abs(delta) < 1e-9 ? "→" : delta > 0 ? "↑" : "↓";
}

/** Duygu skoru [-1, 1] aralığında; sıfır civarı/negatif tabanda yüzde
 *  anlamsız — fark PUAN olarak gösterilir. Diğer metriklerde yüzde. */
function formatChange(kpi: BriefingKpiChange): string {
  const delta = kpiDelta(kpi);
  if (metricKey(kpi.metric) === "sentiment") {
    return `${delta >= 0 ? "+" : ""}${delta.toFixed(2)}`;
  }
  const pct = kpi.change_pct ?? 0;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

/** Yorum sayısı bir tam sayıdır — eski sürüm tüm metrikleri aynı
 *  `.toFixed(2)` ile basıyordu ("1345.00 yorum"), okunabilirlik
 *  düzeltmesi: sayım metriği tam sayı, geri kalanı iki ondalık. */
function formatCurrent(kpi: BriefingKpiChange, locale: string): string {
  if (metricKey(kpi.metric) === "total") {
    return Math.round(kpi.current).toLocaleString(locale);
  }
  return kpi.current.toFixed(2);
}

function KpiTile({ kpi, index }: { kpi: BriefingKpiChange; index: number }) {
  const { t, locale } = useTranslation();
  const Icon = METRIC_ICONS[metricKey(kpi.metric)];
  const tone = toneForKpi(kpi);
  const cls = TONE_CLASSES[tone];
  const hasChange = kpi.change_pct !== null && kpi.change_pct !== undefined;
  return (
    <div
      className="rise-in bg-muted/40 flex flex-col gap-1.5 rounded-2xl p-3.5"
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <span
        className={`inline-flex size-7 shrink-0 items-center justify-center rounded-full ${cls.bg} ${cls.fg}`}
      >
        <Icon className="size-3.5" aria-hidden />
      </span>
      <p className="text-lg font-semibold tracking-tight tabular-nums">
        {formatCurrent(kpi, locale)}
      </p>
      <p className="text-muted-foreground truncate text-xs font-medium">{kpi.metric}</p>
      <p className={`text-xs font-medium tabular-nums ${cls.badge}`}>
        {hasChange ? (
          <>
            {arrowFor(kpi)} {formatChange(kpi)}
          </>
        ) : (
          <span className="italic">{kpi.change_label ?? t("briefing.kpi.newLabel")}</span>
        )}
      </p>
    </div>
  );
}

function PeriodTile({ briefing }: { briefing: ExecutiveBriefing }) {
  const { t } = useTranslation();
  const periodLabel =
    t(`briefing.period.${briefing.period}`) || BRIEFING_PERIOD_LABELS[briefing.period];
  return (
    <div className="rise-in bg-muted/40 flex flex-col gap-1.5 rounded-2xl p-3.5">
      <span className="bg-muted text-muted-foreground inline-flex size-7 shrink-0 items-center justify-center rounded-full">
        <CalendarRange className="size-3.5" aria-hidden />
      </span>
      <p className="text-sm font-semibold tracking-tight">
        {t("briefing.hero.periodTile.range", {
          from: formatDateTr(briefing.date_from),
          to: formatDateTr(briefing.date_to),
        })}
      </p>
      <p className="text-muted-foreground truncate text-xs font-medium">
        {t("briefing.hero.periodTile.label")}: {periodLabel}
      </p>
    </div>
  );
}

export function BriefingHero({ briefing }: { briefing: ExecutiveBriefing }) {
  const { t } = useTranslation();
  return (
    <section
      className="rise-in shadow-soft bg-card ring-foreground/5 rounded-3xl p-6 ring-1 md:p-8"
      aria-label={t("briefing.hero.aria")}
    >
      <h2 className="mt-2 line-clamp-2 text-2xl leading-tight font-semibold tracking-tight text-balance md:text-3xl">
        {briefing.headline}
      </h2>

      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {briefing.kpi_changes.slice(0, 4).map((kpi, idx) => (
          <KpiTile key={kpi.metric} kpi={kpi} index={idx} />
        ))}
        <PeriodTile briefing={briefing} />
      </div>
    </section>
  );
}
