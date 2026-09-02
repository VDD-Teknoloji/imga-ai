"use client";

// Sprint 13.2 — "kök neden önce" kartları (yeniden sıralama, A2).
//
// Ana sayfanın eski hali sayıları önce, nedeni sonra gösteriyordu
// (grafikler → aksiyon). Ürün sahibi isteği: yönetici önce "neden?"
// ve "ne yapmalıyım?" sorularının cevabını görsün, sayılar altta
// dursun. Bu bileşen ExecutiveHero'nun hemen altında en yüksek
// negatif paya sahip ≤3 ana kategoriyi + (varsa) en son üretilmiş
// kök neden analizini gösterir — TopProblems'ın "sıra + kategori +
// kanıt + drilldown" idiomunu izler, PriorityAction'ın "önce hüküm,
// sonra detay" tonunu taşır. Sakin ışıklı kart; glow/pulse yok.

import { useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, ChevronDown, ChevronRight, Info, Sparkles, Target } from "lucide-react";
import { toast } from "sonner";

import { SectionHeading } from "@/components/dashboard/section-heading";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useCreateActionItem } from "@/hooks/use-action-items";
import { useMounted } from "@/hooks/use-count-up";
import { useRoleFlags } from "@/hooks/use-role-flags";
import { useGenerateRootCause } from "@/hooks/use-root-cause";
import {
  useRootCauseOverview,
  type RootCauseOverviewAnalysis,
  type RootCauseOverviewCard,
  type RootCauseOverviewCauseItem,
  type RootCauseOverviewFilters,
} from "@/hooks/use-root-cause-overview";
import { ApiError } from "@/lib/api-client";
import {
  CATEGORY_ICON_FALLBACK,
  CATEGORY_ICON_MAP,
  categoryIconFallbackIndex,
  categoryTone,
} from "@/lib/category-icons";
import { useTranslation } from "@/lib/i18n/use-translation";
import { localizePlaceholders, maskPii, searchableQuoteFragment } from "@/lib/pii-mask";
import { formatDateTr, relativeTimeTr } from "@/lib/relative-time";
import type { ActionItemPriority, SentimentByCategoryResponse } from "@/lib/types";

interface Props {
  /** Sayfanın aktif dönemi — RootCause overview çağrısı VE her kartın
   *  "Kanıtı gör" / üretim isteği bunu taşır. Yeni bir filtre eklenmiyor
   *  (mevcut window/date filtresinin aynısı). */
  filters: RootCauseOverviewFilters;
  /** Kod → etiket eşlemesi için: sayfa zaten useSentimentByCategory'yi
   *  çağırıyor (CategorySentimentBreakdown'daki aynı kaynak). Overview
   *  yalnız kod döner, ayrı bir taksonomi çağrısı açmak yerine bu
   *  paylaşılan veri kullanılır (top-N dışında kalan kod code'a düşer —
   *  category-sentiment-breakdown.tsx'teki `?? code` ile aynı savunma). */
  categories: SentimentByCategoryResponse | undefined;
}

