"use client";

// WS4 (2026-08-18) — /compare sayfası: iki bağımsız dönemi
// karşılaştırır (GET /tenants/me/analytics/period-comparison).
//
// URL state Path B (?a_from,a_to,b_from,b_to — YYYY-MM-DD, dördü de
// zorunlu; bkz. docs/agent-rules/url-state-patterns.md). Varsayılan:
// A = önceki ay, B = bu ay — URL boşken; ilk preset/serbest-aralık
// etkileşiminde URL materialize olur (bare /compare F5'te temiz kalır).
//
// Ay gezginindeki "şu an gezilen ay" cursor'ı URL'e YAZILMAZ — kullanıcı
// "Uygula"ya basana kadar taahhüt edilmemiş bir taslak (url-state-
// patterns.md'nin "Form draft input'ları" istisnası ile aynı kategori).

import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DateField } from "@/components/ui/date-field";
import { useCategories } from "@/hooks/use-categories";
import {
  type ComparisonDirection,
  type DateRange,
  type PeriodComparisonDelta,
  type PeriodComparisonResponse,
  type PeriodStats,
  isComparisonRangeValid,
  monthLabelKey,
  monthRange,
  monthRangeFor,
  usePeriodComparison,
  weekRange,
} from "@/hooks/use-period-comparison";
import { useTranslation } from "@/lib/i18n/use-translation";

const SENTIMENT_ORDER = ["NEGATIF", "NÖTR", "POZITIF"] as const;
const SENTIMENT_COLOURS: Record<string, string> = {
  NEGATIF: "#dc2626",
  NÖTR: "#737373",
  POZITIF: "#16a34a",
};

const EXPERIENCE_BUCKET_KEYS = ["dijital", "operasyonel", "atanmamis"] as const;
type ExperienceBucketKey = (typeof EXPERIENCE_BUCKET_KEYS)[number];

function defaultA(): DateRange {
  return monthRange(-1);
}
function defaultB(): DateRange {
  return monthRange(0);
}

// Sprint 8.3.4 round-2 pattern — Suspense wrapper zorunlu, useSearchParams
// Next.js 16'da bunu bekliyor (aksi halde hidration race).
export default function ComparePage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <CompareContent />
    </Suspense>
  );
}

function PageSkeleton() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6 md:px-8 md:py-10">
      <header className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {t("compare.page.title")}
        </h1>
        <p className="text-muted-foreground text-sm">{t("common.loading")}</p>
      </header>
    </main>
  );
}

