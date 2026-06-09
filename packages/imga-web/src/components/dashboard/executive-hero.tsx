"use client";

// Sprint 10.1 — C-level hero, "Komuta Merkezi" nesli.
//
// İlk sürüm (beyaz kart + üç sayı + ince bar) kullanıcı testinde
// "etkisiz" bulundu: %81 memnuniyetsizlik sıradan bir bilgi gibi
// duruyordu. Bu sürümün ilkesi: YÜZEY DURUMU HAYKIRIR.
//
//   * Koyu (grafit + indigo glow) panel — sayfanın geri kalanından
//     kopar, göz önce buraya gider.
//   * Dev radyal gösterge: Memnuniyet Skoru (pozitif oran). Renk
//     duruma göre: yeşil / amber / kırmızı.
//   * Durum damgası: "KRİTİK DURUM" / "DİKKAT GEREKİYOR" /
//     "SAĞLIKLI GÖRÜNÜM" — nabız noktası + glow ile.
//   * Tek cümle Türkçe anlatı + İKİ aksiyon butonu: yönetici
//     okumakla kalmaz, harekete geçer.
//
// Veri: useExecutiveOverview (tek round-trip).

import {
  ArrowRight,
  Minus,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Upload,
} from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import type {
  ExecutiveOverview,
  ExecutiveSentimentTrend,
} from "@/hooks/use-executive-overview";

type Band = "healthy" | "watch" | "critical" | "balanced";

interface BandVisual {
  band: Band;
  stamp: string;
  stampClass: string;
  dotClass: string;
  gaugeStroke: string;
  gaugeGlow: string;
}

function bandFor(posPct: number, negPct: number): BandVisual {
  if (negPct >= 60) {
    return {
      band: "critical",
      stamp: "KRİTİK DURUM",
      stampClass:
        "bg-red-500/15 text-red-300 ring-1 ring-red-500/40 shadow-[0_0_28px_-6px_rgba(239,68,68,0.6)]",
      dotClass: "bg-red-400",
      gaugeStroke: "#f87171",
      gaugeGlow: "rgba(248,113,113,0.45)",
    };
  }
  if (negPct >= 30) {
    return {
      band: "watch",
      stamp: "DİKKAT GEREKİYOR",
      stampClass:
        "bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/40 shadow-[0_0_28px_-6px_rgba(245,158,11,0.5)]",
      dotClass: "bg-amber-400",
      gaugeStroke: "#fbbf24",
      gaugeGlow: "rgba(251,191,36,0.4)",
    };
  }
  if (posPct >= 60) {
    return {
      band: "healthy",
      stamp: "SAĞLIKLI GÖRÜNÜM",
      stampClass:
        "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/40 shadow-[0_0_28px_-6px_rgba(16,185,129,0.5)]",
      dotClass: "bg-emerald-400",
      gaugeStroke: "#34d399",
      gaugeGlow: "rgba(52,211,153,0.4)",
    };
  }
  return {
    band: "balanced",
    stamp: "DENGELİ GÖRÜNÜM",
    stampClass: "bg-white/10 text-zinc-200 ring-1 ring-white/20",
    dotClass: "bg-zinc-300",
    gaugeStroke: "#a5b4fc",
    gaugeGlow: "rgba(165,180,252,0.35)",
  };
}

function narrative(o: ExecutiveOverview, posPct: number, negPct: number): string {
  const top = o.top_problems[0];
  const parts: string[] = [];
  if (negPct >= 60) {
    parts.push(`Müşterilerinizin %${negPct}'i memnun değil.`);
  } else if (negPct >= 30) {
    parts.push(`Müşterilerinizin %${negPct}'i olumsuz görüş bildirdi.`);
  } else if (posPct >= 60) {
    // Kutlama tonu — sağlıklı tenant'ta hero önce kazanımı söyler.
    parts.push(`Güçlü görünüm: müşterilerinizin %${posPct}'i memnun.`);
  } else {
    parts.push(`Görünüm dengeli — %${posPct} memnun, %${negPct} memnun değil.`);
  }
  // Sağlıklı tablodaki marjinal şikayeti manşete taşıma; sorun
  // cümlesi ancak olumsuzluk anlamlıysa hero'ya girer (Ana Sorunlar
  // bloğu zaten detayı verir).
  if (top && negPct >= 10) {
    parts.push(
      `Olumsuz yorumların %${Math.round(top.share_pct)}'i ${top.label} kaynaklı.`,
    );
  }
  return parts.join(" ");
}

