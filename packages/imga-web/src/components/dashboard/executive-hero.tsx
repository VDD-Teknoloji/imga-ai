"use client";

// Sprint 12 — C-level hero, "sakin cevap" nesli.
//
// Önceki sürüm (koyu komuta-merkezi + radyal gösterge + nabız +
// "KRİTİK DURUM" damgası + glow) ürün sahibi tarafından "çok yapay
// zeka ürünü gibi" bulundu. Yeni ilke Apple-vari sadelik:
//
//   * AYDINLIK kart — sayfanın geri kalanıyla aynı kağıt dünyada;
//     kopuk koyu panel yok, glow yok, nabız yok, sparkle yok.
//   * TEK CÜMLE cevap, çok büyük: "Müşterileriniz memnun." Yönetici
//     rakamı okumadan önce SONUCU okur. Anahtar kelime duruma göre
//     renklenir (yeşil / amber / kırmızı) — renk tek başına anlam.
//   * Büyük memnuniyet yüzdesi + altında tek bir SEGMENTLİ ÇUBUK
//     (olumlu / nötr / olumsuz oranı) — "depolama çubuğu" gibi tüm
//     dengeyi tek bakışta gösterir. Rakam değil, bilgi.
//
// Sprint 13 revizyonu (ürün sahibi görsel geri bildirimi):
//   * Trend rozetindeki ok ikonu kaldırıldı — sadece metin + renk.
//   * Memnuniyet skoru yanına "nasıl hesaplanıyor?" tooltip'i.
//   * Veri artık sayfadaki dönem filtresine göre pencereli gelir;
//     pencere boşsa hafif bir "bu dönemde yorum yok" kartı çizilir.
//   * SWOT analizine göze çarpan yönlendirme butonu.
//
// WS5 (2026-08-18): SatisfactionBar'ın üç segmenti tıklanabilir hale
// geldi — /insights heatmap'indeki handleCellClick deseniyle aynı:
// segment kendi duygusuyla filtrelenmiş /reviews'e router.push eder,
// sayfadaki aktif dönem varsa (dateFrom/dateTo) o da taşınır.

import { ArrowRight, Compass, Info, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useCountUp, useMounted } from "@/hooks/use-count-up";
import type {
  ExecutiveOverview,
  ExecutiveSentimentTrend,
} from "@/hooks/use-executive-overview";
import { useTranslation } from "@/lib/i18n/use-translation";

type Translate = (key: string, vars?: Record<string, string | number>) => string;

type SentimentCounts = ExecutiveOverview["sentiment"];

type Band = "healthy" | "watch" | "critical" | "balanced";

interface BandVisual {
  band: Band;
  /** Anahtar kelime rengi (aydınlık zeminde okunur ton). */
  keywordClass: string;
  /** Büyük yüzde rengi. */
  numberClass: string;
}

function bandFor(posPct: number, negPct: number): BandVisual {
  if (negPct >= 60) {
    return {
      band: "critical",
      keywordClass: "text-red-600 dark:text-red-400",
      numberClass: "text-red-600 dark:text-red-400",
    };
  }
  if (negPct >= 30) {
    return {
      band: "watch",
      keywordClass: "text-amber-600 dark:text-amber-400",
      numberClass: "text-amber-600 dark:text-amber-400",
    };
  }
  if (posPct >= 60) {
    return {
      band: "healthy",
      keywordClass: "text-emerald-600 dark:text-emerald-400",
      numberClass: "text-emerald-600 dark:text-emerald-400",
    };
  }
  return {
    band: "balanced",
    keywordClass: "text-foreground",
    numberClass: "text-foreground",
  };
}

/** Manşet: sabit önek + duruma göre renklenen anahtar kelime.
 *  Yöneticinin tek bakışta okuduğu "cevap". */