function CompareContent() {
  const { t } = useTranslation();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [aFrom, setAFromState] = useState<string>(
    () => searchParams.get("a_from") ?? defaultA().from,
  );
  const [aTo, setAToState] = useState<string>(
    () => searchParams.get("a_to") ?? defaultA().to,
  );
  const [bFrom, setBFromState] = useState<string>(
    () => searchParams.get("b_from") ?? defaultB().from,
  );
  const [bTo, setBToState] = useState<string>(
    () => searchParams.get("b_to") ?? defaultB().to,
  );

  // Path B mirror — URL → state senkronizasyonu (back/forward, deep
  // link, F5 hidration). Aynı varsayımlar her iki tarafta da (lazy
  // init + effect) kullanılıyor ki F5 sonrası davranış tutarlı olsun.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const urlAFrom = searchParams.get("a_from") ?? defaultA().from;
    setAFromState((prev) => (prev === urlAFrom ? prev : urlAFrom));
    const urlATo = searchParams.get("a_to") ?? defaultA().to;
    setAToState((prev) => (prev === urlATo ? prev : urlATo));
    const urlBFrom = searchParams.get("b_from") ?? defaultB().from;
    setBFromState((prev) => (prev === urlBFrom ? prev : urlBFrom));
    const urlBTo = searchParams.get("b_to") ?? defaultB().to;
    setBToState((prev) => (prev === urlBTo ? prev : urlBTo));
    // INTENT: URL kaynak-of-truth; back/forward + deep-link navigasyonu
    // burada local state'e yansır (Path B pattern, url-state-patterns.md).
  }, [searchParams]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function pushParams(updates: Record<string, string | null>) {
    const params = new URLSearchParams(searchParams.toString());
    for (const [k, v] of Object.entries(updates)) {
      if (v === null || v === "") params.delete(k);
      else params.set(k, v);
    }
    const qs = params.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  function setPeriodA(range: DateRange) {
    setAFromState(range.from);
    setAToState(range.to);
    pushParams({ a_from: range.from, a_to: range.to });
  }
  function setPeriodB(range: DateRange) {
    setBFromState(range.from);
    setBToState(range.to);
    pushParams({ b_from: range.from, b_to: range.to });
  }
  // Çift preset kısayolu (ör. "Geçen ay vs Bu ay") dört parametreyi TEK
  // history entry'sinde yazar — ayrı ayrı push, back butonunu kırık ara
  // durumlardan geçirirdi.
  function setBothPeriods(a: DateRange, b: DateRange) {
    setAFromState(a.from);
    setAToState(a.to);
    setBFromState(b.from);
    setBToState(b.to);
    pushParams({ a_from: a.from, a_to: a.to, b_from: b.from, b_to: b.to });
  }
  function setCustomA(from: string, to: string) {
    setAFromState(from);
    setAToState(to);
    pushParams({ a_from: from || null, a_to: to || null });
  }
  function setCustomB(from: string, to: string) {
    setBFromState(from);
    setBToState(to);
    pushParams({ b_from: from || null, b_to: to || null });
  }

  const params = useMemo(
    () => ({ aFrom, aTo, bFrom, bTo }),
    [aFrom, aTo, bFrom, bTo],
  );
  const rangeValid = isComparisonRangeValid(params);
  const comparison = usePeriodComparison(params);

  const categories = useCategories();
  const categoryLabelMap = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of categories.data ?? []) m.set(c.code, c.label_tr);
    return m;
  }, [categories.data]);

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6 md:px-8 md:py-10">
      <header className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {t("compare.page.title")}
        </h1>
        <p className="text-muted-foreground text-sm">
          {t("compare.page.subtitle")}
        </p>
      </header>

      <PairPresets onSelect={setBothPeriods} />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <PeriodPickerGroup
          groupLabel={t("compare.group.a")}
          ariaLabel={t("compare.group.aAria")}
          from={aFrom}
          to={aTo}
          onPreset={setPeriodA}
          onCustomChange={setCustomA}
        />
        <PeriodPickerGroup
          groupLabel={t("compare.group.b")}
          ariaLabel={t("compare.group.bAria")}
          from={bFrom}
          to={bTo}
          onPreset={setPeriodB}
          onCustomChange={setCustomB}
        />
      </div>

      {!rangeValid && (
        <div className="bg-muted/40 border-border rounded-2xl border px-4 py-2.5 text-xs">
          <span className="text-muted-foreground">
            {t("compare.state.incompleteRange")}
          </span>
        </div>
      )}

      {rangeValid && comparison.error && (
        <Card>
          <CardContent className="p-6 text-sm">
            <p className="text-destructive">
              {t("compare.state.loadError", {
                message: comparison.error.message,
              })}
            </p>
          </CardContent>
        </Card>
      )}

      {rangeValid && !comparison.error && (comparison.isLoading || !comparison.data) && (
        <Card>
          <CardContent className="text-muted-foreground p-6 text-sm">
            {t("compare.state.loading")}
          </CardContent>
        </Card>
      )}

      {comparison.data && (
        <CompareResults
          data={comparison.data}
          categoryLabelMap={categoryLabelMap}
        />
      )}
    </main>
  );
}

// --- dönem seçim UI --------------------------------------------------

function PairPresets({
  onSelect,
}: {
  onSelect: (a: DateRange, b: DateRange) => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="flex flex-wrap items-center gap-2"
      role="group"
      aria-label={t("compare.pair.label")}
    >
      <span className="text-muted-foreground text-sm font-medium">
        {t("compare.pair.label")}
      </span>
      <Button
        variant="outline"
        size="sm"
        onClick={() => onSelect(monthRange(-1), monthRange(0))}
      >
        {t("compare.pair.lastMonthVsThisMonth")}
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={() => onSelect(weekRange(-1), weekRange(0))}
      >
        {t("compare.pair.lastWeekVsThisWeek")}
      </Button>
    </div>
  );
}

