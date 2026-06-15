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
//   * Tek birincil aksiyon. Fazla buton = fazla karar.
//
// Veri: useExecutiveOverview (tek round-trip). Memnuniyet sayıları
// tüm zamanlar; trend son 30 gün — etiketler buna göre.

import { ArrowRight, Minus, TrendingDown, TrendingUp, Upload } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { useCountUp, useMounted } from "@/hooks/use-count-up";
import type {
  ExecutiveOverview,
  ExecutiveSentimentTrend,
} from "@/hooks/use-executive-overview";

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
function headlineFor(band: Band): { prefix: string; keyword: string; suffix: string } {
  switch (band) {
    case "critical":
      return { prefix: "Müşterileriniz ", keyword: "memnun değil", suffix: "." };
    case "watch":
      return {
        prefix: "Müşterilerinizin bir kısmı ",
        keyword: "memnun değil",
        suffix: ".",
      };
    case "healthy":
      return { prefix: "Müşterileriniz ", keyword: "memnun", suffix: "." };
    default:
      return { prefix: "Müşteri memnuniyeti ", keyword: "dengeli", suffix: "." };
  }
}

interface Props {
  overview: ExecutiveOverview | undefined;
  isLoading: boolean;
}

export function ExecutiveHero({ overview, isLoading }: Props) {
  if (isLoading) return <Skeleton className="h-72 w-full rounded-3xl" />;
  if (!overview) return null;

  const { POZITIF, NEGATIF, total } = overview.sentiment;

  if (total === 0) {
    return (
      <section className="rise-in shadow-soft bg-card ring-foreground/5 rounded-3xl p-8 text-center ring-1 md:p-12">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
          Müşterilerinizin sesini dinlemeye başlayın
        </h2>
        <p className="text-muted-foreground mx-auto mt-3 max-w-xl text-base leading-relaxed">
          İlk yorum dosyanızı yükleyin — dakikalar içinde memnuniyet durumunuz,
          ana sorunlarınız ve yönetici özetiniz hazır olsun.
        </p>
        <Link
          href="/analyze/upload"
          className="bg-primary text-primary-foreground hover:bg-primary/90 mt-7 inline-flex items-center gap-2 rounded-2xl px-6 py-3 text-sm font-semibold transition-colors"
        >
          <Upload className="size-4" aria-hidden /> İlk dosyanızı yükleyin
        </Link>
      </section>
    );
  }

  const posPct = Math.round((POZITIF / total) * 100);
  const negPct = Math.round((NEGATIF / total) * 100);
  const notrPct = Math.max(0, 100 - posPct - negPct);
  const visual = bandFor(posPct, negPct);
  const headline = headlineFor(visual.band);

  return (
    <section
      className="rise-in shadow-soft bg-card ring-foreground/5 rounded-3xl p-6 ring-1 md:p-10"
      aria-label="Müşteri memnuniyet durumu"
    >
      <div className="flex flex-col gap-8 md:flex-row md:items-start md:justify-between md:gap-12">
        {/* Cevap — büyük, sade, tek cümle. */}
        <div className="min-w-0 flex-1">
          <p className="text-muted-foreground text-sm font-medium">
            Genel müşteri memnuniyeti
          </p>
          <h2 className="mt-2 text-3xl font-semibold leading-tight tracking-tight md:text-5xl md:leading-[1.1]">
            {headline.prefix}
            <span className={visual.keywordClass}>{headline.keyword}</span>
            {headline.suffix}
          </h2>
          <p className="text-muted-foreground mt-4 max-w-xl text-base leading-relaxed md:text-lg">
            Toplam{" "}
            <strong className="text-foreground font-semibold tabular-nums">
              {total.toLocaleString("tr-TR")}
            </strong>{" "}
            yorumdan{" "}
            <strong className="text-foreground font-semibold tabular-nums">
              {POZITIF.toLocaleString("tr-TR")}
            </strong>{" "}
            tanesi olumlu,{" "}
            <strong className="text-foreground font-semibold tabular-nums">
              {NEGATIF.toLocaleString("tr-TR")}
            </strong>{" "}
            tanesi olumsuz.
          </p>
          {overview.trend && <TrendPill trend={overview.trend} />}
        </div>

        {/* Büyük yüzde — destekleyici tek rakam. */}
        <div className="flex shrink-0 flex-col items-start md:items-end">
          <BigPercent pct={posPct} className={visual.numberClass} />
          <p className="text-muted-foreground mt-0.5 text-sm font-medium">
            memnuniyet
          </p>
          {overview.nps_score !== null && (
            <p className="text-muted-foreground mt-3 text-sm tabular-nums">
              NPS{" "}
              <strong className="text-foreground font-semibold">
                {overview.nps_score > 0 ? "+" : ""}
                {Math.round(overview.nps_score)}
              </strong>
            </p>
          )}
        </div>
      </div>

      {/* Segmentli memnuniyet çubuğu — tüm denge tek bakışta. */}
      <SatisfactionBar posPct={posPct} notrPct={notrPct} negPct={negPct} />

      {/* Tek birincil aksiyon — duruma göre yön. */}
      <div className="mt-7 flex flex-wrap items-center gap-x-6 gap-y-3">
        <Link
          href={
            visual.band === "healthy"
              ? "/reviews"
              : "/reviews?sentiment_labels=NEGATIF"
          }
          className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex items-center gap-2 rounded-2xl px-5 py-3 text-sm font-semibold transition-colors"
        >
          {visual.band === "healthy"
            ? "Müşteri yorumlarını incele"
            : "Olumsuz yorumları incele"}
          <ArrowRight className="size-4" aria-hidden />
        </Link>
        <Link
          href="/strategy"
          className="text-foreground/70 hover:text-foreground text-sm font-semibold transition-colors"
        >
          Aksiyon planı oluştur
        </Link>
      </div>
    </section>
  );
}