export function RootCauseCards({ filters, categories }: Props) {
  const { t } = useTranslation();
  const overview = useRootCauseOverview(filters, 3);
  const { isSuperAdmin } = useRoleFlags();

  if (overview.isLoading) {
    return (
      <section aria-label={t("dashboard.rootCauseCards.aria")}>
        <Skeleton className="h-7 w-72" />
        <div className="mt-5 space-y-4">
          <Skeleton className="h-64 w-full rounded-3xl" />
          <Skeleton className="h-64 w-full rounded-3xl" />
          <Skeleton className="h-64 w-full rounded-3xl" />
        </div>
      </section>
    );
  }

  if (overview.isError) {
    return (
      <section aria-label={t("dashboard.rootCauseCards.aria")}>
        <SectionHeading title={t("dashboard.rootCauseCards.title")} icon={Target} />
        <p className="text-destructive mt-5 text-sm">{t("dashboard.common.loadFailed")}</p>
      </section>
    );
  }

  const cards = overview.data?.cards ?? [];
  const generating = overview.data?.generating ?? false;
  // F2 — last_error yalnız üretim sürmüyorken anlamlı: üretim sürerken
  // (generating true) şerit zaten "hazırlanıyor" diyor, hata kopyası onu
  // gölgelememeli (görev talimatı: "never while generating is true").
  const lastError = generating ? null : (overview.data?.last_error ?? null);

  return (
    <section aria-label={t("dashboard.rootCauseCards.aria")}>
      <SectionHeading title={t("dashboard.rootCauseCards.title")} icon={Target} />

      {/* generating: arka planda kuyruklanmış üretim sürüyor — kartlar
          varsa gizlenmez, üstlerinde sakin bir ilerleme şeridi belirir
          (PO isteği). Hook 5sn'de bir yoklayıp bu bayrak false olunca
          durur. */}
      {generating && <RootCauseGeneratingStrip />}

      {/* Son otomatik üretim hata verdiyse kartlar çoğunlukla "analysis
          null" hâlde gelir (cards.length > 0) — o durumda kartların kendi
          "kuyruğa alındı" satırı yanıltıcı olurdu. Tek sakin şerit nedeni
          söyler; gerçek analiz olan kart varsa şerit görünmez. */}
      {lastError !== null && cards.length > 0 && cards.every((c) => !c.analysis) && (
        <RootCauseErrorStrip kind={lastError} isSuperAdmin={isSuperAdmin} />
      )}

      {cards.length === 0 ? (
        <div className="rise-in shadow-soft bg-card ring-foreground/5 mt-5 rounded-3xl p-6 ring-1 md:p-7">
          <p className="text-sm font-semibold">{t("dashboard.rootCauseCards.empty.title")}</p>
          {/* F2 — hiç kart üretilmemişken son otomatik denemenin neden
              boş kaldığını anlatır. Gerçek içerik varsa (cards.length
              > 0) bu blok hiç render edilmez — görev talimatı. */}
          {lastError === "no_credentials" ? (
            <>
              <p className="text-muted-foreground mt-1.5 text-sm leading-relaxed">
                {t("rootCause.error.noCredentials")}
              </p>
              {/* Anahtar yönetimi 2026-08-09'dan beri yalnız süper yönetici
                  yüzeyinde (/admin/tenants/{id}/llm); kurum yöneticisine
                  tıklayınca hiçbir şey yapamayacağı bir link göstermeyiz. */}
              {isSuperAdmin && (
                <Link
                  href="/admin/tenants"
                  className="text-primary mt-2 inline-flex items-center gap-1 text-sm font-medium hover:underline"
                >
                  {t("rootCause.error.noCredentialsCta")}
                  <ArrowRight className="size-3.5" aria-hidden />
                </Link>
              )}
            </>
          ) : lastError === "failed" ? (
            <p className="text-muted-foreground mt-1.5 text-sm leading-relaxed">
              {t("rootCause.error.failed")}
            </p>
          ) : (
            <p className="text-muted-foreground mt-1.5 text-sm leading-relaxed">
              {t("dashboard.rootCauseCards.empty.desc")}
            </p>
          )}
        </div>
      ) : (
        <div className="mt-5 space-y-4">
          {cards.map((card, idx) => (
            <RootCauseCardTile
              key={card.primary_category_code}
              card={card}
              label={labelFor(card.primary_category_code, categories)}
              filters={filters}
              index={idx}
            />
          ))}
        </div>
      )}
    </section>
  );
}

/** Kayan-şerit indeterminate progress bar — BatchProgressStream.tsx'teki
 *  "ısınma" şeridiyle aynı `progress-slide` keyframe'i (globals.css),
 *  yeni bir kütüphane yok. */
function RootCauseGeneratingStrip() {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      className="rise-in shadow-soft bg-card ring-foreground/5 mt-5 rounded-3xl p-5 ring-1"
    >
      <p className="text-sm font-semibold">{t("dashboard.rootCauseCards.generating")}</p>
      <div className="relative mt-3 h-1.5 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
        <div className="from-primary/30 via-primary to-primary/30 absolute inset-y-0 w-1/3 animate-[progress-slide_1.2s_ease-in-out_infinite] rounded-full bg-gradient-to-r" />
      </div>
      <p className="text-muted-foreground mt-2 text-xs leading-relaxed">
        {t("dashboard.rootCauseCards.generatingHint")}
      </p>
    </div>
  );
}

