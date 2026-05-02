"use client";

// Sprint 8.3.3 — /insights sayfası.
//
// 5 tab × N chart, hepsi tek dosyada (her bir tab'ın kendi alt-componenti
// var ama kapsam küçük; ayrı dosyalara bölmek bundan sonra Sprint 8.3.4
// polish'inde yapılır). URL state: ?tab=...&date_from=...&date_to=...
// Refresh-stable; cell-click navigation /reviews'a query params ile.

import { TrendingUp } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";
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
import type { AnalyticsFilters, Granularity } from "@/lib/types";

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

export default function InsightsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const tab = (searchParams.get("tab") as TabKey) || "sentiment";
  const filters = useMemo<AnalyticsFilters>(
    () => ({
      date_from: searchParams.get("date_from") ?? undefined,
      date_to: searchParams.get("date_to") ?? undefined,
      source_types: searchParams.get("source_types")?.split(",").filter(Boolean),
    }),
    [searchParams],
  );

  function setParam(key: string, value: string | null) {
    const params = new URLSearchParams(searchParams.toString());
    if (value === null || value === "") params.delete(key);
    else params.set(key, value);
    router.replace(`/insights?${params.toString()}`, { scroll: false });
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

      <FilterBar filters={filters} setParam={setParam} />

      <Tabs
        value={tab}
        onValueChange={(v) => setParam("tab", v === "sentiment" ? null : v)}
      >
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

function FilterBar({
  filters,
  setParam,
}: {
  filters: AnalyticsFilters;
  setParam: (k: string, v: string | null) => void;
}) {
  return (
    <Card>
      <CardContent className="grid grid-cols-1 gap-3 p-4 md:grid-cols-3">
        <div>
          <Label className="text-xs">Başlangıç</Label>
          <input
            type="date"
            value={filters.date_from?.slice(0, 10) ?? ""}
            onChange={(e) =>
              setParam(
                "date_from",
                e.target.value ? new Date(e.target.value).toISOString() : null,
              )
            }
            className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
          />
        </div>
        <div>
          <Label className="text-xs">Bitiş</Label>
          <input
            type="date"
            value={filters.date_to?.slice(0, 10) ?? ""}
            onChange={(e) =>
              setParam(
                "date_to",
                e.target.value
                  ? new Date(`${e.target.value}T23:59:59`).toISOString()
                  : null,
              )
            }
            className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
          />
        </div>
        <div>
          <Label className="text-xs">Kaynak</Label>
          <select
            value={filters.source_types?.join(",") ?? ""}
            onChange={(e) => setParam("source_types", e.target.value || null)}
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
            {dist.data && dist.data.total > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie
                    data={dist.data.data}
                    dataKey="count"
                    nameKey="label"
                    innerRadius={45}
                    outerRadius={80}
                    label
                  >
                    {dist.data.data.map((row) => (
                      <Cell key={row.label} fill={SENTIMENT_COLOURS[row.label] ?? "#888"} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Skor Histogramı</CardTitle>
          </CardHeader>
          <CardContent>
            {sens.data && sens.data.total > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={sens.data.buckets}>
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
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Duygu Trendi (gün)</CardTitle>
        </CardHeader>
        <CardContent>
          {tl.data && tl.data.data.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={tl.data.data}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" fontSize={10} />
                <YAxis fontSize={10} />
                <Tooltip />
                <Line type="monotone" dataKey="negatif" stroke="#dc2626" />
                <Line type="monotone" dataKey="nötr" stroke="#737373" />
                <Line type="monotone" dataKey="pozitif" stroke="#16a34a" />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState />
          )}
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
        {cats.data && cats.data.total > 0 ? (
          <ResponsiveContainer width="100%" height={Math.max(220, cats.data.data.length * 32)}>
            <BarChart layout="vertical" data={cats.data.data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" fontSize={10} />
              <YAxis type="category" dataKey="category_label_tr" fontSize={11} width={140} />
              <Tooltip />
              <Bar dataKey="count" fill="#1e40af" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <EmptyState />
        )}
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
        {matrix.data && matrix.data.categories.length > 0 ? (
          <Heatmap
            rows={matrix.data.category_labels_tr}
            cols={matrix.data.sentiments}
            matrix={matrix.data.matrix}
            rowTotals={matrix.data.totals_by_category}
            colTotals={matrix.data.totals_by_sentiment}
            colorScale="blue"
            tooltip={(value, rowLabel, colLabel) =>
              `${rowLabel} × ${colLabel}: ${value} analiz`
            }
            onCellClick={(i, j) => {
              const cat = matrix.data?.categories[i];
              const sent = matrix.data?.sentiments[j];
              if (!cat || !sent) return;
              router.push(
                `/reviews?sentiment_labels=${encodeURIComponent(sent)}&category=${encodeURIComponent(cat)}`,
              );
            }}
          />
        ) : (
          <EmptyState />
        )}
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
        {stats.data && stats.data.data.length > 0 ? (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={stats.data.data} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" fontSize={10} />
              <YAxis type="category" dataKey="layer_label_tr" fontSize={11} width={160} />
              <Tooltip />
              <Bar dataKey="trigger_count" fill="#1e40af" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <EmptyState />
        )}
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
          {res.data && res.data.total_resolved_tickets > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={res.data.distribution}>
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
                    {res.data.avg_resolution_hours.toFixed(1)} saat
                  </dd>
                </div>
                <div>
                  <dt>Ortanca</dt>
                  <dd className="text-foreground text-base font-semibold">
                    {res.data.median_resolution_hours.toFixed(1)} saat
                  </dd>
                </div>
                <div>
                  <dt>p95</dt>
                  <dd className="text-foreground text-base font-semibold">
                    {res.data.p95_resolution_hours.toFixed(1)} saat
                  </dd>
                </div>
              </dl>
            </>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function EmptyState() {
  return (
    <p className="text-muted-foreground py-8 text-center text-sm">
      Bu filtrelerle veri bulunamadı.
    </p>
  );
}