interface Props {
  overview: ExecutiveOverview | undefined;
  isLoading: boolean;
}

export function ExecutiveHero({ overview, isLoading }: Props) {
  if (isLoading) return <Skeleton className="h-80 w-full rounded-3xl" />;
  if (!overview) return null;

  const { POZITIF, NEGATIF, total } = overview.sentiment;
  const notrCount = overview.sentiment["NÖTR"];

  if (total === 0) {
    return (
      <section className="rise-in shadow-elevated relative overflow-hidden rounded-3xl bg-zinc-950 p-10 text-center ring-1 ring-white/10">
        <HeroGlow color="rgba(99,102,241,0.35)" />
        <h2 className="relative text-2xl md:text-3xl font-semibold tracking-tight text-white">
          Müşterilerinizin sesini dinlemeye başlayın
        </h2>
        <p className="relative mx-auto mt-3 max-w-xl text-sm md:text-base leading-relaxed text-zinc-400">
          İlk yorum dosyanızı yükleyin — yapay zeka dakikalar içinde duygu
          analizini, kategorileri ve yönetici özetini hazırlasın.
        </p>
        <Link
          href="/analyze/upload"
          className="relative mt-6 inline-flex items-center gap-2 rounded-xl bg-white px-6 py-3 text-sm font-semibold text-zinc-900 transition-transform hover:scale-[1.03]"
        >
          <Upload className="size-4" aria-hidden /> İlk dosyanızı yükleyin
        </Link>
      </section>
    );
  }

  const posPct = Math.round((POZITIF / total) * 100);
  const negPct = Math.round((NEGATIF / total) * 100);
  const visual = bandFor(posPct, negPct);
  const text = narrative(overview, posPct, negPct);

  return (
    <section
      className="rise-in shadow-elevated relative overflow-hidden rounded-3xl bg-zinc-950 p-6 md:p-10 ring-1 ring-white/10"
      aria-label="Müşteri memnuniyet durumu"
    >
      <HeroGlow color={visual.gaugeGlow} />

      <div className="relative flex flex-col items-center gap-8 md:flex-row md:items-center md:gap-12">
        {/* Dev radyal gösterge — tek dominant sayı. */}
        <RadialGauge
          pct={posPct}
          stroke={visual.gaugeStroke}
          glow={visual.gaugeGlow}
        />

        <div className="flex-1 text-center md:text-left">
          {/* Durum damgası — nabız + glow. */}
          <span
            className={`inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs md:text-sm font-bold tracking-[0.14em] ${visual.stampClass}`}
          >
            <span className="relative flex size-2">
              <span
                className={`absolute inline-flex size-full animate-ping rounded-full opacity-60 ${visual.dotClass}`}
              />
              <span
                className={`relative inline-flex size-2 rounded-full ${visual.dotClass}`}
              />
            </span>
            {visual.stamp}
          </span>

          <p className="mt-4 text-xl md:text-3xl font-semibold leading-snug tracking-tight text-white max-w-2xl">
            {text}
          </p>

          {/* Trend — "hareket ediyor muyuz?" Statik fotoğraf değil,
              yön. Önceki 30 günde veri yoksa hiç görünmez. */}
          {overview.trend && <TrendPill trend={overview.trend} />}

          {/* Sayı chip'leri — ikincil seviye. */}
          <div className="mt-5 flex flex-wrap items-center justify-center gap-2.5 md:justify-start">
            <CountChip dot="bg-emerald-400" label="Pozitif" value={POZITIF} />
            <CountChip dot="bg-zinc-400" label="Nötr" value={notrCount} />
            <CountChip dot="bg-red-400" label="Negatif" value={NEGATIF} />
            {overview.nps_score !== null && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/8 px-3 py-1.5 text-xs font-medium text-zinc-200 ring-1 ring-white/15 tabular-nums">
                NPS{" "}
                <strong className="text-white">
                  {overview.nps_score > 0 ? "+" : ""}
                  {Math.round(overview.nps_score)}
                </strong>
              </span>
            )}
            <span className="inline-flex items-center rounded-full bg-white/8 px-3 py-1.5 text-xs font-medium text-zinc-300 ring-1 ring-white/15 tabular-nums">
              {total.toLocaleString("tr-TR")} yorum analiz edildi
            </span>
          </div>

          {/* Aksiyon butonları — yönetici harekete geçer. Birincil
              CTA duruma göre: sorun varsa olumsuzlara, sağlıklıysa
              genel yorumlara götürür. */}
          <div className="mt-6 flex flex-wrap items-center justify-center gap-3 md:justify-start">
            <Link
              href={
                visual.band === "healthy"
                  ? "/reviews"
                  : "/reviews?sentiment_labels=NEGATİF"
              }
              className="inline-flex items-center gap-2 rounded-xl bg-white px-5 py-2.5 text-sm font-semibold text-zinc-900 transition-transform hover:scale-[1.03]"
            >
              {visual.band === "healthy"
                ? "Müşteri yorumlarını incele"
                : "Olumsuz yorumları incele"}
              <ArrowRight className="size-4" aria-hidden />
            </Link>
            <Link
              href="/strategy"
              className="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold text-white ring-1 ring-white/30 transition-colors hover:bg-white/10"
            >
              <Sparkles className="size-4" aria-hidden />
              Yapay zeka aksiyon planı
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

/** Son 30 gün vs önceki 30 gün memnuniyet değişimi. C-level'ın
 *  asıl sorusu "hareket ettik mi?" — yeşil yukarı / kırmızı aşağı
 *  ok + puan farkı. |delta| < 1 puan: "değişim yok". */
function TrendPill({ trend }: { trend: ExecutiveSentimentTrend }) {
  const delta = trend.delta_points;
  const flat = Math.abs(delta) < 1;
  const up = delta >= 1;
  const Icon = flat ? Minus : up ? TrendingUp : TrendingDown;
  const cls = flat
    ? "bg-white/8 text-zinc-200 ring-white/15"
    : up
      ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/35"
      : "bg-red-500/15 text-red-300 ring-red-500/35";
  const label = flat
    ? "Son 30 günde memnuniyet değişmedi"
    : `Son 30 günde memnuniyet ${up ? "+" : "−"}${Math.abs(delta).toLocaleString("tr-TR")} puan`;
  return (
    <span
      className={`mt-4 inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-sm font-semibold ring-1 tabular-nums ${cls}`}
    >
      <Icon className="size-4" aria-hidden />
      {label}
    </span>
  );
}

/** Panelin köşesinden yayılan duruma-göre-renkli ışıma. */
function HeroGlow({ color }: { color: string }) {
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0"
      style={{
        background: `radial-gradient(720px circle at 12% 0%, ${color}, transparent 55%), radial-gradient(560px circle at 100% 100%, rgba(99,102,241,0.18), transparent 60%)`,
      }}
    />
  );
}