function RootCauseErrorStrip({
  kind,
  isSuperAdmin,
}: {
  kind: "no_credentials" | "failed";
  isSuperAdmin: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      className="rise-in shadow-soft bg-card ring-foreground/5 mt-5 rounded-3xl p-5 ring-1"
    >
      <p className="text-muted-foreground text-sm leading-relaxed">
        {kind === "no_credentials"
          ? t("rootCause.error.noCredentials")
          : t("rootCause.error.failed")}
      </p>
      {kind === "no_credentials" && isSuperAdmin && (
        <Link
          href="/admin/tenants"
          className="text-primary mt-2 inline-flex items-center gap-1 text-sm font-medium hover:underline"
        >
          {t("rootCause.error.noCredentialsCta")}
          <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      )}
    </div>
  );
}

function labelFor(code: string, categories: SentimentByCategoryResponse | undefined): string {
  if (!categories) return code;
  const idx = categories.categories.indexOf(code);
  return idx >= 0 ? (categories.category_labels_tr[idx] ?? code) : code;
}

/** ExecutiveHero.handleSegmentClick ile aynı param adları — sayfanın
 *  aktif dönemi varsa taşınır. */
function evidenceHref(code: string, filters: RootCauseOverviewFilters): string {
  const params = new URLSearchParams();
  params.set("primary_categories", code);
  params.set("sentiment_labels", "NEGATIF");
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  return `/reviews?${params.toString()}`;
}

/** F2 — "Süreç verisine bak" linki: /insights sayfasının operations
 *  tab'ına, kartın KENDİ analiz penceresiyle (sayfanın o anki filtresi
 *  değil — analiz başka bir dönem için üretilmiş olabilir). page.tsx
 *  date_from/date_to'yu ham YYYY-MM-DD okur (searchParams.get), backend
 *  bu alanları `date` tipiyle aynı biçimde döner (routes/tenant_insights.py
 *  RootCauseAnalysisBlock) — dönüştürme gerekmez. */
function processHref(analysis: RootCauseOverviewAnalysis): string {
  const params = new URLSearchParams();
  params.set("tab", "operations");
  if (analysis.date_from) params.set("date_from", analysis.date_from);
  if (analysis.date_to) params.set("date_to", analysis.date_to);
  return `/insights?${params.toString()}`;
}

/** Alıntının ilk ~7 kelimesi — /reviews'in `search` filtresi ILIKE
 *  alt-dizi eşleşmesi yaptığından birebir alıntı öneki her zaman
 *  isabet eder. Kesme her zaman İLK "…"/"..."ten önce yapılır (sadece
 *  sondaki değil): sistem prompt'u modele alıntıyı kısaltma izni verir
 *  ("kısaltabilirsin"), bu da "başı … sonu" biçimli bir orta-metin
 *  kırpması üretebilir — kelimelere bölmeden önce elenmezse aranan
 *  dizgenin içine gerçek yorumda hiç geçmeyen "…" karakteri karışır ve
 *  ILIKE hiç eşleşmez. */
function quoteSearchHref(quote: string): string {
  // KVKK yer tutucuları ("[ad]" vb.) aramada eşleşmez; en uzun
  // yer-tutucusuz parça aranır (lib/pii-mask.ts).
  return `/reviews?search=${encodeURIComponent(searchableQuoteFragment(quote))}`;
}

/** KVKK — serbest metin alanları görüntülenirken maske emniyet ağı +
 *  yer tutucu yerelleştirme (eski analizlerde ham e-posta/telefon
 *  kalmış olabilir; sunucu maskesi 2026-09-02'den sonra üretilenleri
 *  zaten temizler). */
function presentText(text: string, locale: "tr" | "en"): string {
  return localizePlaceholders(maskPii(text), locale);
}

/** action_short varsa o (zaten tek satır); yoksa suggested_action'ın
 *  İLK cümlesi — prompt artık suggested_action'ı tek cümlelik, mütevazı
 *  bir öneri olarak üretiyor (root_cause_v1.py), ama eski kalıcı
 *  analizlerde çok cümlelik metin olabilir; ilk cümleyi almak satırı
 *  tek satırda (line-clamp) okunur tutar. */
function suggestionText(cause: RootCauseOverviewCauseItem): string | null {
  if (cause.action_short) return cause.action_short;
  if (!cause.suggested_action) return null;
  const firstSentence = cause.suggested_action.match(/^[^.!?]*[.!?]/)?.[0];
  return (firstSentence ?? cause.suggested_action).trim();
}