function PeriodPickerGroup({
  groupLabel,
  ariaLabel,
  from,
  to,
  onPreset,
  onCustomChange,
}: {
  groupLabel: string;
  ariaLabel: string;
  from: string;
  to: string;
  onPreset: (range: DateRange) => void;
  onCustomChange: (from: string, to: string) => void;
}) {
  const { t } = useTranslation();
  const now = new Date();
  // Ay gezgini kendi taslak cursor'ını taşır (bkz. dosya başı notu) —
  // URL'e yazılmaz, yalnız "Uygula" tıklanınca onPreset ile taahhüt edilir.
  const [navYear, setNavYear] = useState<number>(
    () => Number(from.slice(0, 4)) || now.getFullYear(),
  );
  const [navMonth, setNavMonth] = useState<number>(
    () => Number(from.slice(5, 7)) || now.getMonth() + 1,
  );

  function stepMonth(delta: number) {
    let m = navMonth + delta;
    let y = navYear;
    if (m < 1) {
      m = 12;
      y -= 1;
    } else if (m > 12) {
      m = 1;
      y += 1;
    }
    setNavMonth(m);
    setNavYear(y);
  }

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">{groupLabel}</h3>
          <span className="text-muted-foreground text-xs tabular-nums">
            {t("compare.group.rangeLabel", { from, to })}
          </span>
        </div>

        <div className="flex flex-wrap gap-1.5" role="group" aria-label={ariaLabel}>
          <Button variant="outline" size="sm" onClick={() => onPreset(monthRange(0))}>
            {t("compare.preset.thisMonth")}
          </Button>
          <Button variant="outline" size="sm" onClick={() => onPreset(monthRange(-1))}>
            {t("compare.preset.lastMonth")}
          </Button>
          <Button variant="outline" size="sm" onClick={() => onPreset(weekRange(0))}>
            {t("compare.preset.thisWeek")}
          </Button>
          <Button variant="outline" size="sm" onClick={() => onPreset(weekRange(-1))}>
            {t("compare.preset.lastWeek")}
          </Button>
        </div>

        <div className="flex items-center gap-1.5">
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={t("compare.monthNav.prevAria")}
            onClick={() => stepMonth(-1)}
          >
            <ChevronLeft className="size-4" aria-hidden />
          </Button>
          <span className="min-w-[7rem] text-center text-sm font-medium tabular-nums">
            {t(monthLabelKey(navMonth))} {navYear}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={t("compare.monthNav.nextAria")}
            onClick={() => stepMonth(1)}
          >
            <ChevronRight className="size-4" aria-hidden />
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => onPreset(monthRangeFor(navYear, navMonth))}
          >
            {t("compare.monthNav.apply")}
          </Button>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-muted-foreground text-xs font-medium">
            {t("compare.custom.label")}
          </span>
          <DateField
            value={from}
            max={to || undefined}
            aria-label={t("compare.custom.fromAria")}
            onChange={(e) => onCustomChange(e.target.value, to)}
          />
          <span className="text-muted-foreground text-xs" aria-hidden>
            –
          </span>
          <DateField
            value={to}
            min={from || undefined}
            aria-label={t("compare.custom.toAria")}
            onChange={(e) => onCustomChange(from, e.target.value)}
          />
        </div>
      </CardContent>
    </Card>
  );
}

// --- sonuç bölümü ------------------------------------------------------

