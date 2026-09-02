"use client";

// Sprint 12 — Analiz Arşivi (sakin liste).
//
// Önceki hali 8 kolonlu yoğun tablo idi; ürün sahibi "göz korkutucu"
// buldu. Yeni hali aydınlık, okunur bir LİSTE: her analiz tek bir
// sakin kart — yorum metni önde, duygu sol kenarda renk olarak,
// kategori/tarih/kaynak ikincil ve soluk. "Aptal bile okuyabilir";
// detaya inmek isteyen karta tıklar (/reviews/[id]).
//
// URL-state filtre mantığı (Suspense + Path B mirror) AYNEN korundu —
// docs/agent-rules/url-state-patterns.md gereği değiştirilmedi.

import { ChevronDown, ChevronRight, ExternalLink, Loader2, RefreshCw } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { BatchFilterDropdown } from "@/components/reviews/batch-filter-dropdown";
import { SummaryPanel } from "@/components/reviews/summary-panel";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { DateField } from "@/components/ui/date-field";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useCategories } from "@/hooks/use-categories";
import { type DimensionValueField, useDimensionValues } from "@/hooks/use-dimension-values";
import { useReanalyzeBatchJob } from "@/hooks/use-reanalyze";
import { useRoleFlags } from "@/hooks/use-role-flags";
import {
  useInfiniteReviews,
  type ReviewDimensionFilterFields,
  type ReviewListFiltersExt,
} from "@/hooks/use-reviews";
import { useCompanyTaxonomies } from "@/hooks/use-taxonomies";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";
import { sourceLinkLabelKey } from "@/lib/source-link";
import {
  CONTENT_TYPES,
  type ContentType,
  type ReviewDecision,
  type ReviewListItem,
  type ReviewSourceType,
} from "@/lib/types";

const SOURCE_LABEL_KEYS: Record<ReviewSourceType, string> = {
  manual: "reviews.source.manual",
  batch: "reviews.source.batch",
  api: "reviews.source.api",
};

const SENTIMENT_LABEL_KEYS: Record<string, string> = {
  NEGATIF: "reviews.sentiment.negatif",
  POZITIF: "reviews.sentiment.pozitif",
  "NÖTR": "reviews.sentiment.notr",
};

const SENTIMENT_ACCENT: Record<string, string> = {
  NEGATIF: "border-l-red-400",
  POZITIF: "border-l-emerald-400",
  "NÖTR": "border-l-zinc-300",
};

const SENTIMENT_CHIP: Record<string, string> = {
  NEGATIF: "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300",
  POZITIF:
    "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
  "NÖTR": "bg-zinc-100 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-300",
};