/** Bir nedenin kanıt alıntıları — hem ilk neden hem de "diğer nedenler"
 *  bölümündeki her satır aynı biçimi kullanır (PO isteği: diğer
 *  nedenler de kendi yorum alıntılarını taşısın). */
function EvidenceQuoteList({ quotes }: { quotes: string[] }) {
  const { t, locale } = useTranslation();
  if (quotes.length === 0) return null;
  return (
    <ul className="space-y-2">
      {quotes.slice(0, 2).map((rawQuote, i) => {
        const quote = presentText(rawQuote, locale);
        return (
          <li
            key={`${quote.slice(0, 24)}-${i}`}
            className="border-foreground/15 border-l-2 pl-3 text-xs"
          >
            <p className="text-muted-foreground italic">&ldquo;{quote}&rdquo;</p>
            <Link
              href={quoteSearchHref(quote)}
              className="text-primary mt-1 inline-flex items-center gap-1 font-medium not-italic hover:underline"
            >
              {t("dashboard.rootCauseCards.searchQuote")}
              <ArrowRight className="size-3" aria-hidden />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** F2 — bir nedenin detayında kanıt alıntılarından sonra gelen iki ek
 *  parça: (varsa) uzman notu + "Aksiyona çevir" mikro-akışı. İlk neden
 *  VE her "diğer neden" aynı bileşeni paylaşır (PO isteği: ikisi de
 *  aynı iskelet). "Oluşturuldu" durumu ve mutasyon çağrısı çağıran
 *  bileşenden (RootCauseCardTile) prop olarak gelir — showDetails
 *  kapanıp açıldığında OtherCauseBlock yeniden mount olsa bile durum
 *  kaybolmasın diye (aksi halde aynı oturumda iki kez oluşturulabilirdi). */
function CauseExtras({
  cause,
  canWrite,
  isConverted,
  isPending,
  onConvert,
}: {
  cause: RootCauseOverviewCauseItem;
  canWrite: boolean;
  isConverted: boolean;
  isPending: boolean;
  onConvert: () => void;
}) {
  const { t, locale } = useTranslation();
  return (
    <>
      {cause.expert_note && (
        <div className="space-y-1">
          <p className="text-muted-foreground text-[11px] font-semibold tracking-wide uppercase">
            {t("rootCause.expertNote.label")}
          </p>
          <p className="text-muted-foreground text-xs leading-relaxed">
            {presentText(cause.expert_note, locale)}
          </p>
        </div>
      )}
      {canWrite &&
        (isConverted ? (
          <Link
            href="/action-items"
            className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1 text-xs font-medium transition-colors"
          >
            {t("rootCause.convert.done")}
            <ArrowRight className="size-3" aria-hidden />
          </Link>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onConvert}
            disabled={isPending}
            className="self-start"
          >
            {t("rootCause.convert.button")}
          </Button>
        ))}
    </>
  );
}

/** "Diğer nedenler" bölümündeki her satır — ilk nedenle aynı iskelet:
 *  kendi Çıkarım etiketi + başlık, kendi açıklaması, kendi alıntıları,
 *  kendi mütevazı öneri satırı (PO isteği: diğer nedenler için de
 *  çıkarım ve yorumlar olsun). */
function OtherCauseBlock({
  cause,
  canWrite,
  isConverted,
  isPending,
  onConvert,
}: {
  cause: RootCauseOverviewCauseItem;
  canWrite: boolean;
  isConverted: boolean;
  isPending: boolean;
  onConvert: () => void;
}) {
  const { t, locale } = useTranslation();
  const suggestion = suggestionText(cause);
  return (
    <div className="space-y-2">
      <p className="text-primary text-[11px] font-semibold tracking-wide uppercase">
        {t("dashboard.rootCauseCards.inference")}
      </p>
      <p className="text-sm font-semibold text-balance">{cause.headline ?? cause.title}</p>
      <p className="text-muted-foreground line-clamp-3 text-sm leading-relaxed">
        {presentText(cause.description, locale)}
      </p>
      <EvidenceQuoteList quotes={cause.evidence_quotes} />
      <CauseExtras
        cause={cause}
        canWrite={canWrite}
        isConverted={isConverted}
        isPending={isPending}
        onConvert={onConvert}
      />
      {suggestion && (
        <p className="text-muted-foreground line-clamp-2 text-sm leading-relaxed">
          {t("dashboard.rootCauseCards.suggestion")}: {suggestion}
        </p>
      )}
    </div>
  );
}

/** Kart başlığındaki yumuşak tonlu ikon dairesi — kategori kodunu tek
 *  bakışta ayırt edilir kılar (görev A: root-cause-cards + category-
 *  sentiment-breakdown ortak kayıt defterini paylaşır, lib/category-icons.ts). */
function CategoryIconBadge({ code }: { code: string }) {
  // Satır içi tablo indekslemesi (fonksiyon çağrısının SONUCU değil) —
  // React Compiler'ın react-hooks/static-components kuralı bir JSX
  // etiketinin render sırasında ÇAĞRILAN bir fonksiyondan gelmesini
  // hata sayar; categoryIconFallbackIndex() bir SAYI döndüğü için
  // (JSX etiketi değil) güvenli, `MAP[code] ?? FALLBACK[idx]` düz bir
  // dizi/obje indekslemesi (bkz. lib/category-icons.ts dosya üstü not).
  const Icon = CATEGORY_ICON_MAP[code] ?? CATEGORY_ICON_FALLBACK[categoryIconFallbackIndex(code)]!;
  const tone = categoryTone(code);
  return (
    <span
      className={`inline-flex size-8 shrink-0 items-center justify-center rounded-full ${tone.bg} ${tone.fg}`}
      aria-hidden
    >
      <Icon className="size-4" />
    </span>
  );
}

/** ExecutiveHero.ScoreInfoTip ile aynı desen — küçük "i" tetikleyicisi +
 *  hover/focus balonu. Burada paydayı (window_negative_total) açıklar. */
function ShareInfoTip({ text }: { text: string }) {
  const { t } = useTranslation();
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger
          aria-label={t("dashboard.rootCauseCards.shareInfoAria")}
          className="text-muted-foreground/70 hover:text-foreground inline-flex cursor-help items-center transition-colors"
        >
          <Info className="size-3.5" aria-hidden />
        </TooltipTrigger>
        <TooltipContent className="max-w-72 leading-relaxed">{text}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/** Kartın sağ üst payı rozeti. Kök neden scout'unun kontratı: backend
 *  window_negative_total/window_from/window_to gönderiyorsa gerçek
 *  paydayı ("2.189 / 3.267 olumsuz") + payda + istisnaları açıklayan
 *  bir tooltip gösterir; alanlar henüz gelmiyorsa (eski sunucu, paralel
 *  deploy) eski opak kopyaya sessizce düşer — yarım bir kart göstermek
 *  yerine (görev talimatı: "fall back to the old copy"). n<5 kuralı
 *  (yüzde tek başına yanıltıcı) her iki dalda da aynen korunur. */
function SharePill({
  card,
  filters,
}: {
  card: RootCauseOverviewCard;
  filters: RootCauseOverviewFilters;
}) {
  const { t, locale } = useTranslation();
  const numberLocale = locale === "en" ? "en-US" : "tr-TR";
  const pillClass =
    "rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-medium text-red-700 tabular-nums dark:bg-red-950/40 dark:text-red-300";

  if (card.negative_count < 5) {
    return (
      <span className={pillClass}>
        {t("dashboard.rootCauseCards.shareChipCountOnly", {
          count: card.negative_count.toLocaleString(numberLocale),
        })}
      </span>
    );
  }

  const pct = Math.round(card.share_pct);
  const count = card.negative_count.toLocaleString(numberLocale);
  const hasWindow =
    card.window_negative_total !== undefined &&
    Boolean(card.window_from) &&
    Boolean(card.window_to);

  if (!hasWindow) {
    return (
      <span className={pillClass}>{t("dashboard.rootCauseCards.shareChip", { pct, count })}</span>
    );
  }

  const total = card.window_negative_total!.toLocaleString(numberLocale);
  const windowDays = Math.round(
    (new Date(card.window_to!).getTime() - new Date(card.window_from!).getTime()) / 86_400_000,
  );
  // filters.date_from doluysa sayfa özel bir aralık/preset üzerinde —
  // pencere tamamen backend'in sessiz 90-günlük varsayılanından
  // GELMİYOR, bu yüzden "son N günde" değil açık tarih aralığı denir.
  const tooltipText = filters.date_from
    ? t("dashboard.rootCauseCards.shareTooltipRange", {
        from: formatDateTr(card.window_from!),
        to: formatDateTr(card.window_to!),
        total,
        count,
        pct,
      })
    : t("dashboard.rootCauseCards.shareTooltipDefault", { days: windowDays, total, count, pct });

  return (
    <span className="inline-flex items-center gap-1">
      <span className={pillClass}>
        {t("dashboard.rootCauseCards.shareChipWithTotal", { count, total, pct })}
      </span>
      <ShareInfoTip text={tooltipText} />
    </span>
  );
}

/** İnce yatay pay çubuğu — açılışta soldan dolar (SatisfactionSegment
 *  ile aynı mount-tetikli CSS transition deseni, reduced-motion
 *  globals.css guard'ı zaten kapsıyor). Payda yeni alanlar taşımıyorsa
 *  (eski sunucu) backend'in zaten hesapladığı share_pct'e düşülür — bar
 *  hiçbir sürümde eksik kalmaz. */
function ShareBar({ card }: { card: RootCauseOverviewCard }) {
  const mounted = useMounted();
  const pct = Math.max(
    0,
    Math.min(
      100,
      card.window_negative_total
        ? (card.negative_count / card.window_negative_total) * 100
        : card.share_pct,
    ),
  );
  return (
    <div className="bg-muted mt-3 h-1.5 w-full overflow-hidden rounded-full" aria-hidden>
      <div
        className="bg-sentiment-negative h-full rounded-full transition-[width] duration-700 [transition-timing-function:var(--motion-ease)]"
        style={{ width: mounted ? `${pct}%` : "0%" }}
      />
    </div>
  );
}

function RootCauseCardTile({
  card,
  label,
  filters,
  index,
}: {
  card: RootCauseOverviewCard;
  label: string;
  filters: RootCauseOverviewFilters;
  index: number;
}) {
  const { t, locale } = useTranslation();
  const { canWrite } = useRoleFlags();
  const qc = useQueryClient();
  // Detay akordeonu URL'de DEĞİL — url-state-patterns.md geçici (kalıcı
  // olmayan) UI durumunu açıkça muaf tutuyor; filtre/sıralama değil
  // (category-sentiment-breakdown.tsx'teki `expanded` state'iyle aynı
  // gerekçe). PO geri bildirimi: kart varsayılan KAPALI açılır — başlık +
  // tek satır aksiyon dışındaki her şey bu state'in arkasında.
  const [showDetails, setShowDetails] = useState(false);
  const generate = useGenerateRootCause();
  // F2 — "Aksiyona çevir" durumu burada, showDetails'in İÇİNDE değil:
  // showDetails kapanıp tekrar açıldığında OtherCauseBlock/CauseExtras
  // yeniden mount olur, state orada yaşasaydı "bir oturumda en fazla
  // bir kez" garantisi bozulurdu. Anahtar bare index DEĞİL — bu tile
  // primary_category_code'a göre kalıcı (root-cause-overview refetch'i
  // üzerinden hayatta kalır); arka planda yeni bir analysis gelirse
  // (generating polling / staleTime) aynı index farklı bir nedene
  // işaret eder. `${analysis.generated_at}:${i}` bu analizin kendi
  // kimliğini taşır, yeni analiz gelince durum otomatik sıfırlanır.
  // Mutasyon da burada tek örnek — pending durumu kartın tüm "Aksiyona
  // çevir" butonlarını (aynı anda tek tıklama beklenir) birlikte kilitler.
  const createAction = useCreateActionItem();
  const [converted, setConverted] = useState<Record<string, boolean>>({});

  function convertCause(
    causeKey: string,
    cause: RootCauseOverviewCauseItem,
    priority: ActionItemPriority,
  ) {
    const quotes = cause.evidence_quotes
      .slice(0, 2)
      .map((q) => `- ${q}`)
      .join("\n");
    const rationale = quotes ? `${cause.description}\n${quotes}` : cause.description;
    createAction.mutate(
      {
        // Backend title <= 256 karakter kabul ediyor (görev kontratı) —
        // headline/title zaten kısa üretilir ama savunmacı kesme.
        title: (cause.headline ?? cause.title).slice(0, 256),
        // suggestionText()'in kendi sırasından FARKLI: burada ham
        // suggested_action önce (görev kontratı) — "" boş string de
        // düşülsün diye `||` (ActionItem description boş kalmasın).
        description: cause.suggested_action || cause.action_short || cause.description,
        rationale,
        priority,
      },
      {
        onSuccess: () => setConverted((prev) => ({ ...prev, [causeKey]: true })),
        onError: () => toast.error(t("rootCause.convert.error")),
      },
    );
  }

  const analysis = card.analysis;
  const [firstCause, ...restCauses] = analysis?.causes ?? [];
  // can_generate true iken bile perspective_code null gelebilir
  // (kontrat: "otomatik alt kategori seçilmedi") — bu durumda üretim
  // hedefsiz kalır, buton savunmacı biçimde gizlenir.
  const canOfferGenerate = card.can_generate && card.perspective_code !== null;

  function onGenerate() {
    if (card.perspective_code === null) return;
    generate.mutate(
      {
        primary_category: card.primary_category_code,
        perspective_code: card.perspective_code,
        date_from: filters.date_from,
        date_to: filters.date_to,
      },
      {
        onSuccess: () => {
          qc.invalidateQueries({ queryKey: ["root-cause-overview"] });
        },
        // root-cause-dialog.tsx ile aynı hata haritası (412/400-422/503).
        onError: (err) => {
          if (err instanceof ApiError) {
            if (err.status === 412) {
              toast.error(t("dashboard.rootCause.noCredentials"));
              return;
            }
            if (err.status === 400 || err.status === 422) {
              toast.error(err.detail);
              return;
            }
            if (err.status === 503) {
              toast.error(t("dashboard.rootCause.providerUnavailable"));
              return;
            }
          }
          toast.error(t("dashboard.rootCause.generateFailed"));
        },
      },
    );
  }

  // İki kullanım yeri var: nedenli kartta detay-satırı içinde (kendi
  // üst boşluğu yok, satır zaten mt-4 taşıyor), diğer dallarda tek
  // başına (kendi mt-4'ünü sarmalayıcıdan alır) — bkz. aşağıdaki iki
  // render noktası.
  const evidenceLink = (
    <Link
      href={evidenceHref(card.primary_category_code, filters)}
      className="text-foreground/70 hover:text-foreground inline-flex items-center gap-1.5 text-sm font-semibold transition-colors"
    >
      {t("dashboard.rootCauseCards.evidenceLink", {
        n: card.negative_count.toLocaleString("tr-TR"),
      })}
      <ArrowRight className="size-4" aria-hidden />
    </Link>
  );

  return (
    <div
      className="rise-in shadow-soft bg-card ring-foreground/5 flex flex-col rounded-3xl p-5 ring-1 md:p-6"
      style={{ animationDelay: `${index * 70}ms` }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <CategoryIconBadge code={card.primary_category_code} />
          <p className="truncate text-sm font-semibold">{label}</p>
        </div>
        <SharePill card={card} filters={filters} />
      </div>
      <ShareBar card={card} />

      {analysis && firstCause ? (
        <>
          {/* PO geri bildirimi: kapalı kart tek çıkarım başlığı + tek
              mütevazı öneri satırıyla dikkat çeker (renkli kutu yok —
              "Yapılacak iş" emri kalktı), gerisi "Detayları gör"
              arkasında. "Çıkarım" etiketi bunun ham bir alıntı değil,
              veriden çıkarılmış bir bulgu olduğunu açık eder. */}
          <p className="text-primary mt-3 text-[11px] font-semibold tracking-wide uppercase">
            {t("dashboard.rootCauseCards.inference")}
          </p>
          <p className="mt-0.5 line-clamp-2 text-lg font-semibold tracking-tight text-balance">
            {firstCause.headline ?? firstCause.title}
          </p>
          {suggestionText(firstCause) && (
            <p className="text-muted-foreground mt-3 line-clamp-2 text-sm leading-relaxed">
              {t("dashboard.rootCauseCards.suggestion")}: {suggestionText(firstCause)}
            </p>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
            <button
              type="button"
              onClick={() => setShowDetails((v) => !v)}
              aria-expanded={showDetails}
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs font-medium transition-colors"
            >
              {showDetails ? (
                <ChevronDown className="size-3.5" aria-hidden />
              ) : (
                <ChevronRight className="size-3.5" aria-hidden />
              )}
              {showDetails
                ? t("dashboard.rootCauseCards.hideDetails")
                : t("dashboard.rootCauseCards.showDetails")}
            </button>
            {evidenceLink}
          </div>

          {showDetails && (
            <div className="border-foreground/10 mt-4 space-y-4 border-t pt-4">
              <p className="text-muted-foreground text-sm leading-relaxed">
                {presentText(firstCause.description, locale)}
              </p>
              <EvidenceQuoteList quotes={firstCause.evidence_quotes} />
              <CauseExtras
                cause={firstCause}
                canWrite={canWrite}
                isConverted={Boolean(converted[`${analysis.generated_at}:0`])}
                isPending={createAction.isPending}
                onConvert={() => convertCause(`${analysis.generated_at}:0`, firstCause, "high")}
              />
              {firstCause.affected_surface && (
                <p className="text-muted-foreground text-xs">
                  {t("dashboard.rootCause.affectedSurface")}: {firstCause.affected_surface}
                </p>
              )}
              <p
                className="text-muted-foreground text-xs"
                title={formatDateTr(analysis.generated_at)}
              >
                {t("dashboard.rootCauseCards.lastAnalysis", {
                  time: relativeTimeTr(analysis.generated_at),
                })}
              </p>
              {/* F2 — kartın kendi üretim penceresine bağlı operasyon
                  verisi; sayfanın aktif filtresi değil (bkz. processHref). */}
              <Link
                href={processHref(analysis)}
                className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1 text-xs font-medium transition-colors"
              >
                {t("rootCause.processLink")}
                <ArrowRight className="size-3" aria-hidden />
              </Link>
              {/* PO isteği: diğer nedenler artık başlık listesi değil —
                  her biri ilk nedenle aynı iskelette (çıkarım + açıklama
                  + alıntı + öneri) tam anlatılır. */}
              {restCauses.length > 0 && (
                <div className="border-foreground/10 space-y-4 border-t pt-4">
                  <p className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
                    {t("dashboard.rootCauseCards.otherCausesTitle")}
                  </p>
                  <div className="space-y-4">
                    {restCauses.map((cause, i) => {
                      const causeKey = `${analysis.generated_at}:${i + 1}`;
                      return (
                        <OtherCauseBlock
                          key={`${cause.title}-${i}`}
                          cause={cause}
                          canWrite={canWrite}
                          isConverted={Boolean(converted[causeKey])}
                          isPending={createAction.isPending}
                          onConvert={() => convertCause(causeKey, cause, "medium")}
                        />
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      ) : analysis ? (
        // Kontrat açısından mümkün ama beklenmedik uç durum: analiz var,
        // causes boş. Özet en azından bir cümle taşır.
        <>
          <p className="text-muted-foreground mt-3 text-sm leading-relaxed">{analysis.summary}</p>
          <p
            className="text-muted-foreground mt-3 text-xs"
            title={formatDateTr(analysis.generated_at)}
          >
            {t("dashboard.rootCauseCards.lastAnalysis", {
              time: relativeTimeTr(analysis.generated_at),
            })}
          </p>
        </>
      ) : card.can_generate ? (
        canWrite ? (
          // Hiç üretilmemiş + yazma yetkisi var: kuyruk vaadi + (hedef
          // varsa) manuel üretim butonu.
          <>
            <p className="text-muted-foreground mt-3 text-sm leading-relaxed">
              {t("dashboard.rootCauseCards.queued")}
            </p>
            {canOfferGenerate && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={onGenerate}
                disabled={generate.isPending}
                className="mt-3 gap-1.5 self-start"
              >
                <Sparkles className="size-3.5" aria-hidden />
                {t("dashboard.rootCauseCards.generateNow")}
              </Button>
            )}
          </>
        ) : (
          // Hiç üretilmemiş + salt-okuma üye: üretim butonu gösterilmez,
          // yalnız kimin oluşturabileceği anlatılır.
          <p className="text-muted-foreground mt-3 text-sm leading-relaxed">
            {t("dashboard.rootCauseCards.emptyViewer")}
          </p>
        )
      ) : (
        <p className="text-muted-foreground mt-3 text-sm leading-relaxed">
          {t("dashboard.rootCauseCards.notEnoughData")}
        </p>
      )}

      {/* Nedenli daldaki footer satırı kendi evidenceLink'ini zaten
          gösterdi — burada yalnız diğer dallar için basılır. */}
      {!(analysis && firstCause) && <div className="mt-4">{evidenceLink}</div>}
    </div>
  );
}
