"use client";

import { ChevronDown, Loader2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { BatchFilterDropdown } from "@/components/reviews/batch-filter-dropdown";
import { OverrideChip } from "@/components/reviews/override-display";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useInfiniteReviews } from "@/hooks/use-reviews";
import { useCompanyTaxonomies } from "@/hooks/use-taxonomies";
import type { ReviewListFilters, ReviewSourceType } from "@/lib/types";
import { cn } from "@/lib/utils";

const SOURCE_LABELS: Record<ReviewSourceType, string> = {
  manual: "Manuel",
  batch: "Toplu",
  api: "API",
};

/** Sentinel for the "heuristic didn't match" filter bucket. Backend
 *  recognises the same string in the perspective_codes CSV. */
const UNMATCHED_SENTINEL = "__unmatched__";

/**
 * Reviews list. Filter surface: sentiment, source, has_ticket,
 * batch_job_id, perspective_codes, search — all URL-bound per
 * docs/agent-rules/url-state-patterns.md.
 *
 * Sprint 8.3.5.6 round-2: Suspense wrapper + Path B mirror added.
 * Round-1 used `useSearchParams + useMemo` directly on the page, which
 * lost filter state on F5 (Next.js 16 hydration race + no mirror to
 * keep the dropdown's checked state in sync after the URL → memo
 * round-trip).
 */
export default function ReviewsPage() {
  return (
    <Suspense fallback={<ReviewsPageSkeleton />}>
      <ReviewsPageInner />
    </Suspense>
  );
}

function ReviewsPageSkeleton() {
  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">Analizler</h1>
        <p className="text-muted-foreground text-sm">Yükleniyor…</p>
      </header>
    </main>
  );
}

/** Read the URL params into one filter snapshot. Pure function off
 *  URLSearchParams so the lazy-init + the useEffect mirror share the
 *  parsing logic.
 *
 *  Sprint 9.5.1 B1.1 — added 4 time-bucket params (hour_of_day,
 *  day_of_week, week_of_year, month). The /insights heatmap
 *  drilldown writes one or two of these on a cell click; if this
 *  parser drops them, the URL changes but the API call still goes
 *  out unfiltered — symptom seen in production smoke 2026-05-12. */