function pctOf(count: number, total: number): number {
  return total === 0 ? 0 : (100 * count) / total;
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

function localDirection(diff: number): ComparisonDirection {
  if (diff === 0) return "flat";
  return diff > 0 ? "up" : "down";
}

function signedInt(n: number, nf: Intl.NumberFormat): string {
  return `${n >= 0 ? "+" : ""}${nf.format(n)}`;
}

function signedNum(n: number, decimals: number): string {
  return `${n >= 0 ? "+" : ""}${n.toFixed(decimals)}`;
}

/** Gerçek yön her zaman ok yönünü belirler; ``reversed`` sadece TONU
 *  (renk) çevirir — "Olumsuz Payı" gibi artışın kötü olduğu kartlarda. */
function directionTone(
  direction: ComparisonDirection,
  reversed: boolean,
): ComparisonDirection {
  if (direction === "flat" || !reversed) return direction;
  return direction === "up" ? "down" : "up";
}

const TONE_CLASSES: Record<ComparisonDirection, string> = {
  up: "bg-emerald-50 border-emerald-300 text-emerald-800 dark:bg-emerald-950/30 dark:border-emerald-900/50 dark:text-emerald-300",
  down: "bg-red-50 border-red-300 text-red-800 dark:bg-red-950/30 dark:border-red-900/50 dark:text-red-300",
  flat: "bg-zinc-50 border-zinc-300 text-zinc-700 dark:bg-zinc-900/40 dark:border-zinc-800 dark:text-zinc-300",
};

function DirectionArrow({ direction }: { direction: ComparisonDirection }) {
  if (direction === "up") return <ArrowUp className="size-3.5" aria-hidden />;
  if (direction === "down") return <ArrowDown className="size-3.5" aria-hidden />;
  return <ArrowRight className="size-3.5" aria-hidden />;
}

interface KpiDef {
  key: string;
  label: string;
  aText: string;
  bText: string;
  diffText: string;
  direction: ComparisonDirection;
  reversed: boolean;
}

function CompareResults({
  data,
  categoryLabelMap,
}: {
  data: PeriodComparisonResponse;
  categoryLabelMap: Map<string, string>;
}) {
  const { t, locale } = useTranslation();
  const nf = useMemo(
    () => new Intl.NumberFormat(locale === "en" ? "en-US" : "tr-TR"),
    [locale],
  );
  const { period_a: periodA, period_b: periodB, delta } = data;

  const negA = pctOf(periodA.sentiment_counts.NEGATIF ?? 0, periodA.total_reviews);
  const negB = pctOf(periodB.sentiment_counts.NEGATIF ?? 0, periodB.total_reviews);
  const negDiff = delta.sentiment_pct_point_diff.NEGATIF ?? round1(negB - negA);
  const negDirection = localDirection(negDiff);

  const kpis: KpiDef[] = [
    {
      key: "total",
      label: t("compare.kpi.totalReviews"),
      aText: nf.format(periodA.total_reviews),
      bText: nf.format(periodB.total_reviews),
      diffText: signedInt(delta.total_reviews_diff, nf),
      direction: delta.total_reviews_direction,
      reversed: false,
    },
    {
      key: "nps",
      label: t("compare.kpi.nps"),
      aText:
        periodA.nps.score === null
          ? t("compare.kpi.noValue")
          : String(Math.round(periodA.nps.score)),
      bText:
        periodB.nps.score === null
          ? t("compare.kpi.noValue")
          : String(Math.round(periodB.nps.score)),
      diffText:
        delta.nps_score_diff === null
          ? t("compare.kpi.noValue")
          : signedNum(delta.nps_score_diff, 1),
      direction: delta.nps_direction,
      reversed: false,
    },
    {
      key: "avg",
      label: t("compare.kpi.avgScore"),
      aText:
        periodA.avg_sentiment_score === null
          ? t("compare.kpi.noValue")
          : periodA.avg_sentiment_score.toFixed(2),
      bText:
        periodB.avg_sentiment_score === null
          ? t("compare.kpi.noValue")
          : periodB.avg_sentiment_score.toFixed(2),
      diffText:
        delta.avg_sentiment_score_diff === null
          ? t("compare.kpi.noValue")
          : signedNum(delta.avg_sentiment_score_diff, 2),
      direction: delta.avg_sentiment_direction,
      reversed: false,
    },
    {
      key: "negShare",
      label: t("compare.kpi.negativeShare"),
      aText: `%${negA.toFixed(1)}`,
      bText: `%${negB.toFixed(1)}`,
      diffText: `${signedNum(negDiff, 1)} ${t("compare.kpi.pointsSuffix")}`,
      // Artış (up) burada kötü haber — "Olumsuz Payı" büyüdü demek.
      direction: negDirection,
      reversed: true,
    },
  ];

  const categoryRows = useMemo(
    () => buildCategoryRows(periodA, periodB, delta, categoryLabelMap),
    [periodA, periodB, delta, categoryLabelMap],
  );

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {kpis.map((k) => (
          <KpiDeltaCard
            key={k.key}
            label={k.label}
            aText={k.aText}
            bText={k.bText}
            diffText={k.diffText}
            direction={k.direction}
            reversed={k.reversed}
          />
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <SentimentComparisonCard periodA={periodA} periodB={periodB} />
        <CategoryComparisonCard rows={categoryRows} />
      </div>

      <ExperienceComparisonCard periodA={periodA} periodB={periodB} />

      <ChangeStrip rows={categoryRows} />
    </div>
  );
}

function KpiDeltaCard({ label, aText, bText, diffText, direction, reversed }: KpiDef) {
  const { t } = useTranslation();
  const tone = directionTone(direction, reversed);
  return (
    <div className={`rounded-2xl border p-4 ${TONE_CLASSES[tone]}`}>
      <p className="text-xs font-medium">{label}</p>
      <p className="mt-1 flex items-center gap-1 text-2xl font-semibold tabular-nums">
        <span className="sr-only">{t(`compare.direction.${direction}`)}</span>
        <DirectionArrow direction={direction} />
        {diffText}
      </p>
      <p className="mt-1 text-xs tabular-nums opacity-80">
        {t("compare.kpi.aValue", { value: aText })} → {t("compare.kpi.bValue", { value: bText })}
      </p>
    </div>
  );
}

// --- duygu dağılımı ------------------------------------------------------

function SentimentComparisonCard({
  periodA,
  periodB,
}: {
  periodA: PeriodStats;
  periodB: PeriodStats;
}) {
  const { t } = useTranslation();
  const dataA = SENTIMENT_ORDER.map((label) => ({
    label,
    count: periodA.sentiment_counts[label] ?? 0,
  }));
  const dataB = SENTIMENT_ORDER.map((label) => ({
    label,
    count: periodB.sentiment_counts[label] ?? 0,
  }));
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("compare.section.sentiment")}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-2">
          <SentimentDonut title={t("compare.group.a")} data={dataA} />
          <SentimentDonut title={t("compare.group.b")} data={dataB} />
        </div>
        <ul className="mt-3 flex flex-wrap justify-center gap-3 text-xs">
          {SENTIMENT_ORDER.map((label) => (
            <li key={label} className="flex items-center gap-1.5">
              <span
                className="inline-block size-2.5 rounded-full"
                style={{ backgroundColor: SENTIMENT_COLOURS[label] }}
                aria-hidden
              />
              {t(`compare.sentiment.${label}`)}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function SentimentDonut({
  title,
  data,
}: {
  title: string;
  data: Array<{ label: string; count: number }>;
}) {
  const { t } = useTranslation();
  const total = data.reduce((sum, d) => sum + d.count, 0);
  return (
    <div className="flex flex-col items-center">
      <p className="text-muted-foreground text-xs font-medium">{title}</p>
      {total === 0 ? (
        <div className="flex h-[140px] items-center justify-center">
          <p className="text-muted-foreground text-xs">{t("compare.state.noPeriodData")}</p>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={140}>
          <PieChart>
            <Pie data={data} dataKey="count" nameKey="label" innerRadius={32} outerRadius={58}>
              {data.map((row) => (
                <Cell key={row.label} fill={SENTIMENT_COLOURS[row.label] ?? "#888"} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// --- kategori dağılımı -----------------------------------------------

interface CategoryRow {
  code: string;
  label: string;
  aCount: number;
  bCount: number;
  aPct: number;
  bPct: number;
  /** Yüzde puan farkı (B − A) — kategorinin TOPLAM yorum içindeki
   *  payı üzerinden; NEGATİF pay bazlı DEĞİL (backend
   *  `_pct_point_diff_map` — category_counts tüm sentiment'leri kapsar). */
  diff: number;
}

function buildCategoryRows(
  periodA: PeriodStats,
  periodB: PeriodStats,
  delta: PeriodComparisonDelta,
  labelMap: Map<string, string>,
): CategoryRow[] {
  const codes = new Set([
    ...Object.keys(periodA.category_counts),
    ...Object.keys(periodB.category_counts),
  ]);
  const rows: CategoryRow[] = [...codes].map((code) => {
    const aCount = periodA.category_counts[code] ?? 0;
    const bCount = periodB.category_counts[code] ?? 0;
    return {
      code,
      label: labelMap.get(code) ?? code,
      aCount,
      bCount,
      aPct: pctOf(aCount, periodA.total_reviews),
      bPct: pctOf(bCount, periodB.total_reviews),
      diff: delta.category_pct_point_diff[code] ?? 0,
    };
  });
  // B döneminde en çok görülenler önce — "şu an neye bakıyoruz" sorusuna
  // en güncel dönem cevap verir.
  rows.sort((r1, r2) => r2.bCount - r1.bCount);
  return rows;
}

function CategoryComparisonCard({ rows }: { rows: CategoryRow[] }) {
  const { t } = useTranslation();
  const top8 = rows.slice(0, 8);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("compare.section.category")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {top8.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("compare.category.empty")}</p>
        ) : (
          <ul className="space-y-2">
            {top8.map((row) => (
              <li key={row.code} className="flex items-center justify-between gap-3 text-sm">
                <span className="truncate">{row.label}</span>
                <span className="flex shrink-0 flex-col items-end gap-0.5 text-xs">
                  <span className="text-muted-foreground tabular-nums">
                    {row.aCount} ({row.aPct.toFixed(1)}%) → {row.bCount} ({row.bPct.toFixed(1)}%)
                  </span>
                  <Badge variant="outline" className="tabular-nums">
                    {signedNum(row.diff, 1)} {t("compare.kpi.pointsSuffix")}
                  </Badge>
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="text-muted-foreground text-xs leading-relaxed">
          {t("compare.section.categoryNote")}
        </p>
      </CardContent>
    </Card>
  );
}

// --- deneyim dağılımı --------------------------------------------------

const EXPERIENCE_LABEL_KEYS: Record<ExperienceBucketKey, string> = {
  dijital: "compare.experience.digital",
  operasyonel: "compare.experience.operational",
  atanmamis: "compare.experience.unassigned",
};

function ExperienceComparisonCard({
  periodA,
  periodB,
}: {
  periodA: PeriodStats;
  periodB: PeriodStats;
}) {
  const { t, locale } = useTranslation();
  const nf = useMemo(
    () => new Intl.NumberFormat(locale === "en" ? "en-US" : "tr-TR"),
    [locale],
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("compare.section.experience")}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {EXPERIENCE_BUCKET_KEYS.map((key) => {
            const a = periodA.experience[key];
            const b = periodB.experience[key];
            const diff = b.total - a.total;
            return (
              <div key={key} className="rounded-xl border p-3">
                <p className="text-muted-foreground text-xs font-medium">
                  {t(EXPERIENCE_LABEL_KEYS[key])}
                </p>
                <p className="mt-1 text-lg font-semibold tabular-nums">
                  {nf.format(a.total)} → {nf.format(b.total)}
                </p>
                <p className="text-muted-foreground text-xs tabular-nums">
                  {diff >= 0 ? "+" : ""}
                  {nf.format(diff)}
                </p>
                <div className="text-muted-foreground mt-2 flex justify-between text-[11px] tabular-nums">
                  <span>{t("compare.experience.negativeOf", { count: nf.format(a.negatif) })}</span>
                  <span>{t("compare.experience.negativeOf", { count: nf.format(b.negatif) })}</span>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

// --- "hangi adımda iyileşildi/kötüleşildi" şeridi -----------------------

function ChangeStrip({ rows }: { rows: CategoryRow[] }) {
  const { t } = useTranslation();
  // "belirsiz" sınıflandırılamayan yorumları temsil eder (Sprint 9.8
  // Madde 10/11 hatırlatması) — sıralamadan çıkarılır, gürültü sayılır.
  const ranked = rows.filter((r) => r.code.toLowerCase() !== "belirsiz" && r.diff !== 0);
  const worsened = [...ranked].sort((a, b) => b.diff - a.diff).slice(0, 3);
  const improved = [...ranked].sort((a, b) => a.diff - b.diff).slice(0, 3);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("compare.strip.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-muted-foreground text-xs leading-relaxed">
          {t("compare.strip.subtitle")}
        </p>
        {ranked.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("compare.strip.empty")}</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <ChangeList title={t("compare.strip.improved")} rows={improved} tone="down" />
            <ChangeList title={t("compare.strip.worsened")} rows={worsened} tone="up" />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ChangeList({
  title,
  rows,
  tone,
}: {
  title: string;
  rows: CategoryRow[];
  tone: "up" | "down";
}) {
  const { t } = useTranslation();
  const toneClass =
    tone === "up"
      ? "text-red-700 dark:text-red-400"
      : "text-emerald-700 dark:text-emerald-400";
  return (
    <div>
      <h4 className="text-muted-foreground text-xs font-semibold">{title}</h4>
      {rows.length === 0 ? (
        <p className="text-muted-foreground mt-1 text-xs">—</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {rows.map((r) => (
            <li key={r.code} className="flex items-center justify-between gap-2 text-sm">
              <span className="truncate">{r.label}</span>
              <span className={`shrink-0 text-xs font-medium tabular-nums ${toneClass}`}>
                {signedNum(r.diff, 1)} {t("compare.kpi.pointsSuffix")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
