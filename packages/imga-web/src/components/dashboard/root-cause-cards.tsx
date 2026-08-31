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
import { ArrowRight, ChevronDown, ChevronRight, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { SectionHeading } from "@/components/dashboard/section-heading";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useRoleFlags } from "@/hooks/use-role-flags";
import { useGenerateRootCause } from "@/hooks/use-root-cause";
import {
  useRootCauseOverview,
  type RootCauseOverviewCard,
  type RootCauseOverviewFilters,
} from "@/hooks/use-root-cause-overview";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";
import { formatDateTr, relativeTimeTr } from "@/lib/relative-time";
import type { SentimentByCategoryResponse } from "@/lib/types";

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

  if (overview.isLoading) {
    return (
      <section aria-label={t("dashboard.rootCauseCards.aria")}>
        <Skeleton className="h-7 w-72" />
        <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-3">
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
        <SectionHeading
          title={t("dashboard.rootCauseCards.title")}
          description={t("dashboard.rootCauseCards.description")}
        />
        <p className="text-destructive mt-5 text-sm">{t("dashboard.common.loadFailed")}</p>
      </section>
    );
  }

  const cards = overview.data?.cards ?? [];

  return (
    <section aria-label={t("dashboard.rootCauseCards.aria")}>
      <SectionHeading
        title={t("dashboard.rootCauseCards.title")}
        description={t("dashboard.rootCauseCards.description")}
      />

      {cards.length === 0 ? (
        <div className="rise-in shadow-soft bg-card ring-foreground/5 mt-5 rounded-3xl p-6 ring-1 md:p-7">
          <p className="text-sm font-semibold">{t("dashboard.rootCauseCards.empty.title")}</p>
          <p className="text-muted-foreground mt-1.5 text-sm leading-relaxed">
            {t("dashboard.rootCauseCards.empty.desc")}
          </p>
        </div>
      ) : (
        <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-3">
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

function labelFor(
  code: string,
  categories: SentimentByCategoryResponse | undefined,
): string {
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

/** Alıntının ilk ~7 kelimesi — /reviews'in `search` filtresi ILIKE
 *  alt-dizi eşleşmesi yaptığından birebir alıntı öneki her zaman
 *  isabet eder. Kesme her zaman İLK "…"/"..."ten önce yapılır (sadece
 *  sondaki değil): sistem prompt'u modele alıntıyı kısaltma izni verir
 *  ("kısaltabilirsin"), bu da "başı … sonu" biçimli bir orta-metin
 *  kırpması üretebilir — kelimelere bölmeden önce elenmezse aranan
 *  dizgenin içine gerçek yorumda hiç geçmeyen "…" karakteri karışır ve
 *  ILIKE hiç eşleşmez. */
function quoteSearchHref(quote: string): string {
  const truncated = quote.split(/\.{3}|…/)[0] ?? quote;
  const words = truncated.trim().split(/\s+/).filter(Boolean).slice(0, 7).join(" ");
  return `/reviews?search=${encodeURIComponent(words)}`;
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
  const { t } = useTranslation();
  const { canWrite } = useRoleFlags();
  const qc = useQueryClient();
  // Akordeon durumu URL'de DEĞİL — url-state-patterns.md geçici (kalıcı
  // olmayan) UI durumunu açıkça muaf tutuyor; filtre/sıralama değil
  // (category-sentiment-breakdown.tsx'teki `expanded` state'iyle aynı
  // gerekçe).
  const [showOthers, setShowOthers] = useState(false);
  const generate = useGenerateRootCause();

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

  return (
    <div
      className="rise-in shadow-soft bg-card ring-foreground/5 flex flex-col rounded-3xl p-5 ring-1 md:p-6"
      style={{ animationDelay: `${index * 70}ms` }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold">{label}</p>
        <span className="rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-medium text-red-700 tabular-nums dark:bg-red-950/40 dark:text-red-300">
          {/* n < 5: yüzde tek başına yanıltıcı (5 yorumun %60'ı gibi) —
              o eşiğin altında yalnız ham sayı gösterilir. */}
          {card.negative_count < 5
            ? t("dashboard.rootCauseCards.shareChipCountOnly", {
                count: card.negative_count.toLocaleString("tr-TR"),
              })
            : t("dashboard.rootCauseCards.shareChip", {
                pct: Math.round(card.share_pct),
                count: card.negative_count.toLocaleString("tr-TR"),
              })}
        </span>
      </div>

      {analysis && firstCause ? (
        <>
          <p className="mt-3 text-base font-semibold leading-snug tracking-tight">
            {firstCause.title}
          </p>
          {firstCause.suggested_action && (
            <div className="bg-primary/5 mt-3 rounded-2xl p-3">
              <p className="text-primary text-xs font-semibold">
                {t("dashboard.rootCauseCards.actionLabel")}
              </p>
              <p className="text-foreground/90 mt-0.5 text-sm leading-relaxed">
                {firstCause.suggested_action}
              </p>
            </div>
          )}
          {firstCause.evidence_quotes.length > 0 && (
            <ul className="mt-3 space-y-2">
              {firstCause.evidence_quotes.slice(0, 2).map((quote, i) => (
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
              ))}
            </ul>
          )}
          {firstCause.affected_surface && (
            <p className="text-muted-foreground mt-3 text-xs">
              {t("dashboard.rootCause.affectedSurface")}: {firstCause.affected_surface}
            </p>
          )}
          <p
            className="text-muted-foreground mt-3 text-xs"
            title={formatDateTr(analysis.generated_at)}
          >
            {t("dashboard.rootCauseCards.lastAnalysis", {
              time: relativeTimeTr(analysis.generated_at),
            })}
          </p>

          {restCauses.length > 0 && (
            <div className="mt-2">
              <button
                type="button"
                onClick={() => setShowOthers((v) => !v)}
                aria-expanded={showOthers}
                className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs font-medium transition-colors"
              >
                {showOthers ? (
                  <ChevronDown className="size-3.5" aria-hidden />
                ) : (
                  <ChevronRight className="size-3.5" aria-hidden />
                )}
                {t("dashboard.rootCauseCards.otherCauses", { n: restCauses.length })}
              </button>
              {showOthers && (
                <ul className="mt-2 space-y-2">
                  {restCauses.map((cause, i) => (
                    <li key={`${cause.title}-${i}`} className="bg-muted/40 rounded-2xl p-3">
                      <p className="text-sm font-medium">{cause.title}</p>
                      <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
                        {cause.description}
                      </p>
                      {cause.suggested_action && (
                        <p className="mt-1.5 text-xs">
                          <span className="text-muted-foreground">
                            {t("dashboard.rootCauseCards.actionLabel")}:{" "}
                          </span>
                          {cause.suggested_action}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
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

      <Link
        href={evidenceHref(card.primary_category_code, filters)}
        className="text-foreground/70 hover:text-foreground mt-4 inline-flex items-center gap-1.5 text-sm font-semibold transition-colors"
      >
        {t("dashboard.rootCauseCards.evidenceLink", {
          n: card.negative_count.toLocaleString("tr-TR"),
        })}
        <ArrowRight className="size-4" aria-hidden />
      </Link>
    </div>
  );
}