function headlineFor(
  band: Band,
  t: Translate,
): { prefix: string; keyword: string; suffix: string } {
  switch (band) {
    case "critical":
      return {
        prefix: t("dashboard.executiveHero.headline.critical.prefix"),
        keyword: t("dashboard.executiveHero.headline.critical.keyword"),
        suffix: ".",
      };
    case "watch":
      return {
        prefix: t("dashboard.executiveHero.headline.watch.prefix"),
        keyword: t("dashboard.executiveHero.headline.watch.keyword"),
        suffix: ".",
      };
    case "healthy":
      return {
        prefix: t("dashboard.executiveHero.headline.healthy.prefix"),
        keyword: t("dashboard.executiveHero.headline.healthy.keyword"),
        suffix: ".",
      };
    default:
      return {
        prefix: t("dashboard.executiveHero.headline.balanced.prefix"),
        keyword: t("dashboard.executiveHero.headline.balanced.keyword"),
        suffix: ".",
      };
  }
}

interface Props {
  /** Seçili döneme göre pencereli duygu sayıları. */
  sentiment: SentimentCounts | undefined;
  /** Son 30 gün vs önceki 30 gün (dönem filtresinden bağımsız). */
  trend: ExecutiveSentimentTrend | null | undefined;
  /** Seçili dönemin NPS skoru (veri yoksa null). */
  npsScore: number | null | undefined;
  isLoading: boolean;
  /** Tenant'ta (tüm zamanlar) hiç yorum var mı? Pencere-boş ile
   *  gerçekten-boş ayrımını bu yapar. */
  hasAnyData: boolean;
  /** Yükleme (batch) filtresi seçiliyken boş-pencere metni "seçilen
   *  dönem" değil "seçilen yükleme" der — dönemi genişletmek çare olmaz. */
  batchFilterActive?: boolean;
  /** Sayfadaki aktif dönem filtresi (YYYY-MM-DD) — SatisfactionBar
   *  segment tıklamasında /reviews URL'ine taşınır (WS5). */
  dateFrom?: string;
  dateTo?: string;
}