function readFiltersFromParams(params: URLSearchParams): ReviewListFilters {
  const sentimentRaw = params.get("sentiment_labels");
  const sourceRaw = params.get("source_types");
  const perspectiveRaw = params.get("perspective_codes");
  const primaryCatsRaw = params.get("primary_categories");
  const sourceTypes = sourceRaw
    ? (sourceRaw.split(",").filter(Boolean) as ReviewSourceType[])
    : undefined;
  // Parse a bounded integer URL param or return undefined. Returning
  // undefined for NaN keeps the filter object stable so filtersEq
  // doesn't churn on garbage URLs.
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
    has_ticket: params.has("has_ticket") ? params.get("has_ticket") === "true" : undefined,
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
    arrEq(a.source_types as string[] | undefined, b.source_types as string[] | undefined) &&
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
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Path B mirror — local state controlled by the URL but updated
  // immediately on user actions. See docs/agent-rules/url-state-patterns.md.
  const [filters, setFilters] = useState<ReviewListFilters>(() =>
    readFiltersFromParams(new URLSearchParams(searchParams.toString())),
  );

  // URL → state mirror for back/forward, deep-link, F5 hydration race.
  // INTENT: URL is source of truth; mirror onto local state on
  // navigation events. Path B pattern (Sprint 8.3.4 round-2,
  // Sprint 8.3.5.6 round-2 for /reviews).
  useEffect(() => {
    const fromUrl = readFiltersFromParams(new URLSearchParams(searchParams.toString()));
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFilters((prev) => (filtersEq(prev, fromUrl) ? prev : fromUrl));
  }, [searchParams]);

  // State-first user action: update local state immediately (controlled
  // primitives stay responsive even if useSearchParams' reactivity
  // glitches), then push the URL so the change is shareable +
  // back-button-able.
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
      // Sprint 9.5.1 B1.1 — heatmap drilldown time-bucket filters.
      // Round-trip the URL so back/forward + share-link stay coherent
      // (parent-controlled URL state pattern, see
      // docs/agent-rules/url-state-patterns.md).
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
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">Analizler</h1>
        <p className="text-muted-foreground text-sm">
          {filters.batch_job_id ? (
            <>Belirli bir batch&apos;in analizleri gösteriliyor.</>
          ) : (
            <>Tenant&apos;ın analiz arşivi — manuel ve toplu giriş bir arada.</>
          )}{" "}
          {total > 0 && <span>Toplam {total} kayıt.</span>}
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
            applyFilters({
              ...filters,
              batch_job_id: next ?? undefined,
            })
          }
          inline
        />
        <FilterPills filters={filters} />
      </div>

      {reviews.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> Yükleniyor…
        </div>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground p-6 text-sm">Bu filtrelerle eşleşen analiz yok.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tarih</TableHead>
              <TableHead>Metin</TableHead>
              <TableHead>Duygu</TableHead>
              <TableHead className="hidden md:table-cell">Kategori</TableHead>
              <TableHead className="hidden lg:table-cell">Şirket perspektifi</TableHead>
              <TableHead className="hidden text-center md:table-cell">OV</TableHead>
              <TableHead className="hidden md:table-cell">Bilet</TableHead>
              <TableHead className="hidden md:table-cell">Kaynak</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((r) => (
              <TableRow key={r.id} className="cursor-pointer">
                <TableCell className="text-muted-foreground text-xs">
                  {new Date(r.analyzed_at).toLocaleString("tr-TR")}
                </TableCell>
                <TableCell className="max-w-md">
                  <Link href={`/reviews/${r.id}`} className="hover:underline">
                    <span className="line-clamp-2 text-sm">{r.text}</span>
                  </Link>
                </TableCell>
                <TableCell>
                  <SentimentBadge label={r.sentiment_label} score={r.sentiment_score} />
                </TableCell>
                <TableCell className="hidden text-sm md:table-cell">{r.primary_category}</TableCell>
                <TableCell className="hidden text-sm lg:table-cell">
                  <PerspectiveCell
                    code={r.company_perspective_code}
                    labelTr={r.company_perspective_label_tr}
                  />
                </TableCell>
                <TableCell className="hidden text-center md:table-cell">
                  <OverrideChip count={r.override_count} href={`/reviews/${r.id}`} />
                </TableCell>
                <TableCell className="hidden md:table-cell">
                  {r.ticket_id ? (
                    <Button
                      variant="link"
                      className="h-auto p-0"
                      render={<Link href={`/tickets/${r.ticket_id}`} />}
                    >
                      Görüntüle
                    </Button>
                  ) : (
                    <span className="text-muted-foreground text-xs">—</span>
                  )}
                </TableCell>
                <TableCell className="hidden text-sm md:table-cell">
                  {SOURCE_LABELS[r.source_type]}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {reviews.hasNextPage && (
        <div className="flex justify-center">
          <Button
            variant="outline"
            onClick={() => reviews.fetchNextPage()}
            disabled={reviews.isFetchingNextPage}
          >
            {reviews.isFetchingNextPage ? "Yükleniyor…" : "Daha fazla göster"}
          </Button>
        </div>
      )}
    </main>
  );
}

// Sprint 9.5.1 B1.1 — labels for heatmap drilldown time-bucket pills.
// Postgres DOW convention: 0=Sunday ... 6=Saturday (matches the
// heatmap_generator's y_keys for the day_of_week axis).
const DOW_LABELS_TR: Record<number, string> = {
  0: "Pazar",
  1: "Pazartesi",
  2: "Salı",
  3: "Çarşamba",
  4: "Perşembe",
  5: "Cuma",
  6: "Cumartesi",
};
const MONTH_LABELS_TR: Record<number, string> = {
  1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan", 5: "Mayıs", 6: "Haziran",
  7: "Temmuz", 8: "Ağustos", 9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
};

function FilterPills({ filters }: { filters: ReviewListFilters }) {
  const pills: { label: string; href: string }[] = [];
  if (filters.batch_job_id) {
    pills.push({
      label: `Batch: ${filters.batch_job_id.slice(0, 8)}…`,
      href: "/reviews",
    });
  }
  if (filters.sentiment_labels?.length) {
    pills.push({
      label: `Duygu: ${filters.sentiment_labels.join(", ")}`,
      href: "/reviews",
    });
  }
  if (filters.source_types?.length) {
    pills.push({
      label: `Kaynak: ${filters.source_types.map((t) => SOURCE_LABELS[t]).join(", ")}`,
      href: "/reviews",
    });
  }
  // Sprint 9.5.1 B1.1 — heatmap drilldown pills so the operator can
  // see what's active (otherwise the filtered listing looks like a
  // mysterious empty result with no UI affordance to clear).
  if (filters.hour_of_day !== undefined) {
    pills.push({
      label: `Saat: ${String(filters.hour_of_day).padStart(2, "0")}:00`,
      href: "/reviews",
    });
  }
  if (filters.day_of_week !== undefined) {
    pills.push({
      label: `Gün: ${DOW_LABELS_TR[filters.day_of_week] ?? filters.day_of_week}`,
      href: "/reviews",
    });
  }
  if (filters.week_of_year !== undefined) {
    pills.push({ label: `Hafta: ${filters.week_of_year}`, href: "/reviews" });
  }
  if (filters.month !== undefined) {
    pills.push({
      label: `Ay: ${MONTH_LABELS_TR[filters.month] ?? filters.month}`,
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
          className="bg-muted hover:bg-muted/80 inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs"
        >
          {p.label} <span aria-hidden>×</span>
        </Link>
      ))}
    </div>
  );
}

