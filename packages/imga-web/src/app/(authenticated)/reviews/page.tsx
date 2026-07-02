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

import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { BatchFilterDropdown } from "@/components/reviews/batch-filter-dropdown";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useInfiniteReviews } from "@/hooks/use-reviews";
import { useCompanyTaxonomies } from "@/hooks/use-taxonomies";
import { useTranslation } from "@/lib/i18n/use-translation";
import type {
  ReviewListFilters,
  ReviewListItem,
  ReviewSourceType,
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

/**
 * Analiz Arşivi. Filter surface: sentiment, source, has_ticket,
 * batch_job_id, perspective_codes, search — all URL-bound per
 * docs/agent-rules/url-state-patterns.md.
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
    <main className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 md:px-8 md:py-10">
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
function readFiltersFromParams(params: URLSearchParams): ReviewListFilters {
  const sentimentRaw = params.get("sentiment_labels");
  const sourceRaw = params.get("source_types");
  const perspectiveRaw = params.get("perspective_codes");
  const primaryCatsRaw = params.get("primary_categories");
  const sourceTypes = sourceRaw
    ? (sourceRaw.split(",").filter(Boolean) as ReviewSourceType[])
    : undefined;
  const _int = (key: string): number | undefined => {
    const raw = params.get(key);
    if (raw === null || raw === "") return undefined;
    const n = Number(raw);
    return Number.isFinite(n) && Number.isInteger(n) ? n : undefined;
  };
  return {
    sentiment_labels: sentimentRaw?.split(",").filter(Boolean),
    source_types: sourceTypes,
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

function filtersEq(a: ReviewListFilters, b: ReviewListFilters): boolean {
  return (
    arrEq(a.sentiment_labels, b.sentiment_labels) &&
    arrEq(
      a.source_types as string[] | undefined,
      b.source_types as string[] | undefined,
    ) &&
    arrEq(a.perspective_codes, b.perspective_codes) &&
    arrEq(a.primary_categories, b.primary_categories) &&
    a.has_ticket === b.has_ticket &&
    a.batch_job_id === b.batch_job_id &&
    a.hour_of_day === b.hour_of_day &&
    a.day_of_week === b.day_of_week &&
    a.week_of_year === b.week_of_year &&
    a.month === b.month &&
    a.search === b.search
  );
}

function ReviewsPageInner() {
  const { t } = useTranslation();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Path B mirror — local state controlled by the URL but updated
  // immediately on user actions. See docs/agent-rules/url-state-patterns.md.
  const [filters, setFilters] = useState<ReviewListFilters>(() =>
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
    (next: ReviewListFilters) => {
      setFilters(next);
      const params = new URLSearchParams();
      if (next.sentiment_labels?.length) {
        params.set("sentiment_labels", next.sentiment_labels.join(","));
      }
      if (next.source_types?.length) {
        params.set("source_types", next.source_types.join(","));
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
      const qs = params.toString();
      router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router],
  );

  const reviews = useInfiniteReviews(filters, 50);
  const items = reviews.data?.pages.flatMap((p) => p.items) ?? [];
  const total = reviews.data?.pages[0]?.total ?? 0;

  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 md:px-8 md:py-10">
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

      <div className="flex flex-wrap items-center gap-2">
        <PerspectiveFilterDropdown
          selected={filters.perspective_codes ?? []}
          onApply={(next) =>
            applyFilters({
              ...filters,
              perspective_codes: next.length > 0 ? next : undefined,
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
        <FilterPills filters={filters} />
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
              <ReviewRow review={r} />
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
    </main>
  );
}

/** Tek analiz satırı — okunur, sakin kart. Metin önde; duygu sol
 *  renk şeridinde; kategori/tarih/kaynak ikincil. Tıklama → detay. */
function ReviewRow({ review: r }: { review: ReviewListItem }) {
  const { t } = useTranslation();
  const perspective =
    r.company_perspective_label_tr ??
    (r.company_perspective_code ? t("reviews.review.removed") : null);
  return (
    <Link
      href={`/reviews/${r.id}`}
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
          <span className="font-medium">{r.primary_category}</span>
          {perspective && <span>{perspective}</span>}
          <span className="tabular-nums">
            {DATE_FORMATTER.format(new Date(r.analyzed_at))}
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

function FilterPills({ filters }: { filters: ReviewListFilters }) {
  const { t } = useTranslation();
  const pills: { label: string; href: string }[] = [];
  if (filters.batch_job_id) {
    pills.push({
      label: t("reviews.pill.upload", { id: filters.batch_job_id.slice(0, 8) }),
      href: "/reviews",
    });
  }
  if (filters.sentiment_labels?.length) {
    pills.push({
      label: t("reviews.pill.sentiment", {
        value: filters.sentiment_labels
          .map((s) => (SENTIMENT_LABEL_KEYS[s] ? t(SENTIMENT_LABEL_KEYS[s]!) : s))
          .join(", "),
      }),
      href: "/reviews",
    });
  }
  if (filters.source_types?.length) {
    pills.push({
      label: t("reviews.pill.source", {
        value: filters.source_types
          .map((s) => t(SOURCE_LABEL_KEYS[s]))
          .join(", "),
      }),
      href: "/reviews",
    });
  }
  if (filters.hour_of_day !== undefined) {
    pills.push({
      label: t("reviews.pill.hour", {
        value: String(filters.hour_of_day).padStart(2, "0"),
      }),
      href: "/reviews",
    });
  }
  if (filters.day_of_week !== undefined) {
    pills.push({
      label: t("reviews.pill.day", {
        value: DOW_LABEL_KEYS[filters.day_of_week]
          ? t(DOW_LABEL_KEYS[filters.day_of_week]!)
          : filters.day_of_week,
      }),
      href: "/reviews",
    });
  }
  if (filters.week_of_year !== undefined) {
    pills.push({
      label: t("reviews.pill.week", { value: filters.week_of_year }),
      href: "/reviews",
    });
  }
  if (filters.month !== undefined) {
    pills.push({
      label: t("reviews.pill.month", {
        value: MONTH_LABEL_KEYS[filters.month]
          ? t(MONTH_LABEL_KEYS[filters.month]!)
          : filters.month,
      }),
      href: "/reviews",
    });
  }
  if (pills.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {pills.map((p) => (
        <Link
          key={p.label}
          href={p.href}
          className="bg-muted hover:bg-muted/80 text-foreground/80 inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs transition-colors"
        >
          {p.label} <span aria-hidden>×</span>
        </Link>
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