export function ExecutiveHero({
  sentiment,
  trend,
  npsScore,
  isLoading,
  hasAnyData,
  batchFilterActive = false,
  dateFrom,
  dateTo,
}: Props) {
  const { t } = useTranslation();
  const router = useRouter();
  if (isLoading || !sentiment) {
    return <Skeleton className="h-72 w-full rounded-3xl" />;
  }

  const { POZITIF, NEGATIF, total } = sentiment;

  if (total === 0 && !hasAnyData) {
    return (
      <section className="rise-in shadow-soft bg-card ring-foreground/5 rounded-3xl p-8 text-center ring-1 md:p-12">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {t("dashboard.executiveHero.empty.title")}
        </h2>
        <p className="text-muted-foreground mx-auto mt-3 max-w-xl text-base leading-relaxed">
          {t("dashboard.executiveHero.empty.desc")}
        </p>
        <Link
          href="/analyze/upload"
          className="bg-primary text-primary-foreground hover:bg-primary/90 mt-7 inline-flex items-center gap-2 rounded-2xl px-6 py-3 text-sm font-semibold transition-colors"
        >
          <Upload className="size-4" aria-hidden />{" "}
          {t("dashboard.executiveHero.empty.upload")}
        </Link>
      </section>
    );
  }

  if (total === 0) {
    // Veri var ama seçili dönem penceresi boş — dev boş-CTA yerine
    // sakin bir bilgilendirme (dönem filtresi hemen altta duruyor).
    return (
      <section className="rise-in shadow-soft bg-card ring-foreground/5 rounded-3xl p-8 ring-1 md:p-10">
        <h2 className="text-xl font-semibold tracking-tight md:text-2xl">
          {batchFilterActive
            ? t("dashboard.executiveHero.batchEmpty.title")
            : t("dashboard.executiveHero.windowEmpty.title")}
        </h2>
        <p className="text-muted-foreground mt-2 max-w-xl text-sm leading-relaxed">
          {batchFilterActive
            ? t("dashboard.executiveHero.batchEmpty.desc")
            : t("dashboard.executiveHero.windowEmpty.desc")}
        </p>
      </section>
    );
  }

  const posPct = Math.round((POZITIF / total) * 100);
  const negPct = Math.round((NEGATIF / total) * 100);
  const notrPct = Math.max(0, 100 - posPct - negPct);
  const visual = bandFor(posPct, negPct);
  const headline = headlineFor(visual.band, t);

  // WS5 — segment tıklaması /reviews'e duyguya göre filtrelenmiş gider;
  // sayfanın aktif dönem filtresi varsa (dateFrom/dateTo) o da taşınır
  // (heatmap-tab.tsx handleCellClick ile aynı URLSearchParams deseni).
  function handleSegmentClick(sentimentLabel: "POZITIF" | "NÖTR" | "NEGATIF") {
    const params = new URLSearchParams();
    params.set("sentiment_labels", sentimentLabel);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    router.push(`/reviews?${params.toString()}`);
  }

  return (
    <section
      className="rise-in shadow-soft bg-card ring-foreground/5 rounded-3xl p-6 ring-1 md:p-10"
      aria-label={t("dashboard.executiveHero.aria")}
    >
      <div className="flex flex-col gap-8 md:flex-row md:items-start md:justify-between md:gap-12">
        {/* Cevap — büyük, sade, tek cümle. */}
        <div className="min-w-0 flex-1">
          <p className="text-muted-foreground text-sm font-medium">
            {t("dashboard.executiveHero.overallLabel")}
          </p>
          <h2 className="mt-2 text-3xl font-semibold leading-tight tracking-tight md:text-5xl md:leading-[1.1]">
            {headline.prefix}
            <span className={visual.keywordClass}>{headline.keyword}</span>
            {headline.suffix}
          </h2>
          <p className="text-muted-foreground mt-4 max-w-xl text-base leading-relaxed md:text-lg">
            {t("dashboard.executiveHero.summary.prefix")}{" "}
            <strong className="text-foreground font-semibold tabular-nums">
              {total.toLocaleString("tr-TR")}
            </strong>{" "}
            {t("dashboard.executiveHero.summary.mid1")}{" "}
            <strong className="text-foreground font-semibold tabular-nums">
              {POZITIF.toLocaleString("tr-TR")}
            </strong>{" "}
            {t("dashboard.executiveHero.summary.mid2")}{" "}
            <strong className="text-foreground font-semibold tabular-nums">
              {NEGATIF.toLocaleString("tr-TR")}
            </strong>{" "}
            {t("dashboard.executiveHero.summary.suffix")}
          </p>
          {trend && <TrendPill trend={trend} />}
        </div>

        {/* Büyük yüzde — destekleyici tek rakam. */}
        <div className="flex shrink-0 flex-col items-start md:items-end">
          <BigPercent pct={posPct} className={visual.numberClass} />
          <p className="text-muted-foreground mt-0.5 inline-flex items-center gap-1.5 text-sm font-medium">
            {t("dashboard.executiveHero.satisfaction")}
            <ScoreInfoTip />
          </p>
          {npsScore !== null && npsScore !== undefined && (
            <p className="text-muted-foreground mt-3 text-sm tabular-nums">
              NPS{" "}
              <strong className="text-foreground font-semibold">
                {npsScore > 0 ? "+" : ""}
                {Math.round(npsScore)}
              </strong>
            </p>
          )}
        </div>
      </div>

      {/* Segmentli memnuniyet çubuğu — tüm denge tek bakışta, her segment
          tıklanabilir (WS5). */}
      <SatisfactionBar
        posPct={posPct}
        notrPct={notrPct}
        negPct={negPct}
        t={t}
        onSegmentClick={handleSegmentClick}
      />

      {/* Aksiyonlar — negatiflere git + göze çarpan SWOT kapısı. */}
      <div className="mt-7 flex flex-wrap items-center gap-3">
        <Link
          href={
            visual.band === "healthy"
              ? "/reviews"
              : "/reviews?sentiment_labels=NEGATIF"
          }
          className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex items-center gap-2 rounded-2xl px-5 py-3 text-sm font-semibold transition-colors"
        >
          {visual.band === "healthy"
            ? t("dashboard.executiveHero.reviewReviews")
            : t("dashboard.executiveHero.reviewNegative")}
          <ArrowRight className="size-4" aria-hidden />
        </Link>
        <Link
          href="/strategy?tab=swot"
          className="inline-flex items-center gap-2 rounded-2xl bg-gradient-to-r from-violet-600 to-indigo-600 px-5 py-3 text-sm font-semibold text-white shadow-md transition-all hover:from-violet-500 hover:to-indigo-500 hover:shadow-lg"
        >
          <Compass className="size-4" aria-hidden />
          {t("dashboard.executiveHero.swotCta")}
          <ArrowRight className="size-4" aria-hidden />
        </Link>
      </div>
    </section>
  );
}