/** Multi-select dropdown driven by ``GET /tenants/me/taxonomies`` plus
 *  the ``__unmatched__`` sentinel. The dropdown is a controlled
 *  primitive — ``selected`` flows in from the parent's mirror state,
 *  ``onApply`` flows out and the parent owns both the local state +
 *  URL push (Path B mirror, see docs/agent-rules/url-state-patterns.md). */
function PerspectiveFilterDropdown({
  selected,
  onApply,
}: {
  selected: string[];
  onApply: (next: string[]) => void;
}) {
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
    selected.length === 0 ? "Şirket perspektifi" : `Perspektif: ${selected.length} seçili`;

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
      {/* Sprint 8.3.5.6 round-1 — DropdownMenuLabel removed: it maps to
          MenuPrimitive.GroupLabel which Base UI requires to live inside a
          <Menu.Group>. Without the Group wrapper the component throws
          "MenuGroupRootContext is missing" (production error #31) on
          first open. Trigger label already reads "Şirket perspektifi" so
          the in-menu heading was redundant. */}
      <DropdownMenuContent align="start" className="max-h-80 w-64 overflow-y-auto">
        <DropdownMenuCheckboxItem
          checked={selected.includes(UNMATCHED_SENTINEL)}
          onCheckedChange={() => toggle(UNMATCHED_SENTINEL)}
        >
          <span className="text-muted-foreground italic">Eşleşme yok</span>
        </DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        {taxonomies.isLoading ? (
          <div className="text-muted-foreground px-2 py-1.5 text-xs">Yükleniyor…</div>
        ) : items.length === 0 ? (
          <div className="text-muted-foreground px-2 py-1.5 text-xs">Taksonomi yok.</div>
        ) : (
          items.map((t) => (
            <DropdownMenuCheckboxItem
              key={t.code}
              checked={selected.includes(t.code)}
              onCheckedChange={() => toggle(t.code)}
            >
              {t.label_tr}
            </DropdownMenuCheckboxItem>
          ))
        )}
        {selected.length > 0 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => onApply([])} className="text-muted-foreground text-xs">
              Tümünü temizle
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function PerspectiveCell({ code, labelTr }: { code: string | null; labelTr: string | null }) {
  if (code === null) {
    return <span className="text-muted-foreground text-xs">—</span>;
  }
  // labelTr null + code non-null = taxonomy entry was pruned post-analyze
  // (Sprint 8.3.7 edit UI). Render a subtle "kaldırıldı" badge so the
  // UI doesn't pretend the raw code is the human-friendly label.
  if (labelTr === null) {
    return (
      <span className="text-muted-foreground italic" title={`Kod: ${code}`}>
        kaldırılmış
      </span>
    );
  }
  return <span className="line-clamp-1">{labelTr}</span>;
}

function SentimentBadge({ label, score }: { label: string; score: number }) {
  const tone = label === "NEGATIF" ? "danger" : label === "POZITIF" ? "success" : "default";
  return (
    <div className="flex flex-col items-start gap-0.5">
      <Badge
        className={cn(
          tone === "danger" && "bg-red-100 text-red-700",
          tone === "success" && "bg-emerald-100 text-emerald-700",
        )}
      >
        {label}
      </Badge>
      <span className="text-muted-foreground text-xs">{score.toFixed(2)}</span>
    </div>
  );
}