/** SVG radyal gösterge — Memnuniyet Skoru. CSS transition ile
 *  stroke-dashoffset yumuşak açılır (mount sonrası tek geçiş). */
function RadialGauge({
  pct,
  stroke,
  glow,
}: {
  pct: number;
  stroke: string;
  glow: string;
}) {
  const R = 84;
  const C = 2 * Math.PI * R;
  const clamped = Math.max(0, Math.min(100, pct));
  const offset = C * (1 - clamped / 100);
  return (
    <div
      className="relative size-44 shrink-0 md:size-[216px]"
      role="img"
      aria-label={`Memnuniyet skoru yüzde ${clamped}`}
    >
      <svg viewBox="0 0 216 216" className="size-full -rotate-90">
        <circle
          cx="108" cy="108" r={R}
          fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="16"
        />
        <circle
          cx="108" cy="108" r={R}
          fill="none" stroke={stroke} strokeWidth="16" strokeLinecap="round"
          strokeDasharray={C} strokeDashoffset={offset}
          style={{
            transition: "stroke-dashoffset 900ms var(--motion-ease)",
            filter: `drop-shadow(0 0 14px ${glow})`,
          }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span
          className="text-4xl md:text-6xl font-semibold tabular-nums tracking-tight text-white"
          style={{ letterSpacing: "-0.03em" }}
        >
          %{clamped}
        </span>
        <span className="mt-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-zinc-300">
          Memnuniyet
        </span>
      </div>
    </div>
  );
}

function CountChip({
  dot,
  label,
  value,
}: {
  dot: string;
  label: string;
  value: number;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-white/8 px-3 py-1.5 text-xs font-medium text-zinc-200 ring-1 ring-white/15">
      <span className={`size-2 rounded-full ${dot}`} aria-hidden />
      {label}{" "}
      <strong className="text-white tabular-nums">
        {value.toLocaleString("tr-TR")}
      </strong>
    </span>
  );
}