/** Memnuniyet skorunun nasıl hesaplandığını açıklayan bilgi balonu.
 *  Ürün sahibi isteği: skor mantıklıysa açıklaması görünür olsun. */
function ScoreInfoTip() {
  const { t } = useTranslation();
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger
          aria-label={t("dashboard.executiveHero.scoreInfo.aria")}
          className="text-muted-foreground/70 hover:text-foreground inline-flex cursor-help items-center transition-colors"
        >
          <Info className="size-3.5" aria-hidden />
        </TooltipTrigger>
        <TooltipContent className="max-w-72 leading-relaxed">
          {t("dashboard.executiveHero.scoreInfo.text")}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/** Son 30 gün vs önceki 30 gün memnuniyet değişimi — sakin, aydınlık
 *  rozet. |delta| < 1 puan: "değişmedi". İkonsuz: renk + metin yeter
 *  (ürün sahibi görsel geri bildirimi, Sprint 13). */
function TrendPill({ trend }: { trend: ExecutiveSentimentTrend }) {
  const { t } = useTranslation();
  const delta = trend.delta_points;
  const flat = Math.abs(delta) < 1;
  const up = delta >= 1;
  const cls = flat
    ? "bg-muted text-muted-foreground"
    : up
      ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
      : "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300";
  const points = Math.abs(delta).toLocaleString("tr-TR");
  const label = flat
    ? t("dashboard.executiveHero.trend.flat")
    : up
      ? t("dashboard.executiveHero.trend.up", { points })
      : t("dashboard.executiveHero.trend.down", { points });
  return (
    <span
      className={`mt-5 inline-flex items-center rounded-full px-3.5 py-1.5 text-sm font-medium tabular-nums ${cls}`}
    >
      {label}
    </span>
  );
}

/** Büyük memnuniyet yüzdesi — açılışta sıfırdan sayar (sakin,
 *  reduced-motion'a saygılı). Glow/gösterge yok; sadece rakam. */
function BigPercent({ pct, className }: { pct: number; className: string }) {
  const counted = useCountUp(Math.max(0, Math.min(100, pct)), 900);
  return (
    <span
      className={`text-6xl font-semibold tabular-nums tracking-tight md:text-7xl ${className}`}
      style={{ letterSpacing: "-0.03em" }}
    >
      %{Math.round(counted)}
    </span>
  );
}

/** Apple-vari segmentli oran çubuğu: olumlu / nötr / olumsuz tek
 *  satırda. Açılışta soldan dolar. Altında sade lejant.
 *  Sprint 13: Deneyim Dağılımı kartları gibi büyük — segment içinde
 *  yüzde etiketi (dar segmentte gizlenir, lejant zaten taşıyor).
 *  WS5: her segment /reviews'e duyguya göre filtrelenmiş gider —
 *  role="img" (dekoratif) yerine role="group" + her segment kendi
 *  aria-label'ini taşıyan bir <button>. %0 segment odaklanabilir
 *  olmasın diye (0 genişlikli buton = klavye tuzağı) düz <div>
 *  kalır. */
function SatisfactionBar({
  posPct,
  notrPct,
  negPct,
  t,
  onSegmentClick,
}: {
  posPct: number;
  notrPct: number;
  negPct: number;
  t: Translate;
  onSegmentClick: (sentimentLabel: "POZITIF" | "NÖTR" | "NEGATIF") => void;
}) {
  const mounted = useMounted();
  const pctLabel = "text-lg font-semibold tabular-nums md:text-2xl";
  return (
    <div className="mt-8">
      <div
        className="bg-muted flex h-16 w-full overflow-hidden rounded-2xl md:h-20"
        role="group"
        aria-label={t("dashboard.executiveHero.satisfactionBarAria")}
      >
        <SatisfactionSegment
          pct={posPct}
          mounted={mounted}
          className="bg-gradient-to-br from-emerald-600 to-emerald-500 focus-visible:ring-white"
          textClassName="text-white"
          pctLabelClass={pctLabel}
          ariaLabel={t("dashboard.executiveHero.legend.segmentAria", {
            label: t("dashboard.executiveHero.legend.positive"),
            pct: posPct,
          })}
          onClick={() => onSegmentClick("POZITIF")}
        />
        <SatisfactionSegment
          pct={notrPct}
          mounted={mounted}
          className="bg-zinc-300 focus-visible:ring-zinc-700 dark:bg-zinc-600 dark:focus-visible:ring-zinc-100"
          textClassName="text-zinc-700 dark:text-zinc-100"
          pctLabelClass={pctLabel}
          ariaLabel={t("dashboard.executiveHero.legend.segmentAria", {
            label: t("dashboard.executiveHero.legend.neutral"),
            pct: notrPct,
          })}
          onClick={() => onSegmentClick("NÖTR")}
        />
        <SatisfactionSegment
          pct={negPct}
          mounted={mounted}
          className="bg-gradient-to-br from-red-600 to-red-500 focus-visible:ring-white"
          textClassName="text-white"
          pctLabelClass={pctLabel}
          ariaLabel={t("dashboard.executiveHero.legend.segmentAria", {
            label: t("dashboard.executiveHero.legend.negative"),
            pct: negPct,
          })}
          onClick={() => onSegmentClick("NEGATIF")}
        />
      </div>
      <div className="text-muted-foreground mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm">
        <LegendDot
          className="bg-emerald-500"
          label={t("dashboard.executiveHero.legend.positive")}
          pct={posPct}
        />
        <LegendDot
          className="bg-zinc-300 dark:bg-zinc-600"
          label={t("dashboard.executiveHero.legend.neutral")}
          pct={notrPct}
        />
        <LegendDot
          className="bg-red-500"
          label={t("dashboard.executiveHero.legend.negative")}
          pct={negPct}
        />
      </div>
    </div>
  );
}

/** Tek bir SatisfactionBar dilimi. %0 iken düz (odaklanamaz) <div>
 *  kalır — 0 genişlikli bir <button> klavye ile atlanamayan bir
 *  tuzağa dönüşür. focus-visible halkası `ring-inset` ile konteynerin
 *  `overflow-hidden`ı içinde kırpılmadan görünür. */
function SatisfactionSegment({
  pct,
  mounted,
  className,
  textClassName,
  pctLabelClass,
  ariaLabel,
  onClick,
}: {
  pct: number;
  mounted: boolean;
  className: string;
  textClassName: string;
  pctLabelClass: string;
  ariaLabel: string;
  onClick: () => void;
}) {
  const sharedClassName = `flex h-full items-center justify-center overflow-hidden transition-[width] duration-700 [transition-timing-function:var(--motion-ease)] ${className}`;
  const style = { width: mounted ? `${pct}%` : "0%" };

  if (pct <= 0) {
    return <div className={sharedClassName} style={style} aria-hidden />;
  }

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      className={`${sharedClassName} cursor-pointer hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset`}
      style={style}
    >
      {pct >= 8 && <span className={`${pctLabelClass} ${textClassName}`}>%{pct}</span>}
    </button>
  );
}

function LegendDot({
  className,
  label,
  pct,
}: {
  className: string;
  label: string;
  pct: number;
}) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className={`size-2.5 rounded-full ${className}`} aria-hidden />
      <span className="text-foreground/80 font-medium">{label}</span>
      <span className="tabular-nums">%{pct}</span>
    </span>
  );
}
