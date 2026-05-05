"use client";

// Sprint 8.3.9 — word cloud tab for /insights.
//
// CSS-only renderer: words rendered inline-flex with font-size
// scaled by weight and colour interpolated from sentiment_skew
// (red → grey → green). No external library — sidesteps the
// Next.js SSR + canvas concerns flagged in the sprint spec, and
// matches how Sprint 8.3.6 rendered the SWOT recommendations
// (CSS classes only).

import { useMemo } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { useInsightsWordCloud } from "@/hooks/use-insights-word-cloud";
import type { WordCloudSentiment, WordCloudWord } from "@/lib/types";

const SENTIMENT_LABELS: Record<WordCloudSentiment, string> = {
  all: "Tümü",
  positive: "Pozitif",
  negative: "Negatif",
  neutral: "Nötr",
};

interface Props {
  sentiment: WordCloudSentiment;
  taxonomyCode: string;
  includeBigrams: boolean;
  dateFrom: string;
  dateTo: string;
  onSentimentChange: (next: WordCloudSentiment) => void;
  onTaxonomyChange: (next: string) => void;
  onBigramsChange: (next: boolean) => void;
}

export function WordCloudTab({
  sentiment,
  taxonomyCode,
  includeBigrams,
  dateFrom,
  dateTo,
  onSentimentChange,
  onTaxonomyChange,
  onBigramsChange,
}: Props) {
  const query = useInsightsWordCloud({
    sentiment,
    taxonomy_code: taxonomyCode || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    include_bigrams: includeBigrams,
  });

  const { fontSizeFor, colorFor } = useMemo(
    () => buildScales(query.data?.words ?? []),
    [query.data],
  );

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="grid grid-cols-1 gap-3 p-4 md:grid-cols-4">
          <div>
            <Label className="text-xs">Duygu</Label>
            <select
              value={sentiment}
              onChange={(e) =>
                onSentimentChange(e.target.value as WordCloudSentiment)
              }
              className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
            >
              {(Object.keys(SENTIMENT_LABELS) as WordCloudSentiment[]).map(
                (s) => (
                  <option key={s} value={s}>
                    {SENTIMENT_LABELS[s]}
                  </option>
                ),
              )}
            </select>
          </div>
          <div className="md:col-span-2">
            <Label className="text-xs">Kategori filtresi (opsiyonel)</Label>
            <input
              value={taxonomyCode}
              onChange={(e) => onTaxonomyChange(e.target.value)}
              placeholder="kategori_kodu"
              className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
            />
          </div>
          <div className="flex items-end">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={includeBigrams}
                onChange={(e) => onBigramsChange(e.target.checked)}
                className="size-4"
              />
              İkili kelimeler
            </label>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Kelime Bulutu</CardTitle>
          </CardHeader>
          <CardContent className="min-h-[360px]">
            {query.isLoading || query.isPending ? (
              <p className="text-muted-foreground py-12 text-center text-sm">
                Yükleniyor…
              </p>
            ) : query.isError ? (
              <p className="text-destructive py-12 text-center text-sm">
                Veri yüklenemedi.
              </p>
            ) : !query.data || query.data.words.length === 0 ? (
              <p className="text-muted-foreground py-12 text-center text-sm">
                Bu filtrelerle gösterilecek kelime yok.
              </p>
            ) : (
              <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-2 p-4">
                {query.data.words.map((w) => (
                  <span
                    key={`${w.text}-${w.is_bigram ? "bg" : "ug"}`}
                    style={{
                      fontSize: `${fontSizeFor(w.weight)}px`,
                      color: colorFor(w.sentiment_skew),
                      lineHeight: 1.1,
                    }}
                    className={
                      w.is_bigram
                        ? "font-medium italic"
                        : "font-medium"
                    }
                    title={`${w.text} · ${w.weight} yorum · skew ${w.sentiment_skew.toFixed(2)}`}
                  >
                    {w.text}
                  </span>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">İlk 20 Kelime</CardTitle>
          </CardHeader>
          <CardContent>
            {!query.data || query.data.words.length === 0 ? (
              <p className="text-muted-foreground text-sm">—</p>
            ) : (
              <ul className="space-y-1 text-xs">
                {query.data.words.slice(0, 20).map((w) => (
                  <li
                    key={`top-${w.text}`}
                    className="flex items-center justify-between gap-2"
                  >
                    <span
                      className={w.is_bigram ? "italic" : ""}
                      style={{ color: colorFor(w.sentiment_skew) }}
                    >
                      {w.text}
                    </span>
                    <span className="text-muted-foreground tabular-nums">
                      {w.weight}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {query.data && (
              <p className="text-muted-foreground mt-3 text-xs">
                {query.data.total_reviews_analyzed} yorum analiz edildi.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

interface Scales {
  fontSizeFor: (weight: number) => number;
  colorFor: (skew: number) => string;
}

function buildScales(words: WordCloudWord[]): Scales {
  if (words.length === 0) {
    return {
      fontSizeFor: () => 14,
      colorFor: () => "#525252",
    };
  }
  const weights = words.map((w) => w.weight);
  const minW = Math.min(...weights);
  const maxW = Math.max(...weights);
  const fontMin = 12;
  const fontMax = 56;
  function fontSizeFor(weight: number): number {
    if (maxW === minW) return (fontMin + fontMax) / 2;
    const ratio = (weight - minW) / (maxW - minW);
    return Math.round(fontMin + ratio * (fontMax - fontMin));
  }
  // Sentiment skew ∈ [-1, 1] → red (#dc2626) ↔ grey (#737373) ↔
  // green (#16a34a). Linear interpolation in RGB space; good enough
  // visual quality for a dashboard tile.
  function colorFor(skew: number): string {
    const clamped = Math.max(-1, Math.min(1, skew));
    if (clamped < 0) {
      // -1 → red, 0 → grey
      const t = -clamped; // 0..1
      return mix("#737373", "#dc2626", t);
    }
    // 0 → grey, +1 → green
    return mix("#737373", "#16a34a", clamped);
  }
  return { fontSizeFor, colorFor };
}

function mix(from: string, to: string, t: number): string {
  const a = parseHex(from);
  const b = parseHex(to);
  const r = Math.round(a[0] + (b[0] - a[0]) * t);
  const g = Math.round(a[1] + (b[1] - a[1]) * t);
  const bl = Math.round(a[2] + (b[2] - a[2]) * t);
  return `rgb(${r}, ${g}, ${bl})`;
}

function parseHex(hex: string): [number, number, number] {
  const cleaned = hex.replace("#", "");
  return [
    parseInt(cleaned.slice(0, 2), 16),
    parseInt(cleaned.slice(2, 4), 16),
    parseInt(cleaned.slice(4, 6), 16),
  ];
}