/** Son 30 gün vs önceki 30 gün memnuniyet değişimi — sakin, aydınlık
 *  rozet. |delta| < 1 puan: "değişmedi". */
function TrendPill({ trend }: { trend: ExecutiveSentimentTrend }) {
  const delta = trend.delta_points;
  const flat = Math.abs(delta) < 1;
  const up = delta >= 1;
  const Icon = flat ? Minus : up ? TrendingUp : TrendingDown;
  const cls = flat
    ? "bg-muted text-muted-foreground"
    : up
      ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
      : "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300";
  const label = flat
    ? "Son 30 günde memnuniyet değişmedi"
    : `Son 30 günde memnuniyet ${up ? "+" : "−"}${Math.abs(delta).toLocaleString("tr-TR")} puan ${up ? "arttı" : "düştü"}`;
  return (
    <span
      className={`mt-5 inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-sm font-medium tabular-nums ${cls}`}
    >
      <Icon className="size-4" aria-hidden />
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
 *  satırda. Açılışta soldan dolar. Altında sade lejant. */
function SatisfactionBar({
  posPct,
  notrPct,
  negPct,
}: {
  posPct: number;
  notrPct: number;
  negPct: number;
}) {
  const mounted = useMounted();
  return (
    <div className="mt-8">
      <div className="bg-muted flex h-3 w-full overflow-hidden rounded-full">
        <div
          className="h-full bg-emerald-500 transition-[width] duration-700 [transition-timing-function:var(--motion-ease)]"
          style={{ width: mounted ? `${posPct}%` : "0%" }}
        />
        <div
          className="h-full bg-zinc-300 transition-[width] duration-700 [transition-timing-function:var(--motion-ease)] dark:bg-zinc-600"
          style={{ width: mounted ? `${notrPct}%` : "0%" }}
        />
        <div
          className="h-full bg-red-500 transition-[width] duration-700 [transition-timing-function:var(--motion-ease)]"
          style={{ width: mounted ? `${negPct}%` : "0%" }}
        />
      </div>
      <div className="text-muted-foreground mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm">
        <LegendDot className="bg-emerald-500" label="Olumlu" pct={posPct} />
        <LegendDot className="bg-zinc-300 dark:bg-zinc-600" label="Nötr" pct={notrPct} />
        <LegendDot className="bg-red-500" label="Olumsuz" pct={negPct} />
      </div>
    </div>
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
