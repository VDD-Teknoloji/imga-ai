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
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  useCategoryDistribution,
  useOverrideStats,
  useSensitivityDistribution,
  useSentimentByCategory,
  useSentimentDistribution,
  useSentimentTimeline,
  useTicketResolutionTime,
} from "@/hooks/use-analytics";
import type { AnalyticsFilters } from "@/lib/types";

const SENTIMENT_COLOURS: Record<string, string> = {
  NEGATIF: "#dc2626",
  NÖTR: "#737373",
  POZITIF: "#16a34a",
};

type TabKey = "sentiment" | "category" | "cross" | "overrides" | "tickets";

const TAB_LABELS: Record<TabKey, string> = {
  sentiment: "Duygu",
  category: "Kategori",
  cross: "Çapraz Analiz",
  overrides: "Override Katmanları",
  tickets: "Biletler",
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
  const [dateFrom, setDateFromState] = useState<string>(
    () => searchParams.get("date_from") ?? "",
  );
  const [dateTo, setDateToState] = useState<string>(
    () => searchParams.get("date_to") ?? "",
  );
  const [sourceTypes, setSourceTypesState] = useState<string>(
    () => searchParams.get("source_types") ?? "",
  );

  // Sync FROM URL → state for external navigations (back/forward, deep
  // links, /reviews drilldown navigating back here). Functional setter
  // form keeps the eslint deps array honest while still no-op'ing when
  // the value is unchanged.
  useEffect(() => {
    const urlTab = (searchParams.get("tab") as TabKey) || "sentiment";
    setTabState((prev) => (prev === urlTab ? prev : urlTab));
    const urlFrom = searchParams.get("date_from") ?? "";
    setDateFromState((prev) => (prev === urlFrom ? prev : urlFrom));
    const urlTo = searchParams.get("date_to") ?? "";
    setDateToState((prev) => (prev === urlTo ? prev : urlTo));
    const urlSrc = searchParams.get("source_types") ?? "";
    setSourceTypesState((prev) => (prev === urlSrc ? prev : urlSrc));
  }, [searchParams]);

  // The query hooks see this; date strings are YYYY-MM-DD (the
  // use-analytics layer expands to local-midnight ISO before the API).
  const filters = useMemo<AnalyticsFilters>(
    () => ({
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      source_types: sourceTypes
        ? sourceTypes.split(",").filter(Boolean)
        : undefined,
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
        <TabsList className="grid grid-cols-5">
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
        <p className="text-destructive text-sm">
          Veri yüklenemedi: {state.error.message}
        </p>
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
        <p className="text-muted-foreground text-sm">
          Bu filtrelerle veri bulunamadı.
        </p>
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
        <ChartFrame
          state={matrix}
          isEmpty={(d) => d.categories.length === 0}
          height={300}
        >
          {(d) => (
            <Heatmap
              rows={d.category_labels_tr}
              cols={d.sentiments}
              matrix={d.matrix}
              rowTotals={d.totals_by_category}
              colTotals={d.totals_by_sentiment}
              colorScale="blue"
              tooltip={(value, rowLabel, colLabel) =>
                `${rowLabel} × ${colLabel}: ${value} analiz`
              }
              onCellClick={(i, j) => {
                const cat = d.categories[i];
                const sent = d.sentiments[j];
                if (!cat || !sent) return;
                router.push(
                  `/reviews?sentiment_labels=${encodeURIComponent(sent)}&category=${encodeURIComponent(cat)}`,
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
          Override katman sayımı Sprint 8.3.4&apos;te doldurulacak (
          <code>overrides_applied</code> JSONB kolonu); şimdilik 5 katman
          sıfır sayımla gösteriliyor.
        </p>
      </CardContent>
    </Card>
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
          <ChartFrame
            state={res}
            isEmpty={(d) => d.total_resolved_tickets === 0}
            height={220}
          >
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