const DATE_FORMATTER = new Intl.DateTimeFormat("tr-TR", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

/** Sentinel for the "heuristic didn't match" filter bucket. Backend
 *  recognises the same string in the perspective_codes CSV. */
const UNMATCHED_SENTINEL = "__unmatched__";

// WS5 — duygu çoklu-seçim filtresi. Aynı üç değer PerspectiveFilterDropdown
// yerine ayrı bir dropdown'da; SENTIMENT_LABEL_KEYS zaten üstte tanımlı.
const SENTIMENT_VALUES: readonly string[] = ["POZITIF", "NÖTR", "NEGATIF"];

// F1 (2026-09-02) — sıralama kontrolü. Önceden hiç UI yoktu (order_by
// yalnız use-reviews.ts'in buildQueryString'inde tanımlıydı, hiçbir
// çağıran set etmiyordu); bu görevle birlikte "engagement" (viral
// olumsuz tweet linki için) eklendi ve aynı anda ilk kez bir sıralama
// kontrolü kondu. "created_at" backend varsayılanı — URL'i kirletmemek
// için yalnız varsayılan-dışı bir değer seçiliyken yazılır.
//
// i18n notu: "reviews.*" anahtarları normalde insights.ts'de yaşıyor
// (bu sayfanın diğer tüm çevirileri orada) ama bu ajanın HARD RULE
// dosya listesi yalnız dashboard.ts'e dictionary erişimi veriyor —
// anahtarlar isim uzayı tutarlılığı için "reviews.sort.*" kaldı,
// fiziksel olarak dashboard.ts'te tanımlı (sözlükler tek bir düz
// haritaya birleşiyor, bkz. lib/i18n/dictionaries.ts).
const ORDER_BY_VALUES = ["created_at", "sentiment_score", "engagement"] as const;
type OrderByValue = (typeof ORDER_BY_VALUES)[number];
function isOrderByValue(v: string | null): v is OrderByValue {
  return v !== null && (ORDER_BY_VALUES as readonly string[]).includes(v);
}
const ORDER_BY_LABEL_KEYS: Record<OrderByValue, string> = {
  created_at: "reviews.sort.date",
  sentiment_score: "reviews.sort.sentimentScore",
  engagement: "reviews.sort.engagement",
};

// WS5 — /reviews/[id]/page.tsx ile aynı harita ("mevcut karar
// etiketleri" — lib/types.ts'teki ReviewDecision NOT'una bkz:
// backend'in yeni skipped_quality dalı bilinçli olarak dışarıda,
// çünkü union'ı genişletmek analyze/page.tsx'i kırıyor).
const DECISION_LABEL_KEYS: Record<ReviewDecision, string> = {
  create: "reviews.decision.create",
  skipped_belirsiz: "reviews.decision.skippedBelirsiz",
  skipped_mode: "reviews.decision.skippedMode",
  skipped_threshold: "reviews.decision.skippedThreshold",
  skipped_dedup: "reviews.decision.skippedDedup",
  skipped_quality: "reviews.decision.skippedQuality",
};
const DECISION_VALUES: readonly ReviewDecision[] = Object.keys(
  DECISION_LABEL_KEYS,
) as ReviewDecision[];

// Content-type filter/badge/pill label map — shared i18n keys with the
// summary panel's chip row (reviews.contentType.*). Kept Record<string,
// string> (not Record<ContentType,string>) so lookups from filters.
// content_types (a generic string[] wire value) stay safe without a
// cast; unknown codes fall back to the raw string (same convention as
// SENTIMENT_LABEL_KEYS below).
const CONTENT_TYPE_LABEL_KEYS: Record<string, string> = {
  escalation: "reviews.contentType.escalation",
  request: "reviews.contentType.request",
  question: "reviews.contentType.question",
  suggestion: "reviews.contentType.suggestion",
  thanks: "reviews.contentType.thanks",
};

// Escalation gets a warning treatment everywhere it appears (filter
// checkbox row order, list badge, summary chip) so risk pops.
const ESCALATION_BADGE_CLASS = "bg-sentiment-negative/10 text-sentiment-negative font-semibold";
const DEFAULT_BADGE_CLASS = "bg-muted text-muted-foreground";

// WS5 — "Veri kalitesi" filtresi tek-seçimli: Tümü / Yalnız geçerli /
// tekil bayrak. URL'de doğrudan backend'in iki parametresine
// (include_flagged, quality_flags) eşlenir — bkz. qualitySelectionFor /
// applyQualitySelection.
type QualitySelection = "all" | "valid_only" | string;
const QUALITY_FLAG_VALUES: readonly string[] = [
  "duplicate",
  "empty",
  "informational",
  "meaningless",
];
const QUALITY_FLAG_LABEL_KEYS: Record<string, string> = {
  duplicate: "reviews.qualityFilter.duplicate",
  empty: "reviews.qualityFilter.empty",
  informational: "reviews.qualityFilter.informational",
  meaningless: "reviews.qualityFilter.meaningless",
};

// 2026-08-20 — Boyutlar filtreleri (Ticket'ın 6 iş boyutu). ``field``
// dimension-values ucunun tekil parametresi, ``filterKey`` /reviews'in
// CSV parametresi (çoğul) + yerel ReviewListFiltersExt alanı,
// ``labelKey`` Boyutlar tab + cohort ile PAYLAŞILAN "dimensions.*"
// i18n anahtarı (görev notu: "aynı Türkçe etiketler"). Tek bir generic
// dropdown/pill bu config listesini map'ler — 6 ayrı bileşen yerine.
const DIMENSION_FILTER_CONFIGS: ReadonlyArray<{
  field: DimensionValueField;
  filterKey: keyof ReviewDimensionFilterFields;
  labelKey: string;
}> = [
  { field: "channel", filterKey: "channels", labelKey: "dimensions.channel" },
  {
    field: "business_segment",
    filterKey: "business_segments",
    labelKey: "dimensions.businessSegment",
  },
  { field: "product_line", filterKey: "product_lines", labelKey: "dimensions.productLine" },
  { field: "customer_tier", filterKey: "customer_tiers", labelKey: "dimensions.customerTier" },
  { field: "entered_by", filterKey: "entered_bys", labelKey: "dimensions.enteredBy" },
  // NOT: bu "source" bir İŞ BOYUTU (örn. Web/Mobil/Mağaza) —
  // sayfanın var olan source_types (manuel/toplu ingest yöntemi)
  // filtresinden kavramsal olarak farklı; ikisi de "Kaynak" görünebilir
  // ama ayrı filtrelerdir. Görev tanımındaki birebir eşleme
  // ("Kaynak"="source") bilinçli, isim çakışması kabul edildi.
  { field: "source", filterKey: "sources", labelKey: "dimensions.source" },
];

function qualitySelectionFor(filters: ReviewListFiltersExt): QualitySelection {
  const flag = filters.quality_flags?.[0];
  if (flag) return flag;
  if (filters.include_flagged === false) return "valid_only";
  return "all";
}

/**
 * Analiz Arşivi. Filter surface: sentiment, source, has_ticket,
 * batch_job_id, perspective_codes, decisions, quality (quality_flags +
 * include_flagged), date range (date_from/date_to), search — all
 * URL-bound per docs/agent-rules/url-state-patterns.md.
 *
 * Suspense wrapper + Path B mirror (Sprint 8.3.5.6 round-2) korunur.
 */
export default function ReviewsPage() {
  return (
    <Suspense fallback={<ReviewsPageSkeleton />}>
      <ReviewsPageInner />
    </Suspense>
  );
}

function ReviewsPageSkeleton() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto w-full max-w-7xl space-y-6 px-4 py-6 md:px-8 md:py-10">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {t("reviews.list.title")}
        </h1>
        <p className="text-muted-foreground text-sm">{t("common.loading")}</p>
      </header>
    </main>
  );
}

/** Read the URL params into one filter snapshot. Pure function off
 *  URLSearchParams so the lazy-init + the useEffect mirror share the
 *  parsing logic.
 *
 *  Sprint 9.5.1 B1.1 — 4 time-bucket params (hour_of_day, day_of_week,
 *  week_of_year, month). The /insights heatmap drilldown writes them;
 *  dropping them here changes the URL but sends the API call
 *  unfiltered. */
function readFiltersFromParams(params: URLSearchParams): ReviewListFiltersExt {
  const sentimentRaw = params.get("sentiment_labels");
  const sourceRaw = params.get("source_types");
  const perspectiveRaw = params.get("perspective_codes");
  const orderByRaw = params.get("order_by");
  const primaryCatsRaw = params.get("primary_categories");
  const decisionsRaw = params.get("decisions");
  const qualityFlagsRaw = params.get("quality_flags");
  const contentTypesRaw = params.get("content_types");
  const sourceTypes = sourceRaw
    ? (sourceRaw.split(",").filter(Boolean) as ReviewSourceType[])
    : undefined;
  const _int = (key: string): number | undefined => {
    const raw = params.get(key);
    if (raw === null || raw === "") return undefined;
    const n = Number(raw);
    return Number.isFinite(n) && Number.isInteger(n) ? n : undefined;
  };
  // 2026-08-20 — 6 boyut filtresi, tek döngüde okunuyor (bkz.
  // DIMENSION_FILTER_CONFIGS).
  const dims: ReviewDimensionFilterFields = {};
  for (const cfg of DIMENSION_FILTER_CONFIGS) {
    const vals = params.get(cfg.filterKey)?.split(",").filter(Boolean);
    if (vals?.length) dims[cfg.filterKey] = vals;
  }
  return {
    // Sprint 9.5.1'de zaten ReviewListFilters'ta duruyordu ama sayfa
    // hiç okumuyordu — /insights heatmap drilldown bu paramları
    // /reviews'e yazıyor, buraya bağlanmadan sessizce yok oluyorlardı.
    date_from: params.get("date_from") ?? undefined,
    date_to: params.get("date_to") ?? undefined,
    sentiment_labels: sentimentRaw?.split(",").filter(Boolean),
    source_types: sourceTypes,
    decisions: decisionsRaw?.split(",").filter(Boolean) as
      | ReviewDecision[]
      | undefined,
    perspective_codes: perspectiveRaw?.split(",").filter(Boolean),
    primary_categories: primaryCatsRaw?.split(",").filter(Boolean),
    has_ticket: params.has("has_ticket")
      ? params.get("has_ticket") === "true"
      : undefined,
    batch_job_id: params.get("batch_job_id") ?? undefined,
    hour_of_day: _int("hour_of_day"),
    day_of_week: _int("day_of_week"),
    week_of_year: _int("week_of_year"),
    month: _int("month"),
    search: params.get("search") ?? undefined,
    quality_flags: qualityFlagsRaw?.split(",").filter(Boolean),
    // applyFilters yalnız açık false yazar (bkz. aşağı); herhangi
    // başka bir değer varsayılana (undefined = true) düşer.
    include_flagged: params.get("include_flagged") === "false" ? false : undefined,
    // İçerik türü çoklu-seçim filtresi (bkz. CONTENT_TYPE_LABEL_KEYS) —
    // diğer CSV filtrelerle aynı desen.
    content_types: contentTypesRaw?.split(",").filter(Boolean),
    // F1 (2026-09-02) — sıralama; geçersiz/eksik değer undefined'a
    // düşer (backend "created_at" varsayılanını kullanır).
    order_by: isOrderByValue(orderByRaw) ? orderByRaw : undefined,
    ...dims,
  };
}

