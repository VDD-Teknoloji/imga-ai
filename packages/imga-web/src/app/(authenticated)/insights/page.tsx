"use client";

// Sprint 8.3.3 — /insights sayfası.
//
// 5 tab × N chart, hepsi tek dosyada (her bir tab'ın kendi alt-componenti
// var ama kapsam küçük; ayrı dosyalara bölmek bundan sonra Sprint 8.3.4
// polish'inde yapılır). URL state: ?tab=...&date_from=...&date_to=...
// Refresh-stable; cell-click navigation /reviews'a query params ile.

import { TrendingUp } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Heatmap } from "@/components/charts/heatmap";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useCategoryDistribution,
  useCompanyPerspectiveDistribution,
  useNpsMonthlyTrend,
  useNpsSummary,
  useOverrideStats,
  useSensitivityDistribution,
  useSentimentByCategory,
  useSentimentDistribution,
  useSentimentTimeline,
  useTicketResolutionTime,
} from "@/hooks/use-analytics";
import type {
  AnalyticsFilters,
  CohortDimension,
  CohortPeriod,
  HeatmapMetric,
  HeatmapXAxis,
  HeatmapYAxis,
  WordCloudSentiment,
} from "@/lib/types";

import { CohortTab } from "./_components/cohort-tab";
import { HeatmapTab } from "./_components/heatmap-tab";
import { WordCloudTab } from "./_components/word-cloud-tab";

const SENTIMENT_COLOURS: Record<string, string> = {
  NEGATIF: "#dc2626",
  NÖTR: "#737373",
  POZITIF: "#16a34a",
};

type TabKey =
  | "sentiment"
  | "category"
  | "cross"
  | "overrides"
  | "tickets"
  | "nps"
  | "perspective"
  // Sprint 8.3.9 additions.
  | "cohort"
  | "wordcloud"
  | "heatmap";

const TAB_LABELS: Record<TabKey, string> = {
  sentiment: "Duygu",
  category: "Kategori",
  cross: "Çapraz Analiz",
  overrides: "Override Katmanları",
  tickets: "Biletler",
  nps: "NPS",
  perspective: "Şirket Perspektifi",
  cohort: "Kohort",
  wordcloud: "Kelime Bulutu",
  heatmap: "Heatmap",
};

// Sprint 8.3.4 round-2 — wrap the search-params-reading subtree in
// <Suspense>. Without it, Next.js 16 client-renders the entire page
// up to the nearest boundary; on hard refresh the searchParams hook
// hits a hydration race where the first paint sees stale (or null)
// values, locks `tab` and `filters` to defaults, and subsequent
// router.push() updates don't propagate cleanly. The Suspense
// fallback covers the brief window before client hydration; once
// mounted, useSearchParams is reactive as documented.
export default function InsightsPage() {
  return (
    <Suspense fallback={<InsightsHeaderSkeleton />}>
      <InsightsContent />
    </Suspense>
  );
}

function InsightsHeaderSkeleton() {
  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-8">
      <header className="flex items-center gap-2">
        <TrendingUp className="text-primary size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold">İçgörüler</h1>
          <p className="text-muted-foreground text-sm">Yükleniyor…</p>
        </div>
      </header>
    </main>
  );
}

// Sprint 8.3.4 round-2 (continued) — controlled local state mirrors the
// URL snapshot. The pure URL-as-source-of-truth pattern (round-1) broke
// after a hard refresh with non-empty query: tab clicks fired
// onValueChange and our handler pushed the new URL, but `useSearchParams`
// in this Suspense child stopped notifying subscribers after the first
// hydration, so `tab` never updated, the controlled <Tabs value=...>
// prop never changed, and the UI froze. The mirror gives the controlled
// primitives an immediate state update independent of the hook's
// reactivity; the URL still gets pushed (shareable + back-button), and
// a sync useEffect catches external nav (back/forward, deep links).

function InsightsContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [tab, setTabState] = useState<TabKey>(
    () => (searchParams.get("tab") as TabKey) || "sentiment",
  );
  const [dateFrom, setDateFromState] = useState<string>(() => searchParams.get("date_from") ?? "");
  const [dateTo, setDateToState] = useState<string>(() => searchParams.get("date_to") ?? "");
  const [sourceTypes, setSourceTypesState] = useState<string>(
    () => searchParams.get("source_types") ?? "",
  );

  // Sprint 8.3.9 — per-tab URL state for the new visualization tabs.
  // Each tab owns a small slice of params; the parent page is the
  // single owner so back/forward and F5 stay coherent (Path B
  // mirror, same as the date filter above).
  const [cohortPeriod, setCohortPeriodState] = useState<CohortPeriod>(
    () => (searchParams.get("cohort_period") as CohortPeriod) || "month",
  );
  const [cohortDimension, setCohortDimensionState] = useState<CohortDimension>(
    () =>
      (searchParams.get("cohort_dimension") as CohortDimension) || "taxonomy",
  );
  const [cohortLimit, setCohortLimitState] = useState<number>(
    () => Number(searchParams.get("cohort_limit") ?? "10") || 10,
  );
  const [wcSentiment, setWcSentimentState] = useState<WordCloudSentiment>(
    () => (searchParams.get("wc_sentiment") as WordCloudSentiment) || "all",
  );
  const [wcTaxonomy, setWcTaxonomyState] = useState<string>(
    () => searchParams.get("wc_taxonomy") ?? "",
  );
  const [wcBigrams, setWcBigramsState] = useState<boolean>(
    () => searchParams.get("wc_bigrams") !== "false",
  );
  const [hmX, setHmXState] = useState<HeatmapXAxis>(
    () => (searchParams.get("hm_x") as HeatmapXAxis) || "hour_of_day",
  );
  const [hmY, setHmYState] = useState<HeatmapYAxis>(
    () => (searchParams.get("hm_y") as HeatmapYAxis) || "day_of_week",
  );
  const [hmMetric, setHmMetricState] = useState<HeatmapMetric>(
    () => (searchParams.get("hm_metric") as HeatmapMetric) || "count",
  );

  // Sync FROM URL → state for external navigations (back/forward, deep
  // links, /reviews drilldown navigating back here). Functional setter
  // form keeps the eslint deps array honest while still no-op'ing when
  // the value is unchanged.
  //
  // The four setState calls trip react-hooks/set-state-in-effect. They
  // are the load-bearing half of the Path B mirror pattern documented
  // above (Sprint 8.3.4 round-2) — useSearchParams is not reactive in
  // this Suspense child after the first hydration, so URL-driven nav
  // (back/forward, deep links) needs an effect to re-sync local state.
  // Intentional; refactoring to useSyncExternalStore would re-introduce
  // the round-1 freeze.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const urlTab = (searchParams.get("tab") as TabKey) || "sentiment";
    setTabState((prev) => (prev === urlTab ? prev : urlTab));
    const urlFrom = searchParams.get("date_from") ?? "";
    setDateFromState((prev) => (prev === urlFrom ? prev : urlFrom));
    const urlTo = searchParams.get("date_to") ?? "";
    setDateToState((prev) => (prev === urlTo ? prev : urlTo));
    const urlSrc = searchParams.get("source_types") ?? "";
    setSourceTypesState((prev) => (prev === urlSrc ? prev : urlSrc));
    // Sprint 8.3.9 mirrors.
    const urlCohortPeriod =
      (searchParams.get("cohort_period") as CohortPeriod) || "month";
    setCohortPeriodState((prev) =>
      prev === urlCohortPeriod ? prev : urlCohortPeriod,
    );
    const urlCohortDimension =
      (searchParams.get("cohort_dimension") as CohortDimension) || "taxonomy";
    setCohortDimensionState((prev) =>
      prev === urlCohortDimension ? prev : urlCohortDimension,
    );
    const urlCohortLimit =
      Number(searchParams.get("cohort_limit") ?? "10") || 10;
    setCohortLimitState((prev) =>
      prev === urlCohortLimit ? prev : urlCohortLimit,
    );
    const urlWcSent =
      (searchParams.get("wc_sentiment") as WordCloudSentiment) || "all";
    setWcSentimentState((prev) => (prev === urlWcSent ? prev : urlWcSent));
    const urlWcTax = searchParams.get("wc_taxonomy") ?? "";
    setWcTaxonomyState((prev) => (prev === urlWcTax ? prev : urlWcTax));
    const urlWcBg = searchParams.get("wc_bigrams") !== "false";
    setWcBigramsState((prev) => (prev === urlWcBg ? prev : urlWcBg));
    const urlHmX =
      (searchParams.get("hm_x") as HeatmapXAxis) || "hour_of_day";
    setHmXState((prev) => (prev === urlHmX ? prev : urlHmX));
    const urlHmY =
      (searchParams.get("hm_y") as HeatmapYAxis) || "day_of_week";
    setHmYState((prev) => (prev === urlHmY ? prev : urlHmY));
    const urlHmMetric =
      (searchParams.get("hm_metric") as HeatmapMetric) || "count";
    setHmMetricState((prev) => (prev === urlHmMetric ? prev : urlHmMetric));
  }, [searchParams]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // The query hooks see this; date strings are YYYY-MM-DD (the
  // use-analytics layer expands to local-midnight ISO before the API).
  const filters = useMemo<AnalyticsFilters>(
    () => ({
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      source_types: sourceTypes ? sourceTypes.split(",").filter(Boolean) : undefined,
    }),
    [dateFrom, dateTo, sourceTypes],
  );

  // Push a single querystring update. Reads searchParams fresh on each
  // call (closure-captured but the captured value is the latest at click
  // time, since the click handlers are recreated per render).
  function pushParam(key: string, value: string | null) {
    const params = new URLSearchParams(searchParams.toString());
    if (value === null || value === "") params.delete(key);
    else params.set(key, value);
    const qs = params.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  function handleTabChange(newTab: TabKey) {
    setTabState(newTab);
    pushParam("tab", newTab);
  }
  function handleDateFromChange(value: string) {
    setDateFromState(value);
    pushParam("date_from", value || null);
  }
  function handleDateToChange(value: string) {
    setDateToState(value);
    pushParam("date_to", value || null);
  }
  function handleSourceTypesChange(value: string) {
    setSourceTypesState(value);
    pushParam("source_types", value || null);
  }

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-8">
      <header className="flex items-center gap-2">
        <TrendingUp className="text-primary size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold">İçgörüler</h1>
          <p className="text-muted-foreground text-sm">
            Duygu, kategori ve bilet metriklerinin derin dalış görünümü.
          </p>
        </div>
      </header>

      <FilterBar
        dateFrom={dateFrom}
        dateTo={dateTo}
        sourceTypes={sourceTypes}
        onDateFromChange={handleDateFromChange}
        onDateToChange={handleDateToChange}
        onSourceTypesChange={handleSourceTypesChange}
      />

      <Tabs value={tab} onValueChange={(v) => handleTabChange(v as TabKey)}>
        <TabsList className="grid grid-cols-3 sm:grid-cols-5 lg:grid-cols-10">
          {(Object.keys(TAB_LABELS) as TabKey[]).map((k) => (
            <TabsTrigger key={k} value={k}>
              {TAB_LABELS[k]}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="sentiment">
          <SentimentTab filters={filters} />
        </TabsContent>
        <TabsContent value="category">
          <CategoryTab filters={filters} />
        </TabsContent>
        <TabsContent value="cross">
          <CrossAnalysisTab filters={filters} router={router} />
        </TabsContent>
        <TabsContent value="overrides">
          <OverridesTab filters={filters} />
        </TabsContent>
        <TabsContent value="tickets">
          <TicketsTab filters={filters} />
        </TabsContent>
        <TabsContent value="nps">
          <NpsTab dateFrom={dateFrom} dateTo={dateTo} />
        </TabsContent>
        <TabsContent value="perspective">
          <PerspectiveTab filters={filters} router={router} />
        </TabsContent>
        <TabsContent value="cohort">
          <CohortTab
            period={cohortPeriod}
            dimension={cohortDimension}
            dateFrom={dateFrom}
            dateTo={dateTo}
            limitCohorts={cohortLimit}
            onPeriodChange={(next) => {
              setCohortPeriodState(next);
              pushParam("cohort_period", next === "month" ? null : next);
            }}
            onDimensionChange={(next) => {
              setCohortDimensionState(next);
              pushParam(
                "cohort_dimension",
                next === "taxonomy" ? null : next,
              );
            }}
            onLimitChange={(next) => {
              setCohortLimitState(next);
              pushParam("cohort_limit", next === 10 ? null : String(next));
            }}
          />
        </TabsContent>
        <TabsContent value="wordcloud">
          <WordCloudTab
            sentiment={wcSentiment}
            taxonomyCode={wcTaxonomy}
            includeBigrams={wcBigrams}
            dateFrom={dateFrom}
            dateTo={dateTo}
            onSentimentChange={(next) => {
              setWcSentimentState(next);
              pushParam("wc_sentiment", next === "all" ? null : next);
            }}
            onTaxonomyChange={(next) => {
              setWcTaxonomyState(next);
              pushParam("wc_taxonomy", next || null);
            }}
            onBigramsChange={(next) => {
              setWcBigramsState(next);
              pushParam("wc_bigrams", next ? null : "false");
            }}
          />
        </TabsContent>
        <TabsContent value="heatmap">
          <HeatmapTab
            xAxis={hmX}
            yAxis={hmY}
            metric={hmMetric}
            dateFrom={dateFrom}
            dateTo={dateTo}
            onXAxisChange={(next) => {
              setHmXState(next);
              pushParam("hm_x", next === "hour_of_day" ? null : next);
            }}
            onYAxisChange={(next) => {
              setHmYState(next);
              pushParam("hm_y", next === "day_of_week" ? null : next);
            }}
            onMetricChange={(next) => {
              setHmMetricState(next);
              pushParam("hm_metric", next === "count" ? null : next);
            }}
          />
        </TabsContent>
      </Tabs>
    </main>
  );
}

// --- filter bar -----------------------------------------------------------

// Dates live in the URL as YYYY-MM-DD strings — same string the native
// <input type="date"> already produces and consumes. The ISO datetime
// detour caused a -1 day timezone slide (a TR user picking April 4
// stored 2026-04-03T21:00:00Z, which slice(0,10) displayed as April 3).
// Use-analytics hooks convert to local-midnight ISO before hitting the
// API, so the user's "April 4" semantically means "April 4 00:00 in
// my timezone".

function FilterBar({
  dateFrom,
  dateTo,
  sourceTypes,
  onDateFromChange,
  onDateToChange,
  onSourceTypesChange,
}: {
  dateFrom: string;
  dateTo: string;
  sourceTypes: string;
  onDateFromChange: (value: string) => void;
  onDateToChange: (value: string) => void;
  onSourceTypesChange: (value: string) => void;
}) {
  // Native min/max on the date inputs prevents the picker from offering
  // an invalid (from > to) range; the API would still cap at 90 days,
  // but stopping it at the input level is friendlier than a 400 round-
  // trip and makes the picker grey out the disallowed days visually.
  return (
    <Card>
      <CardContent className="grid grid-cols-1 gap-3 p-4 md:grid-cols-3">
        <div>
          <Label className="text-xs">Başlangıç</Label>
          <input
            type="date"
            value={dateFrom}
            max={dateTo || undefined}
            onChange={(e) => onDateFromChange(e.target.value)}
            className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
          />
        </div>
        <div>
          <Label className="text-xs">Bitiş</Label>
          <input
            type="date"
            value={dateTo}
            min={dateFrom || undefined}
            onChange={(e) => onDateToChange(e.target.value)}
            className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
          />
        </div>
        <div>
          <Label className="text-xs">Kaynak</Label>
          <select
            value={sourceTypes}
            onChange={(e) => onSourceTypesChange(e.target.value)}
            className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
          >
            <option value="">Tümü</option>
            <option value="manual">Sadece Manuel</option>
            <option value="batch">Sadece Toplu</option>
          </select>
        </div>
      </CardContent>
    </Card>
  );
}

// --- chart frame: handles loading / error / empty states + min-height ---

// Recharts ResponsiveContainer measures parent on mount. If a Tabs primitive
// keeps inactive content with display:none, the container reads 0×0 and
// emits "width(-1) height(-1)" warnings; explicit min-h on the wrapper plus
// keying the chart to the active tab ensures clean dimensions on tab switch.

type AsyncState<T> = {
  data?: T;
  error?: { message: string } | null;
  isLoading?: boolean;
  isPending?: boolean;
};

function ChartFrame<T>({
  state,
  isEmpty,
  height = 240,
  children,
}: {
  state: AsyncState<T>;
  isEmpty: (data: T) => boolean;
  height?: number;
  children: (data: T) => React.ReactNode;
}) {
  const minH = `min-h-[${height}px]`;
  if (state.error) {
    return (
      <div className={`${minH} flex items-center justify-center`}>
        <p className="text-destructive text-sm">Veri yüklenemedi: {state.error.message}</p>
      </div>
    );
  }
  if (state.isLoading || state.isPending || !state.data) {
    return (
      <div className={`${minH} flex items-center justify-center`}>
        <p className="text-muted-foreground text-sm">Yükleniyor…</p>
      </div>
    );
  }
  if (isEmpty(state.data)) {
    return (
      <div className={`${minH} flex items-center justify-center`}>
        <p className="text-muted-foreground text-sm">Bu filtrelerle veri bulunamadı.</p>
      </div>
    );
  }
  return <div className={minH}>{children(state.data)}</div>;
}

// --- tab components -------------------------------------------------------

function SentimentTab({ filters }: { filters: AnalyticsFilters }) {
  const dist = useSentimentDistribution(filters);
  const sens = useSensitivityDistribution(filters);
  const tl = useSentimentTimeline(filters, "day");
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Duygu Dağılımı</CardTitle>
          </CardHeader>
          <CardContent>
            <ChartFrame state={dist} isEmpty={(d) => d.total === 0}>
              {(d) => (
                <ResponsiveContainer width="100%" height={240}>
                  <PieChart>
                    <Pie
                      data={d.data}
                      dataKey="count"
                      nameKey="label"
                      innerRadius={45}
                      outerRadius={80}
                      label
                    >
                      {d.data.map((row) => (
                        <Cell key={row.label} fill={SENTIMENT_COLOURS[row.label] ?? "#888"} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </ChartFrame>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Skor Histogramı</CardTitle>
          </CardHeader>
          <CardContent>
            <ChartFrame state={sens} isEmpty={(d) => d.total === 0}>
              {(d) => (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={d.buckets}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="range_start"
                      tickFormatter={(v) => v.toFixed(1)}
                      fontSize={10}
                    />
                    <YAxis fontSize={10} />
                    <Tooltip />
                    <Bar dataKey="count" fill="#1e40af" />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </ChartFrame>
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Duygu Trendi (gün)</CardTitle>
        </CardHeader>
        <CardContent>
          <ChartFrame state={tl} isEmpty={(d) => d.data.length === 0} height={260}>
            {(d) => (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={d.data}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" fontSize={10} />
                  <YAxis fontSize={10} />
                  <Tooltip />
                  <Line type="monotone" dataKey="negatif" stroke="#dc2626" />
                  <Line type="monotone" dataKey="nötr" stroke="#737373" />
                  <Line type="monotone" dataKey="pozitif" stroke="#16a34a" />
                </LineChart>
              </ResponsiveContainer>
            )}
          </ChartFrame>
        </CardContent>
      </Card>
    </div>
  );
}

function CategoryTab({ filters }: { filters: AnalyticsFilters }) {
  const cats = useCategoryDistribution(filters, 10);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Kategori Top 10</CardTitle>
      </CardHeader>
      <CardContent>
        <ChartFrame state={cats} isEmpty={(d) => d.total === 0}>
          {(d) => (
            <ResponsiveContainer width="100%" height={Math.max(220, d.data.length * 32)}>
              <BarChart layout="vertical" data={d.data}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" fontSize={10} />
                <YAxis type="category" dataKey="category_label_tr" fontSize={11} width={140} />
                <Tooltip />
                <Bar dataKey="count" fill="#1e40af" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartFrame>
      </CardContent>
    </Card>
  );
}

function CrossAnalysisTab({
  filters,
  router,
}: {
  filters: AnalyticsFilters;
  router: ReturnType<typeof useRouter>;
}) {
  const matrix = useSentimentByCategory(filters, 10);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Kategori × Duygu Matrisi</CardTitle>
      </CardHeader>
      <CardContent>
        <ChartFrame state={matrix} isEmpty={(d) => d.categories.length === 0} height={300}>
          {(d) => (
            <Heatmap
              rows={d.category_labels_tr}
              cols={d.sentiments}
              matrix={d.matrix}
              rowTotals={d.totals_by_category}
              colTotals={d.totals_by_sentiment}
              colorScale="blue"
              tooltip={(value, rowLabel, colLabel) => `${rowLabel} × ${colLabel}: ${value} analiz`}
              onCellClick={(i, j) => {
                const cat = d.categories[i];
                const sent = d.sentiments[j];
                if (!cat || !sent) return;
                // Sprint 8.3.10 — pre-fix this URL silently dropped
                // ``category`` (the /reviews page never read it). The
                // backend now accepts ``primary_categories`` (CSV) and
                // the page parses it into the filter chain.
                router.push(
                  `/reviews?sentiment_labels=${encodeURIComponent(sent)}&primary_categories=${encodeURIComponent(cat)}`,
                );
              }}
            />
          )}
        </ChartFrame>
      </CardContent>
    </Card>
  );
}

function OverridesTab({ filters }: { filters: AnalyticsFilters }) {
  const stats = useOverrideStats(filters);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Override Katmanları</CardTitle>
      </CardHeader>
      <CardContent>
        <ChartFrame state={stats} isEmpty={(d) => d.data.length === 0} height={260}>
          {(d) => (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={d.data} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" fontSize={10} />
                <YAxis type="category" dataKey="layer_label_tr" fontSize={11} width={160} />
                <Tooltip />
                <Bar dataKey="trigger_count" fill="#1e40af" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartFrame>
        <p className="text-muted-foreground mt-2 text-xs">
          Override katman sayımı Sprint 8.3.4&apos;te doldurulacak (<code>overrides_applied</code>{" "}
          JSONB kolonu); şimdilik 5 katman sıfır sayımla gösteriliyor.
        </p>
      </CardContent>
    </Card>
  );
}

// --- Sprint 8.3.5 / 8.3.5.6 — NPS + Şirket Perspektifi --------------------

const NPS_BUCKET_COLOURS: Record<string, string> = {
  Detractor: "#dc2626",
  Passive: "#f59e0b",
  Promoter: "#16a34a",
};

function NpsTab({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }) {
  const filters = useMemo(
    () => ({
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    }),
    [dateFrom, dateTo],
  );
  const summary = useNpsSummary(filters);
  const trend = useNpsMonthlyTrend(12);

  const trendData = useMemo(
    () => (trend.data ?? []).map((p) => ({ ...p, label: p.month.slice(0, 7) })),
    [trend.data],
  );
  const donutData = useMemo(() => {
    if (!summary.data) return [];
    return [
      { name: "Detractor", count: summary.data.detractor_count },
      { name: "Passive", count: summary.data.passive_count },
      { name: "Promoter", count: summary.data.promoter_count },
    ];
  }, [summary.data]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">NPS Skoru</CardTitle>
          </CardHeader>
          <CardContent>
            <ChartFrame state={summary} isEmpty={(d) => d.total_count === 0} height={160}>
              {(d) => (
                <div className="flex flex-col items-center justify-center gap-1 py-6">
                  <span className="text-5xl font-semibold tracking-tight">
                    {d.score === null ? "—" : (d.score > 0 ? "+" : "") + Math.round(d.score)}
                  </span>
                  <span className="text-muted-foreground text-xs">
                    {d.total_count} yanıt · kapsama %{d.coverage_percent.toFixed(1)}
                  </span>
                </div>
              )}
            </ChartFrame>
          </CardContent>
        </Card>
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Bucket Dağılımı</CardTitle>
          </CardHeader>
          <CardContent>
            <ChartFrame state={summary} isEmpty={(d) => d.total_count === 0} height={220}>
              {() => (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie
                      data={donutData}
                      dataKey="count"
                      nameKey="name"
                      innerRadius={45}
                      outerRadius={80}
                      label
                    >
                      {donutData.map((row) => (
                        <Cell key={row.name} fill={NPS_BUCKET_COLOURS[row.name] ?? "#888"} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </ChartFrame>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Aylık Trend (son 12 ay)</CardTitle>
        </CardHeader>
        <CardContent>
          <ChartFrame state={trend} isEmpty={(d) => d.length === 0} height={260}>
            {() => (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={trendData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="label" fontSize={10} />
                  <YAxis domain={[-100, 100]} ticks={[-100, -50, 0, 50, 100]} fontSize={10} />
                  <Tooltip
                    formatter={(value) =>
                      value === null || value === undefined ? "veri yok" : String(value)
                    }
                  />
                  <Line
                    type="monotone"
                    dataKey="score"
                    stroke="#2563eb"
                    strokeWidth={2.5}
                    dot={{ r: 3 }}
                    connectNulls={false}
                    name="NPS"
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </ChartFrame>
        </CardContent>
      </Card>
    </div>
  );
}

function PerspectiveTab({
  filters,
  router,
}: {
  filters: AnalyticsFilters;
  router: ReturnType<typeof useRouter>;
}) {
  const dist = useCompanyPerspectiveDistribution(filters, 10);
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Şirket Perspektifi Top 10</CardTitle>
        </CardHeader>
        <CardContent>
          <ChartFrame state={dist} isEmpty={(d) => d.total === 0}>
            {(d) => (
              <>
                <ResponsiveContainer width="100%" height={Math.max(220, d.data.length * 32)}>
                  <BarChart layout="vertical" data={d.data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" fontSize={10} />
                    <YAxis type="category" dataKey="label_tr" fontSize={11} width={160} />
                    <Tooltip />
                    <Bar
                      dataKey="count"
                      fill="#0d9488"
                      onClick={(data) => {
                        const code = (data as { code?: string } | undefined)?.code;
                        if (typeof code === "string" && code.length > 0) {
                          router.push(`/reviews?perspective_codes=${encodeURIComponent(code)}`);
                        }
                      }}
                      style={{ cursor: "pointer" }}
                    />
                  </BarChart>
                </ResponsiveContainer>
                {d.unmatched_count > 0 && (
                  <p className="text-muted-foreground mt-3 text-xs">
                    Eşleşme yok:{" "}
                    <button
                      type="button"
                      className="hover:text-foreground underline"
                      onClick={() => router.push("/reviews?perspective_codes=__unmatched__")}
                    >
                      {d.unmatched_count} analiz
                    </button>{" "}
                    (heuristik bir taksonomi girdisiyle eşleşmedi).
                  </p>
                )}
              </>
            )}
          </ChartFrame>
        </CardContent>
      </Card>
    </div>
  );
}

function TicketsTab({ filters }: { filters: AnalyticsFilters }) {
  const res = useTicketResolutionTime(filters);
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Çözüm Süresi Dağılımı</CardTitle>
        </CardHeader>
        <CardContent>
          <ChartFrame state={res} isEmpty={(d) => d.total_resolved_tickets === 0} height={220}>
            {(d) => (
              <>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={d.distribution}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="bucket" fontSize={11} />
                    <YAxis fontSize={10} />
                    <Tooltip />
                    <Bar dataKey="count" fill="#1e40af" />
                  </BarChart>
                </ResponsiveContainer>
                <dl className="text-muted-foreground mt-3 grid grid-cols-3 gap-3 text-xs">
                  <div>
                    <dt>Ortalama</dt>
                    <dd className="text-foreground text-base font-semibold">
                      {d.avg_resolution_hours.toFixed(1)} saat
                    </dd>
                  </div>
                  <div>
                    <dt>Ortanca</dt>
                    <dd className="text-foreground text-base font-semibold">
                      {d.median_resolution_hours.toFixed(1)} saat
                    </dd>
                  </div>
                  <div>
                    <dt>p95</dt>
                    <dd className="text-foreground text-base font-semibold">
                      {d.p95_resolution_hours.toFixed(1)} saat
                    </dd>
                  </div>
                </dl>
              </>
            )}
          </ChartFrame>
        </CardContent>
      </Card>
    </div>
  );
}