/** Cheap shallow-array eq for the mirror's no-op short-circuit. */
function arrEq(a: string[] | undefined, b: string[] | undefined): boolean {
  if (a === b) return true;
  if (!a || !b) return a === undefined && b === undefined;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

function filtersEq(a: ReviewListFiltersExt, b: ReviewListFiltersExt): boolean {
  return (
    a.date_from === b.date_from &&
    a.date_to === b.date_to &&
    arrEq(a.sentiment_labels, b.sentiment_labels) &&
    arrEq(
      a.source_types as string[] | undefined,
      b.source_types as string[] | undefined,
    ) &&
    arrEq(
      a.decisions as string[] | undefined,
      b.decisions as string[] | undefined,
    ) &&
    arrEq(a.perspective_codes, b.perspective_codes) &&
    arrEq(a.primary_categories, b.primary_categories) &&
    a.has_ticket === b.has_ticket &&
    a.batch_job_id === b.batch_job_id &&
    a.hour_of_day === b.hour_of_day &&
    a.day_of_week === b.day_of_week &&
    a.week_of_year === b.week_of_year &&
    a.month === b.month &&
    a.search === b.search &&
    arrEq(a.quality_flags, b.quality_flags) &&
    a.include_flagged === b.include_flagged &&
    arrEq(a.content_types, b.content_types) &&
    a.order_by === b.order_by &&
    DIMENSION_FILTER_CONFIGS.every((cfg) => arrEq(a[cfg.filterKey], b[cfg.filterKey]))
  );
}

function ReviewsPageInner() {
  const { t } = useTranslation();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Path B mirror — local state controlled by the URL but updated
  // immediately on user actions. See docs/agent-rules/url-state-patterns.md.
  const [filters, setFilters] = useState<ReviewListFiltersExt>(() =>
    readFiltersFromParams(new URLSearchParams(searchParams.toString())),
  );

  // URL → state mirror for back/forward, deep-link, F5 hydration race.
  useEffect(() => {
    const fromUrl = readFiltersFromParams(
      new URLSearchParams(searchParams.toString()),
    );
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFilters((prev) => (filtersEq(prev, fromUrl) ? prev : fromUrl));
  }, [searchParams]);

  // State-first user action: update local state immediately, then push
  // the URL so the change is shareable + back-button-able.
  const applyFilters = useCallback(
    (next: ReviewListFiltersExt) => {
      setFilters(next);
      const params = new URLSearchParams();
      if (next.date_from) params.set("date_from", next.date_from);
      if (next.date_to) params.set("date_to", next.date_to);
      if (next.sentiment_labels?.length) {
        params.set("sentiment_labels", next.sentiment_labels.join(","));
      }
      if (next.source_types?.length) {
        params.set("source_types", next.source_types.join(","));
      }
      if (next.decisions?.length) {
        params.set("decisions", next.decisions.join(","));
      }
      if (next.perspective_codes?.length) {
        params.set("perspective_codes", next.perspective_codes.join(","));
      }
      if (next.primary_categories?.length) {
        params.set("primary_categories", next.primary_categories.join(","));
      }
      if (next.has_ticket !== undefined) {
        params.set("has_ticket", String(next.has_ticket));
      }
      if (next.batch_job_id) params.set("batch_job_id", next.batch_job_id);
      if (next.hour_of_day !== undefined) {
        params.set("hour_of_day", String(next.hour_of_day));
      }
      if (next.day_of_week !== undefined) {
        params.set("day_of_week", String(next.day_of_week));
      }
      if (next.week_of_year !== undefined) {
        params.set("week_of_year", String(next.week_of_year));
      }
      if (next.month !== undefined) {
        params.set("month", String(next.month));
      }
      if (next.search) params.set("search", next.search);
      // Veri kalitesi tek-seçim: bayrak varsa quality_flags CSV
      // (tek eleman), yoksa yalnız include_flagged=false ("yalnız
      // geçerli") URL'e yazılır — "Tümü" varsayılan, iz bırakmaz.
      if (next.quality_flags?.length) {
        params.set("quality_flags", next.quality_flags.join(","));
      } else if (next.include_flagged === false) {
        params.set("include_flagged", "false");
      }
      if (next.content_types?.length) {
        params.set("content_types", next.content_types.join(","));
      }
      // F1 (2026-09-02) — sıralama; "created_at" backend varsayılanı,
      // URL'i kirletmemek için yalnız varsayılan-dışı yazılır.
      if (next.order_by && next.order_by !== "created_at") {
        params.set("order_by", next.order_by);
      }
      // 2026-08-20 — 6 boyut filtresi, tek döngüde yazılıyor.
      for (const cfg of DIMENSION_FILTER_CONFIGS) {
        const vals = next[cfg.filterKey];
        if (vals?.length) params.set(cfg.filterKey, vals.join(","));
      }
      const qs = params.toString();
      router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router],
  );

  /** Veri kalitesi dropdown'ının tek-seçim durumu → filters iki alanı
   *  birlikte set eder (mutually exclusive). */
  const applyQualitySelection = useCallback(
    (selection: QualitySelection) => {
      if (selection === "all") {
        applyFilters({
          ...filters,
          quality_flags: undefined,
          include_flagged: undefined,
        });
      } else if (selection === "valid_only") {
        applyFilters({
          ...filters,
          quality_flags: undefined,
          include_flagged: false,
        });
      } else {
        applyFilters({
          ...filters,
          quality_flags: [selection],
          include_flagged: undefined,
        });
      }
    },
    [filters, applyFilters],
  );

  const reviews = useInfiniteReviews(filters, 50);
  const items = reviews.data?.pages.flatMap((p) => p.items) ?? [];
  const total = reviews.data?.pages[0]?.total ?? 0;

  // F2 (2026-09-01) — aktif yükleme filtresini yeniden analiz eder.
  // Aynı hook + i18n anahtarları Geçmiş Yüklemeler sayfasıyla (bkz.
  // analyze/upload/history/page.tsx) paylaşılır — "aynı onay + toast
  // deseni" görev notu. confirmDesc'teki {count} bu listenin GÜNCEL
  // FİLTRELİ toplamı — batch job'ın tüm succeeded_rows'u değil (diğer
  // filtreler de aktifse tam sayı olmayabilir); yine de kullanıcıya
  // kabaca ölçek fikri verir.
  const { isAdmin } = useRoleFlags();
  const reanalyzeBatch = useReanalyzeBatchJob();
  const [reanalyzeBatchOpen, setReanalyzeBatchOpen] = useState(false);

  function handleReanalyzeBatchConfirm() {
    if (!filters.batch_job_id) return;
    reanalyzeBatch.mutate(filters.batch_job_id, {
      onSuccess: () => {
        toast.success(t("analyze.history.reanalyze.queued"));
        setReanalyzeBatchOpen(false);
        void reviews.refetch();
      },
      onError: (err) => {
        if (err instanceof ApiError && err.status === 403) {
          toast.error(t("analyze.history.reanalyze.noPermission"));
          return;
        }
        toast.error(t("analyze.history.reanalyze.failed"));
      },
    });
  }

  return (
    <main className="mx-auto w-full max-w-7xl space-y-6 px-4 py-6 md:px-8 md:py-10">
      <header className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {t("reviews.list.title")}
        </h1>
        <p className="text-muted-foreground text-sm">
          {filters.batch_job_id
            ? t("reviews.list.subtitleBatch")
            : t("reviews.list.subtitleAll")}{" "}
          {total > 0 && (
            <span className="text-foreground/70 font-medium tabular-nums">
              {t("reviews.list.recordCount", {
                count: total.toLocaleString("tr-TR"),
              })}
            </span>
          )}
        </p>
      </header>

      {/* W3 — sol: filtreler + liste (davranış AYNEN korunur); sağ:
          filtreye tepki veren özet paneli. Mobilde grid devre dışı,
          DOM sırası zaten panel-liste-sonra verir (order-* gerekmez).
          Panelin lg:sticky'si çalışır çünkü app-shell içerik bölmesi
          kendi overflow-y-auto'sunu taşıyor (bkz. app-shell.tsx). */}
      <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start lg:gap-6">
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <SentimentFilterDropdown
              selected={filters.sentiment_labels ?? []}
              onApply={(next) =>
                applyFilters({
                  ...filters,
                  sentiment_labels: next.length > 0 ? next : undefined,
                })
              }
            />
            <PerspectiveFilterDropdown
              selected={filters.perspective_codes ?? []}
              onApply={(next) =>
                applyFilters({
                  ...filters,
                  perspective_codes: next.length > 0 ? next : undefined,
                })
              }
            />
            <DecisionsFilterDropdown
              selected={filters.decisions ?? []}
              onApply={(next) =>
                applyFilters({
                  ...filters,
                  decisions: next.length > 0 ? (next as ReviewDecision[]) : undefined,
                })
              }
            />
            <QualityFilterDropdown
              selected={qualitySelectionFor(filters)}
              onApply={applyQualitySelection}
            />
            <ContentTypeFilterDropdown
              selected={filters.content_types ?? []}
              onApply={(next) =>
                applyFilters({ ...filters, content_types: next.length > 0 ? next : undefined })
              }
            />
            {DIMENSION_FILTER_CONFIGS.map((cfg) => (
              <DimensionFilterDropdown
                key={cfg.field}
                field={cfg.field}
                labelKey={cfg.labelKey}
                selected={filters[cfg.filterKey] ?? []}
                onApply={(next) =>
                  applyFilters({
                    ...filters,
                    [cfg.filterKey]: next.length > 0 ? next : undefined,
                  })
                }
              />
            ))}
            <DateRangeFilter
              dateFrom={filters.date_from ?? ""}
              dateTo={filters.date_to ?? ""}
              onChange={(dateFrom, dateTo) =>
                applyFilters({
                  ...filters,
                  date_from: dateFrom || undefined,
                  date_to: dateTo || undefined,
                })
              }
            />
            <BatchFilterDropdown
              selected={filters.batch_job_id}
              onChange={(next) =>
                applyFilters({ ...filters, batch_job_id: next ?? undefined })
              }
              inline
            />
            {/* Yeniden analiz uçları _TenantAdmin — düğmeyi analiste
                gösterip 403 yedirmemek için isAdmin. */}
            {filters.batch_job_id && isAdmin && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-1.5"
                onClick={() => setReanalyzeBatchOpen(true)}
                disabled={reanalyzeBatch.isPending}
              >
                <RefreshCw className="size-3.5" aria-hidden />
                {t("reviews.list.reanalyzeBatch")}
              </Button>
            )}
            {/* F1 (2026-09-02) — sıralama kontrolü. */}
            <OrderByFilterDropdown
              selected={filters.order_by ?? "created_at"}
              onApply={(next) => applyFilters({ ...filters, order_by: next })}
            />
            <FilterPills filters={filters} onApply={applyFilters} />
          </div>

          {reviews.isLoading ? (
            <div className="text-muted-foreground flex items-center gap-2 p-6 text-sm">
              <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
            </div>
          ) : items.length === 0 ? (
            <div className="bg-card ring-foreground/5 rounded-3xl p-10 text-center ring-1">
              <p className="text-base font-medium">{t("reviews.list.emptyTitle")}</p>
              <p className="text-muted-foreground mt-1 text-sm">
                {t("reviews.list.emptyHint")}
              </p>
            </div>
          ) : (
            <ul className="space-y-2.5">
              {items.map((r) => (
                <li key={r.id}>
                  <ReviewRow review={r} listQuery={searchParams.toString()} />
                </li>
              ))}
            </ul>
          )}

          {reviews.hasNextPage && (
            <div className="flex justify-center">
              <Button
                variant="outline"
                onClick={() => reviews.fetchNextPage()}
                disabled={reviews.isFetchingNextPage}
              >
                {reviews.isFetchingNextPage
                  ? t("common.loading")
                  : t("reviews.list.loadMore")}
              </Button>
            </div>
          )}
        </div>

        {/* Panel viewport'tan uzunsa alt blokları (sorular, kalite) kendi
            scroll'uyla erişilebilir kalır — sayfa scroll'una karışmaz. */}
        <div className="mt-6 lg:sticky lg:top-6 lg:mt-0 lg:max-h-[calc(100dvh-3rem)] lg:overflow-y-auto lg:overscroll-contain lg:pr-1">
          <SummaryPanel filters={filters} />
        </div>
      </div>

      <AlertDialog open={reanalyzeBatchOpen} onOpenChange={setReanalyzeBatchOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("analyze.history.reanalyze.confirmTitle")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("analyze.history.reanalyze.confirmDesc", { count: total })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={reanalyzeBatch.isPending}>
              {t("analyze.history.reanalyze.cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleReanalyzeBatchConfirm}
              disabled={reanalyzeBatch.isPending}
            >
              {reanalyzeBatch.isPending
                ? t("analyze.history.reanalyze.submitting")
                : t("analyze.history.reanalyze.confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </main>
  );
}

/** Tek analiz satırı — okunur, sakin kart. Metin önde; duygu sol
 *  renk şeridinde; kategori/tarih/kaynak ikincil. Tıklama → detay.
 *  listQuery: aktif filtre query-string'i detay URL'ine taşınır ki
 *  "Listeye dön" filtreleri geri getirebilsin. */
function ReviewRow({
  review: r,
  listQuery,
}: {
  review: ReviewListItem;
  listQuery: string;
}) {
  const { t } = useTranslation();
  // Ham BERT kodu (kargo_teslimat) yerine kurum sözlüğündeki etiket;
  // sorgu tek anahtar altında cache'lenir, satır başına maliyet yok.
  const categories = useCategories();
  const categoryLabel =
    categories.data?.find((c) => c.code === r.primary_category)?.label_tr ??
    r.primary_category;
  const perspective =
    r.company_perspective_label_tr ??
    (r.company_perspective_code ? t("reviews.review.removed") : null);
  return (
    <Link
      href={`/reviews/${r.id}${listQuery ? `?${listQuery}` : ""}`}
      className={`hover-lift shadow-soft bg-card ring-foreground/5 group flex items-start gap-4 rounded-2xl border-l-2 p-4 ring-1 md:p-5 ${SENTIMENT_ACCENT[r.sentiment_label] ?? "border-l-zinc-300"}`}
    >
      <div className="min-w-0 flex-1">
        <p className="text-foreground/90 line-clamp-2 text-sm leading-relaxed [overflow-wrap:anywhere] md:text-base">
          {r.text}
        </p>
        <div className="text-muted-foreground mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 font-semibold ${SENTIMENT_CHIP[r.sentiment_label] ?? ""}`}
          >
            {SENTIMENT_LABEL_KEYS[r.sentiment_label]
              ? t(SENTIMENT_LABEL_KEYS[r.sentiment_label]!)
              : r.sentiment_label}
          </span>
          {r.content_type && (
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 font-medium ${
                r.content_type === "escalation" ? ESCALATION_BADGE_CLASS : DEFAULT_BADGE_CLASS
              }`}
            >
              {CONTENT_TYPE_LABEL_KEYS[r.content_type]
                ? t(CONTENT_TYPE_LABEL_KEYS[r.content_type]!)
                : r.content_type}
            </span>
          )}
          <span className="font-medium">{categoryLabel}</span>
          {perspective && <span>{perspective}</span>}
          <span className="tabular-nums">
            {DATE_FORMATTER.format(new Date(r.review_date))}
          </span>
          <span>{t(SOURCE_LABEL_KEYS[r.source_type])}</span>
          {r.ticket_id && (
            <span className="text-primary font-medium">
              {t("reviews.review.hasTicket")}
            </span>
          )}
          {r.override_count > 0 && (
            <span className="text-amber-700 dark:text-amber-400">
              {t("reviews.review.corrected")}
            </span>
          )}
          {r.source_url && (
            // Kart bir <Link>; düğme yeni sekmede kaynağı açar ve kartın
            // detay navigasyonunu bastırır (preventDefault + stopPropagation).
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                window.open(r.source_url ?? "", "_blank", "noopener,noreferrer");
              }}
              className="border-border text-foreground/80 hover:bg-muted hover:text-foreground inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium transition-colors"
              title={r.source_url}
            >
              <ExternalLink className="size-3" aria-hidden />
              {t(sourceLinkLabelKey(r.source_url))}
            </button>
          )}
        </div>
      </div>
      <ChevronRight
        className="text-muted-foreground/40 group-hover:text-foreground mt-0.5 size-5 shrink-0 transition-colors"
        aria-hidden
      />
    </Link>
  );
}

// Sprint 9.5.1 B1.1 — labels for heatmap drilldown time-bucket pills.
// Postgres DOW convention: 0=Sunday ... 6=Saturday.
const DOW_LABEL_KEYS: Record<number, string> = {
  0: "reviews.dow.0",
  1: "reviews.dow.1",
  2: "reviews.dow.2",
  3: "reviews.dow.3",
  4: "reviews.dow.4",
  5: "reviews.dow.5",
  6: "reviews.dow.6",
};
const MONTH_LABEL_KEYS: Record<number, string> = {
  1: "reviews.month.1", 2: "reviews.month.2", 3: "reviews.month.3",
  4: "reviews.month.4", 5: "reviews.month.5", 6: "reviews.month.6",
  7: "reviews.month.7", 8: "reviews.month.8", 9: "reviews.month.9",
  10: "reviews.month.10", 11: "reviews.month.11", 12: "reviews.month.12",
};

/** Aktif filtrelerin özet rozetleri. Her rozetin "×"i YALNIZ o
 *  filtreyi temizler — kalan filtreler korunarak applyFilters'a
 *  yeniden geçilir (önceki sürüm hepsini fixed href="/reviews" ile
 *  siliyordu, bkz. WS5 plan notu). */
function FilterPills({
  filters,
  onApply,
}: {
  filters: ReviewListFiltersExt;
  onApply: (next: ReviewListFiltersExt) => void;
}) {
  const { t } = useTranslation();
  const pills: { label: string; remove: () => void }[] = [];
  // 2026-08-20 — 6 boyut filtresi pill'i (tek şablon, bkz.
  // DIMENSION_FILTER_CONFIGS).
  for (const cfg of DIMENSION_FILTER_CONFIGS) {
    const vals = filters[cfg.filterKey];
    if (vals?.length) {
      pills.push({
        label: t("reviews.pill.dimension", { label: t(cfg.labelKey), value: vals.join(", ") }),
        remove: () => onApply({ ...filters, [cfg.filterKey]: undefined }),
      });
    }
  }
  if (filters.batch_job_id) {
    pills.push({
      label: t("reviews.pill.upload", { id: filters.batch_job_id.slice(0, 8) }),
      remove: () => onApply({ ...filters, batch_job_id: undefined }),
    });
  }
  if (filters.sentiment_labels?.length) {
    pills.push({
      label: t("reviews.pill.sentiment", {
        value: filters.sentiment_labels
          .map((s) => (SENTIMENT_LABEL_KEYS[s] ? t(SENTIMENT_LABEL_KEYS[s]!) : s))
          .join(", "),
      }),
      remove: () => onApply({ ...filters, sentiment_labels: undefined }),
    });
  }
  if (filters.source_types?.length) {
    pills.push({
      label: t("reviews.pill.source", {
        value: filters.source_types
          .map((s) => t(SOURCE_LABEL_KEYS[s]))
          .join(", "),
      }),
      remove: () => onApply({ ...filters, source_types: undefined }),
    });
  }
  if (filters.decisions?.length) {
    pills.push({
      label: t("reviews.pill.decisions", {
        value: filters.decisions
          .map((d) => (DECISION_LABEL_KEYS[d] ? t(DECISION_LABEL_KEYS[d]) : d))
          .join(", "),
      }),
      remove: () => onApply({ ...filters, decisions: undefined }),
    });
  }
  if (filters.quality_flags?.length) {
    const flag = filters.quality_flags[0]!;
    pills.push({
      label: t("reviews.pill.quality", {
        value: QUALITY_FLAG_LABEL_KEYS[flag]
          ? t(QUALITY_FLAG_LABEL_KEYS[flag]!)
          : flag,
      }),
      remove: () => onApply({ ...filters, quality_flags: undefined }),
    });
  } else if (filters.include_flagged === false) {
    pills.push({
      label: t("reviews.pill.validOnly"),
      remove: () => onApply({ ...filters, include_flagged: undefined }),
    });
  }
  // Her seçili içerik türü kendi rozetini alır (tek toplu pill değil):
  // "×" yalnız o türü listeden çıkarır, kalan seçimler URL'de durur.
  for (const ct of filters.content_types ?? []) {
    pills.push({
      label: CONTENT_TYPE_LABEL_KEYS[ct] ? t(CONTENT_TYPE_LABEL_KEYS[ct]!) : ct,
      remove: () => {
        const remaining = (filters.content_types ?? []).filter((c) => c !== ct);
        onApply({ ...filters, content_types: remaining.length > 0 ? remaining : undefined });
      },
    });
  }
  if (filters.date_from || filters.date_to) {
    pills.push({
      label: t("reviews.pill.dateRange", {
        from: filters.date_from ?? "…",
        to: filters.date_to ?? "…",
      }),
      remove: () =>
        onApply({ ...filters, date_from: undefined, date_to: undefined }),
    });
  }
  if (filters.hour_of_day !== undefined) {
    pills.push({
      label: t("reviews.pill.hour", {
        value: String(filters.hour_of_day).padStart(2, "0"),
      }),
      remove: () => onApply({ ...filters, hour_of_day: undefined }),
    });
  }
  if (filters.day_of_week !== undefined) {
    pills.push({
      label: t("reviews.pill.day", {
        value: DOW_LABEL_KEYS[filters.day_of_week]
          ? t(DOW_LABEL_KEYS[filters.day_of_week]!)
          : filters.day_of_week,
      }),
      remove: () => onApply({ ...filters, day_of_week: undefined }),
    });
  }
  if (filters.week_of_year !== undefined) {
    pills.push({
      label: t("reviews.pill.week", { value: filters.week_of_year }),
      remove: () => onApply({ ...filters, week_of_year: undefined }),
    });
  }
  if (filters.month !== undefined) {
    pills.push({
      label: t("reviews.pill.month", {
        value: MONTH_LABEL_KEYS[filters.month]
          ? t(MONTH_LABEL_KEYS[filters.month]!)
          : filters.month,
      }),
      remove: () => onApply({ ...filters, month: undefined }),
    });
  }
  if (pills.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {pills.map((p) => (
        <button
          key={p.label}
          type="button"
          onClick={p.remove}
          aria-label={t("reviews.pill.removeAria", { label: p.label })}
          className="bg-muted hover:bg-muted/80 text-foreground/80 inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs transition-colors"
        >
          {p.label} <span aria-hidden>×</span>
        </button>
      ))}
    </div>
  );
}

/** Multi-select dropdown driven by ``GET /tenants/me/taxonomies`` plus
 *  the ``__unmatched__`` sentinel. Controlled primitive — ``selected``
 *  flows in from the parent's mirror state, ``onApply`` flows out and
 *  the parent owns local state + URL push (Path B mirror). */
function PerspectiveFilterDropdown({
  selected,
  onApply,
}: {
  selected: string[];
  onApply: (next: string[]) => void;
}) {
  const { t } = useTranslation();
  const taxonomies = useCompanyTaxonomies();

  const toggle = useCallback(
    (code: string) => {
      const next = selected.includes(code)
        ? selected.filter((c) => c !== code)
        : [...selected, code];
      onApply(next);
    },
    [selected, onApply],
  );

  const items = taxonomies.data ?? [];
  const triggerLabel =
    selected.length === 0
      ? t("reviews.perspFilter.trigger")
      : t("reviews.perspFilter.selected", { count: selected.length });

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="outline" size="sm" className="gap-1">
            {triggerLabel}
            <ChevronDown className="size-4" aria-hidden />
          </Button>
        }
      />
      {/* Sprint 8.3.5.6 round-1 — DropdownMenuLabel removed (Base UI
          requires GroupLabel inside a Menu.Group, else error #31). */}
      <DropdownMenuContent
        align="start"
        className="max-h-80 w-64 overflow-y-auto"
      >
        <DropdownMenuCheckboxItem
          checked={selected.includes(UNMATCHED_SENTINEL)}
          onCheckedChange={() => toggle(UNMATCHED_SENTINEL)}
        >
          <span className="text-muted-foreground italic">
            {t("reviews.perspFilter.unmatched")}
          </span>
        </DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        {taxonomies.isLoading ? (
          <div className="text-muted-foreground px-2 py-1.5 text-xs">
            {t("common.loading")}
          </div>
        ) : items.length === 0 ? (
          <div className="text-muted-foreground px-2 py-1.5 text-xs">
            {t("reviews.perspFilter.noTaxonomy")}
          </div>
        ) : (
          items.map((tax) => (
            <DropdownMenuCheckboxItem
              key={tax.code}
              checked={selected.includes(tax.code)}
              onCheckedChange={() => toggle(tax.code)}
            >
              {tax.label_tr}
            </DropdownMenuCheckboxItem>
          ))
        )}
        {selected.length > 0 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => onApply([])}
              className="text-muted-foreground text-xs"
            >
              {t("reviews.perspFilter.clearAll")}
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** WS5 — duygu çoklu-seçim filtresi. PerspectiveFilterDropdown ile
 *  aynı controlled desen: ``selected`` ebeveynin mirror state'inden
 *  gelir, ``onApply`` geri döner (ebeveyn URL push'unu yönetir). */
function SentimentFilterDropdown({
  selected,
  onApply,
}: {
  selected: string[];
  onApply: (next: string[]) => void;
}) {
  const { t } = useTranslation();

  const toggle = useCallback(
    (value: string) => {
      const next = selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value];
      onApply(next);
    },
    [selected, onApply],
  );

  const triggerLabel =
    selected.length === 0
      ? t("reviews.sentimentFilter.trigger")
      : t("reviews.sentimentFilter.selected", { count: selected.length });

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="outline" size="sm" className="gap-1">
            {triggerLabel}
            <ChevronDown className="size-4" aria-hidden />
          </Button>
        }
      />
      <DropdownMenuContent align="start" className="w-48">
        {SENTIMENT_VALUES.map((value) => (
          <DropdownMenuCheckboxItem
            key={value}
            checked={selected.includes(value)}
            onCheckedChange={() => toggle(value)}
          >
            {SENTIMENT_LABEL_KEYS[value] ? t(SENTIMENT_LABEL_KEYS[value]!) : value}
          </DropdownMenuCheckboxItem>
        ))}
        {selected.length > 0 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => onApply([])}
              className="text-muted-foreground text-xs"
            >
              {t("reviews.perspFilter.clearAll")}
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** WS5 — mevcut karar etiketleri (reviews/[id]/page.tsx ile aynı
 *  DECISION_LABEL_KEYS haritası) üzerinden çoklu-seçim filtresi. */
function DecisionsFilterDropdown({
  selected,
  onApply,
}: {
  selected: string[];
  onApply: (next: string[]) => void;
}) {
  const { t } = useTranslation();

  const toggle = useCallback(
    (value: string) => {
      const next = selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value];
      onApply(next);
    },
    [selected, onApply],
  );

  const triggerLabel =
    selected.length === 0
      ? t("reviews.decisionsFilter.trigger")
      : t("reviews.decisionsFilter.selected", { count: selected.length });

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="outline" size="sm" className="gap-1">
            {triggerLabel}
            <ChevronDown className="size-4" aria-hidden />
          </Button>
        }
      />
      <DropdownMenuContent align="start" className="w-64">
        {DECISION_VALUES.map((value) => (
          <DropdownMenuCheckboxItem
            key={value}
            checked={selected.includes(value)}
            onCheckedChange={() => toggle(value)}
          >
            {t(DECISION_LABEL_KEYS[value])}
          </DropdownMenuCheckboxItem>
        ))}
        {selected.length > 0 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => onApply([])}
              className="text-muted-foreground text-xs"
            >
              {t("reviews.perspFilter.clearAll")}
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** WS5 — "Veri kalitesi" tek-seçim filtresi. Backend'in iki ayrı
 *  parametresini (include_flagged, quality_flags) tek bir radio-grup
 *  gibi sunar — bkz. qualitySelectionFor / applyQualitySelection. */
function QualityFilterDropdown({
  selected,
  onApply,
}: {
  selected: QualitySelection;
  onApply: (next: QualitySelection) => void;
}) {
  const { t } = useTranslation();

  const triggerLabel =
    selected === "all"
      ? t("reviews.qualityFilter.trigger")
      : selected === "valid_only"
        ? t("reviews.qualityFilter.validOnly")
        : QUALITY_FLAG_LABEL_KEYS[selected]
          ? t(QUALITY_FLAG_LABEL_KEYS[selected]!)
          : selected;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="outline" size="sm" className="gap-1">
            {triggerLabel}
            <ChevronDown className="size-4" aria-hidden />
          </Button>
        }
      />
      <DropdownMenuContent align="start" className="w-56">
        <DropdownMenuRadioGroup
          value={selected}
          onValueChange={(v) => v && onApply(v as QualitySelection)}
        >
          <DropdownMenuRadioItem value="all" closeOnClick>
            {t("reviews.qualityFilter.trigger")}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="valid_only" closeOnClick>
            {t("reviews.qualityFilter.validOnly")}
          </DropdownMenuRadioItem>
          <DropdownMenuSeparator />
          {QUALITY_FLAG_VALUES.map((flag) => (
            <DropdownMenuRadioItem key={flag} value={flag} closeOnClick>
              {t(QUALITY_FLAG_LABEL_KEYS[flag]!)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** F1 (2026-09-02) — sıralama kontrolü. QualityFilterDropdown ile AYNI
 *  tek-seçim radio-group deseni; farkı, her zaman bir değeri seçili
 *  olması (kapatılamaz "Tümü" seçeneği yok — sıralama zorunlu bir
 *  varsayılana sahip). */
function OrderByFilterDropdown({
  selected,
  onApply,
}: {
  selected: OrderByValue;
  onApply: (next: OrderByValue) => void;
}) {
  const { t } = useTranslation();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="outline" size="sm" className="gap-1">
            {t("reviews.sort.trigger", { value: t(ORDER_BY_LABEL_KEYS[selected]) })}
            <ChevronDown className="size-4" aria-hidden />
          </Button>
        }
      />
      <DropdownMenuContent align="start" className="w-48">
        <DropdownMenuRadioGroup
          value={selected}
          onValueChange={(v) => {
            if (isOrderByValue(v)) onApply(v);
          }}
        >
          {ORDER_BY_VALUES.map((value) => (
            <DropdownMenuRadioItem key={value} value={value} closeOnClick>
              {t(ORDER_BY_LABEL_KEYS[value])}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** İçerik türü çoklu-seçim filtresi. SentimentFilterDropdown /
 *  DecisionsFilterDropdown ile AYNI controlled desen. QualityFilter
 *  Dropdown'dan KASITLI olarak ayrı bileşen — content_type kalite
 *  bayrağı değil (bkz. ReviewListFilters.content_types yorumu), iki
 *  filtre birlikte de seçilebilir. Sıralama CONTENT_TYPES'tan gelir
 *  (risk — escalation — ilk sırada). */
function ContentTypeFilterDropdown({
  selected,
  onApply,
}: {
  selected: string[];
  onApply: (next: string[]) => void;
}) {
  const { t } = useTranslation();

  const toggle = useCallback(
    (value: ContentType) => {
      const next = selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value];
      onApply(next);
    },
    [selected, onApply],
  );

  const triggerLabel =
    selected.length === 0
      ? t("reviews.filter.contentTypes")
      : t("reviews.filter.contentTypesSelected", { count: selected.length });

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="outline" size="sm" className="gap-1">
            {triggerLabel}
            <ChevronDown className="size-4" aria-hidden />
          </Button>
        }
      />
      <DropdownMenuContent align="start" className="w-56">
        {CONTENT_TYPES.map((value) => (
          <DropdownMenuCheckboxItem
            key={value}
            checked={selected.includes(value)}
            onCheckedChange={() => toggle(value)}
          >
            {t(CONTENT_TYPE_LABEL_KEYS[value]!)}
          </DropdownMenuCheckboxItem>
        ))}
        {selected.length > 0 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => onApply([])}
              className="text-muted-foreground text-xs"
            >
              {t("reviews.perspFilter.clearAll")}
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** 2026-08-20 — Boyutlar filtresi. PerspectiveFilterDropdown /
 *  SentimentFilterDropdown ile aynı controlled çoklu-seçim deseni;
 *  6 boyut TEK bileşeni paylaşır (DIMENSION_FILTER_CONFIGS ile
 *  parametrize edilir) — 6 ayrı kopya yerine. Değer listesi
 *  use-dimension-values'tan gelir; sonuç boşsa (yükleme bittiyse)
 *  dropdown TAMAMEN GİZLENİR — görev notu "yalnız değeri olan boyutlar
 *  gösterilir". */
function DimensionFilterDropdown({
  field,
  labelKey,
  selected,
  onApply,
}: {
  field: DimensionValueField;
  labelKey: string;
  selected: string[];
  onApply: (next: string[]) => void;
}) {
  const { t } = useTranslation();
  const values = useDimensionValues(field);

  const toggle = useCallback(
    (value: string) => {
      const next = selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value];
      onApply(next);
    },
    [selected, onApply],
  );

  const rows = values.data?.values ?? [];
  if (values.isLoading || rows.length === 0) return null;

  const dimLabel = t(labelKey);
  const triggerLabel =
    selected.length === 0
      ? dimLabel
      : t("dimensions.filterSelected", { label: dimLabel, count: selected.length });

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="outline" size="sm" className="gap-1">
            {triggerLabel}
            <ChevronDown className="size-4" aria-hidden />
          </Button>
        }
      />
      <DropdownMenuContent align="start" className="max-h-80 w-64 overflow-y-auto">
        {rows.map((row) => (
          <DropdownMenuCheckboxItem
            key={row.value}
            checked={selected.includes(row.value)}
            onCheckedChange={() => toggle(row.value)}
          >
            {row.value}
          </DropdownMenuCheckboxItem>
        ))}
        {selected.length > 0 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => onApply([])}
              className="text-muted-foreground text-xs"
            >
              {t("reviews.perspFilter.clearAll")}
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** WS5 — tarih aralığı filtresi. Dashboard'daki DashboardFilterBar'ın
 *  DateField ikilisiyle aynı desen; date_from > date_to durumunu
 *  native min/max ile engeller. YYYY-MM-DD taşır (url-state-patterns.md). */
function DateRangeFilter({
  dateFrom,
  dateTo,
  onChange,
}: {
  dateFrom: string;
  dateTo: string;
  onChange: (dateFrom: string, dateTo: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="flex items-center gap-1.5"
      role="group"
      aria-label={t("reviews.dateFilter.groupAria")}
    >
      <DateField
        value={dateFrom}
        max={dateTo || undefined}
        aria-label={t("reviews.dateFilter.fromAria")}
        onChange={(e) => onChange(e.target.value, dateTo)}
      />
      <span className="text-muted-foreground text-xs" aria-hidden>
        –
      </span>
      <DateField
        value={dateTo}
        min={dateFrom || undefined}
        aria-label={t("reviews.dateFilter.toAria")}
        onChange={(e) => onChange(dateFrom, e.target.value)}
      />
    </div>
  );
}
