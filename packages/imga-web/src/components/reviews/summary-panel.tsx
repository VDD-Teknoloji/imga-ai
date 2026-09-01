"use client";

// W3 — /reviews sağ panel: aktif filtrelere tepki veren özet.
//
// ``filters`` PROP olarak ReviewsPageInner'ın mirror state'inden akar;
// bu bileşen useSearchParams ÇAĞIRMAZ ve ikinci bir Suspense sınırı
// AÇMAZ — docs/agent-rules/url-state-patterns.md kuralı, sayfa başına
// tek useSearchParams çağrısı. useReviewSummary de listenin AYNI
// buildReviewFilterParams'ını kullanır (bkz. hooks/use-reviews.ts) —
// panel sayıları listeyle her zaman birebir örtüşür.
//
// Tek sorgu (useReviewSummary) tüm blokları besler; repo'nun 3-durum
// konvansiyonu (loading/error/empty) bu yüzden PANEL seviyesinde bir
// kez uygulanır — bloklar kendi içinde yalnız "bu blok boşsa gizlen"
// kararını verir. Duygu renkleri (bg-/text-sentiment-*) merkezi
// token'lardan gelir (bkz. app/globals.css sentiment token bloğu).

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useCategories } from "@/hooks/use-categories";
import {
  useReviewSummary,
  type ReviewSummaryCategoryCount,
  type ReviewSummaryDaily,
  type ReviewSummaryEnteredBy,
  type ReviewSummaryNps,
  type ReviewSummaryQuality,
  type ReviewSummaryResponse,
  type ReviewSummaryTopQuestion,
  type ReviewSummaryValueCount,
} from "@/hooks/use-review-summary";
import type { ReviewListFiltersExt } from "@/hooks/use-reviews";
import { useTranslation } from "@/lib/i18n/use-translation";
import { sentimentScoreBucket, type SentimentScoreBucket } from "@/lib/sentiment-score";
import { CONTENT_TYPES, type CategoryView, type ContentType } from "@/lib/types";

const CARD_CLASS = "bg-card ring-foreground/5 rounded-2xl p-4 ring-1";

const SENTIMENT_ORDER = ["NEGATIF", "NÖTR", "POZITIF"] as const;

const SENTIMENT_LABEL_KEYS: Record<string, string> = {
  NEGATIF: "reviews.sentiment.negatif",
  POZITIF: "reviews.sentiment.pozitif",
  "NÖTR": "reviews.sentiment.notr",
};

const SENTIMENT_BAR_CLASS: Record<string, string> = {
  NEGATIF: "bg-sentiment-negative",
  "NÖTR": "bg-sentiment-neutral",
  POZITIF: "bg-sentiment-positive",
};

const QUALITY_FLAG_LABEL_KEYS: Record<string, string> = {
  duplicate: "reviews.qualityFilter.duplicate",
  empty: "reviews.qualityFilter.empty",
  informational: "reviews.qualityFilter.informational",
  meaningless: "reviews.qualityFilter.meaningless",
};

// Content-type chip labels — same i18n keys + escalation warning
// treatment as the list badge in reviews/page.tsx (ReviewRow).
const CONTENT_TYPE_LABEL_KEYS: Record<ContentType, string> = {
  escalation: "reviews.contentType.escalation",
  request: "reviews.contentType.request",
  question: "reviews.contentType.question",
  suggestion: "reviews.contentType.suggestion",
  thanks: "reviews.contentType.thanks",
};
const CONTENT_TYPE_CHIP_CLASS: Record<ContentType, string> = {
  escalation: "bg-sentiment-negative/10 text-sentiment-negative font-semibold",
  request: "bg-muted text-muted-foreground",
  question: "bg-muted text-muted-foreground",
  suggestion: "bg-muted text-muted-foreground",
  thanks: "bg-muted text-muted-foreground",
};

// Hüküm (verdict) rengi yalnız negatif/pozitif kovalarda; nötr ve
// skor-yok durumu varsayılan (renksiz) metin rengiyle kalır.
const VERDICT_COLOR_CLASS: Partial<Record<SentimentScoreBucket, string>> = {
  veryNegative: "text-sentiment-negative",
  negative: "text-sentiment-negative",
  positive: "text-sentiment-positive",
  veryPositive: "text-sentiment-positive",
};

const LOW_HEADLINE_TOTAL = 5;
const LOW_NPS_RESPONSES = 10;
const ENTERED_BY_WARN_MIN_TOTAL = 20;
const ENTERED_BY_WARN_MIN_RATE = 0.05;
const DAILY_TREND_MAX_DAYS = 90;

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** Backend yalnız veri olan günleri döner (Query H); aradaki sessiz
 *  günler burada count:0/negative:0 ile doldurulur ki seyrek bir aralık
 *  yanıltıcı biçimde yoğun görünmesin. UTC ile ilerlenir (tarihler zaten
 *  "YYYY-MM-DD", saat dilimi belirsizliği yok). */
function fillDailyGaps(daily: ReviewSummaryDaily[]): ReviewSummaryDaily[] {
  if (daily.length === 0) return daily;
  const byDate = new Map(daily.map((d) => [d.date, d]));
  const cursor = new Date(`${daily[0]!.date}T00:00:00Z`);
  const end = new Date(`${daily[daily.length - 1]!.date}T00:00:00Z`);
  const filled: ReviewSummaryDaily[] = [];
  while (cursor.getTime() <= end.getTime()) {
    const iso = cursor.toISOString().slice(0, 10);
    filled.push(byDate.get(iso) ?? { date: iso, count: 0, negative: 0 });
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return filled.slice(-DAILY_TREND_MAX_DAYS);
}

export function SummaryPanel({ filters }: { filters: ReviewListFiltersExt }) {
  const { t } = useTranslation();
  const summary = useReviewSummary(filters);
  const categories = useCategories();

  return (
    <aside className="space-y-3" aria-label={t("reviews.summary.panelTitle")}>
      <h2 className="text-muted-foreground px-1 text-xs font-semibold tracking-wide uppercase">
        {t("reviews.summary.panelTitle")}
      </h2>
      {summary.isLoading ? (
        <SummarySkeleton />
      ) : summary.isError ? (
        <div className={CARD_CLASS}>
          <p className="text-destructive text-sm">{t("reviews.summary.loadError")}</p>
        </div>
      ) : !summary.data || summary.data.total === 0 ? (
        <div className={`${CARD_CLASS} text-center`}>
          <p className="text-muted-foreground text-sm">{t("reviews.summary.emptyTitle")}</p>
        </div>
      ) : (
        <SummaryBlocks data={summary.data} categoryLabels={categories.data} />
      )}
    </aside>
  );
}

function SummarySkeleton() {
  const { t } = useTranslation();
  return (
    <div className="space-y-3">
      <span className="sr-only">{t("reviews.summary.loading")}</span>
      {[96, 56, 64, 130, 44, 110, 84, 96, 150, 90].map((h, i) => (
        <Skeleton key={i} className="w-full" style={{ height: h }} />
      ))}
    </div>
  );
}

function SummaryBlocks({
  data,
  categoryLabels,
}: {
  data: ReviewSummaryResponse;
  categoryLabels?: CategoryView[];
}) {
  return (
    <div className="space-y-3">
      <HeadlineBlock data={data} />
      <SentimentBarBlock sentiment={data.sentiment} total={data.total} />
      <ContentTypesBlock contentTypes={data.content_types} />
      <EnteredByBlock rows={data.entered_by} />
      <QualityLineBlock quality={data.quality} />
      <TopQuestionsBlock topQuestions={data.top_questions} questionCount={data.question_count} />
      <NpsBlock nps={data.nps} />
      <DailyTrendBlock daily={data.daily} />
      <CategoriesBlock categories={data.categories} categoryLabels={categoryLabels} />
      <SourcesBlock sources={data.sources} />
    </div>
  );
}

/** (a) — toplam kayıt + ortalama skor hükmü (sentimentScoreBucket) +
 *  ticket bağlantı sayısı. Hüküm ÖNCE, sayı SONRA: verdict birincil
 *  eleman (renkli, büyük), ham skor ikincil soluk satır. total<5 iken
 *  hüküm renksiz+italik'e döner ve "az veri" uyarısı eklenir — küçük
 *  örneklemde kesin bir renkli hüküm yanıltıcı olur. */
function HeadlineBlock({ data }: { data: ReviewSummaryResponse }) {
  const { t } = useTranslation();
  const bucket =
    data.avg_sentiment_score !== null ? sentimentScoreBucket(data.avg_sentiment_score) : null;
  const lowData = data.total < LOW_HEADLINE_TOTAL;
  const verdictText = bucket ? t(`reviews.scoreLabel.${bucket}`) : t("reviews.summary.headline.noScore");
  const verdictClass = lowData
    ? "text-muted-foreground text-lg font-semibold italic"
    : `text-lg font-semibold ${bucket ? (VERDICT_COLOR_CLASS[bucket] ?? "") : ""}`.trim();
  return (
    <div className={CARD_CLASS}>
      <p className="text-2xl font-semibold tracking-tight tabular-nums">
        {t("reviews.summary.headline.recordCount", { count: data.total.toLocaleString("tr-TR") })}
      </p>
      <div className="mt-3 flex items-end justify-between gap-3">
        <div>
          <p className={verdictClass}>{verdictText}</p>
          <p className="text-muted-foreground text-xs tabular-nums">
            {data.avg_sentiment_score !== null ? data.avg_sentiment_score.toFixed(2) : "—"}
          </p>
          {lowData && (
            <p className="text-muted-foreground text-xs italic">
              {t("reviews.summary.headline.lowN", { count: data.total.toLocaleString("tr-TR") })}
            </p>
          )}
        </div>
        {data.ticket_linked > 0 && (
          <p className="text-muted-foreground text-right text-xs">
            {t("reviews.summary.headline.ticketLinked", {
              count: data.ticket_linked.toLocaleString("tr-TR"),
            })}
          </p>
        )}
      </div>
    </div>
  );
}

/** (b) — yatay yığılmış duygu çubuğu + sayaçlı legend. Yeni marka
 *  token'ları (bg-sentiment-*) kullanır — dashboard'daki eski hex
 *  kopyalarının yerine geçecek merkezi paletin İLK kullanıcısı. */
function SentimentBarBlock({
  sentiment,
  total,
}: {
  sentiment: Record<string, number>;
  total: number;
}) {
  const { t } = useTranslation();
  return (
    <div className={CARD_CLASS}>
      <h3 className="text-sm font-medium">{t("reviews.summary.sentiment.title")}</h3>
      <div className="bg-muted mt-3 flex h-2.5 overflow-hidden rounded-full">
        {SENTIMENT_ORDER.map((label) => {
          const count = sentiment[label] ?? 0;
          const pct = total > 0 ? (count / total) * 100 : 0;
          if (pct <= 0) return null;
          return (
            <div
              key={label}
              className={SENTIMENT_BAR_CLASS[label]}
              style={{ width: `${pct}%` }}
              title={`${t(SENTIMENT_LABEL_KEYS[label]!)}: ${count.toLocaleString("tr-TR")}`}
            />
          );
        })}
      </div>
      <ul className="text-muted-foreground mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
        {SENTIMENT_ORDER.map((label) => (
          <li key={label} className="inline-flex items-center gap-1.5">
            <span className={`size-2 rounded-full ${SENTIMENT_BAR_CLASS[label]}`} aria-hidden />
            {t(SENTIMENT_LABEL_KEYS[label]!)} · {(sentiment[label] ?? 0).toLocaleString("tr-TR")}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** (b.5) — CONTENT_TYPES sırasında (risk önce) sıfır olmayan kovalar
 *  kompakt chip satırı. Tümü sıfırsa blok TAMAMEN gizlenir — diğer
 *  bloklarla aynı "boşsa gizlen" konvansiyonu. Escalation>0 iken chip
 *  satırının altına tek satırlık bir yönlendirme eklenir; chip'e
 *  tıklama YOK — filtreleme sayfa üstü ContentTypeFilterDropdown'ın
 *  işi, panel salt-okunur bir özet. */
function ContentTypesBlock({
  contentTypes,
}: {
  contentTypes: Record<string, number> | undefined;
}) {
  const { t } = useTranslation();
  // Backend rollout window (bkz. use-review-summary.ts alan yorumu) —
  // eski bir api yanıtı bu alanı hiç taşımayabilir; boş harita gibi davran.
  const counts = contentTypes ?? {};
  const entries = CONTENT_TYPES.map((type) => ({ type, count: counts[type] ?? 0 })).filter(
    (e) => e.count > 0,
  );
  if (entries.length === 0) return null;
  const escalationCount = counts.escalation ?? 0;
  return (
    <div className={CARD_CLASS}>
      <h3 className="text-sm font-medium">{t("reviews.summary.contentTypes.title")}</h3>
      <ul className="mt-3 flex flex-wrap gap-1.5">
        {entries.map(({ type, count }) => (
          <li
            key={type}
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${CONTENT_TYPE_CHIP_CLASS[type]}`}
          >
            {t(CONTENT_TYPE_LABEL_KEYS[type])}
            <span className="tabular-nums">{count.toLocaleString("tr-TR")}</span>
          </li>
        ))}
      </ul>
      {escalationCount > 0 && (
        <p className="text-sentiment-negative mt-2 text-xs font-medium">
          {t("reviews.summary.contentTypes.escalationHint")}
        </p>
      )}
    </div>
  );
}

/** (c) — with_nps===0 iken TAMAMEN gizlenir (görev notu). with_nps<10
 *  iken sayısal skor GİZLENİR (küçük örneklemde NPS aşırı oynak) —
 *  başlık jenerik "NPS"e döner, dağılım (promoter/passive/detractor)
 *  yine de gösterilir. */
function NpsBlock({ nps }: { nps: ReviewSummaryNps }) {
  const { t } = useTranslation();
  if (nps.with_nps === 0) return null;
  const insufficient = nps.with_nps < LOW_NPS_RESPONSES;
  return (
    <div className={CARD_CLASS}>
      <h3 className="text-sm font-medium">
        {!insufficient && nps.score !== null
          ? t("reviews.summary.nps.score", { score: nps.score.toFixed(1) })
          : t("reviews.summary.nps.title")}
      </h3>
      <p className="text-muted-foreground text-xs">
        {insufficient
          ? t("reviews.summary.nps.insufficientN", { count: nps.with_nps.toLocaleString("tr-TR") })
          : t("reviews.summary.nps.responses", { count: nps.with_nps.toLocaleString("tr-TR") })}
      </p>
      <dl className="mt-2 grid grid-cols-3 gap-2 text-xs">
        <div>
          <dt className="text-muted-foreground">{t("reviews.summary.nps.promoter")}</dt>
          <dd className="font-medium tabular-nums">{nps.promoter.toLocaleString("tr-TR")}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("reviews.summary.nps.passive")}</dt>
          <dd className="font-medium tabular-nums">{nps.passive.toLocaleString("tr-TR")}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("reviews.summary.nps.detractor")}</dt>
          <dd className="font-medium tabular-nums">{nps.detractor.toLocaleString("tr-TR")}</dd>
        </div>
      </dl>
    </div>
  );
}

/** (d) — CSS bar row (yeni kütüphane yok). Yükseklik gün içindeki en
 *  yüksek sayıya normalize; negatif payı aynı çubukta taban hizalı
 *  bg-sentiment-negative kaplamasıyla gösterilir. Backend zaten ≤90
 *  bucket döner (review_list_service.py Query H). */
function DailyTrendBlock({ daily }: { daily: ReviewSummaryDaily[] }) {
  const { t } = useTranslation();
  if (daily.length === 0) return null;
  const filled = fillDailyGaps(daily);
  const max = Math.max(1, ...filled.map((d) => d.count));
  return (
    <div className={CARD_CLASS}>
      <h3 className="text-sm font-medium">{t("reviews.summary.daily.title")}</h3>
      <div
        className="mt-3 flex h-16 items-end gap-px"
        role="img"
        aria-label={t("reviews.summary.daily.title")}
      >
        {filled.map((d) => {
          const heightPct = Math.max((d.count / max) * 100, d.count > 0 ? 6 : 2);
          const negPct = d.count > 0 ? (d.negative / d.count) * 100 : 0;
          return (
            <div
              key={d.date}
              className="bg-muted relative min-w-[2px] flex-1 overflow-hidden rounded-t-sm"
              style={{ height: `${heightPct}%` }}
              title={t("reviews.summary.daily.barAria", {
                date: d.date,
                count: d.count,
                negative: d.negative,
              })}
            >
              <div
                className="bg-sentiment-negative absolute inset-x-0 bottom-0"
                style={{ height: `${negPct}%` }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** (e) — kod -> etiket eşlemesi ReviewRow'daki AYNI desen
 *  (useCategories cache'i kurum genelinde paylaşılır). İnce çubuk bu
 *  kategorinin KENDİ negatif payı (negative_count/count), toplam
 *  içindeki payı değil. */
function CategoriesBlock({
  categories,
  categoryLabels,
}: {
  categories: ReviewSummaryCategoryCount[];
  categoryLabels?: CategoryView[];
}) {
  const { t } = useTranslation();
  if (categories.length === 0) return null;
  return (
    <div className={CARD_CLASS}>
      <h3 className="text-sm font-medium">{t("reviews.summary.categories.title")}</h3>
      <ul className="mt-3 space-y-2">
        {categories.map((c) => {
          const label = categoryLabels?.find((cat) => cat.code === c.code)?.label_tr ?? c.code;
          const negPct = c.count > 0 ? (c.negative_count / c.count) * 100 : 0;
          return (
            <li key={c.code} className="text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="text-foreground/90 truncate font-medium">{label}</span>
                <span className="text-muted-foreground shrink-0 tabular-nums">
                  {c.count.toLocaleString("tr-TR")}
                </span>
              </div>
              <div className="bg-muted mt-1 h-1 overflow-hidden rounded-full">
                <div
                  className={`bg-sentiment-negative h-full ${c.count < 5 ? "opacity-40" : ""}`}
                  style={{ width: `${negPct}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** (f). */
function SourcesBlock({ sources }: { sources: ReviewSummaryValueCount[] }) {
  const { t } = useTranslation();
  if (sources.length === 0) return null;
  return (
    <div className={CARD_CLASS}>
      <h3 className="text-sm font-medium">{t("reviews.summary.sources.title")}</h3>
      <ul className="text-muted-foreground mt-2 space-y-1 text-xs">
        {sources.map((s) => (
          <li key={s.value} className="flex items-center justify-between gap-2">
            <span className="text-foreground/90 truncate">{s.value}</span>
            <span className="shrink-0 tabular-nums">{s.count.toLocaleString("tr-TR")}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** (g) — "hangi temsilci kaç boş/anlamsız girmiş" sorusunu yanıtlar.
 *  entered_by boşsa (dimension_value_present hiç eşleşmediyse) blok
 *  TAMAMEN gizlenir. Uyarı rengi yalnız total>=20 VE flagged/total>=%5
 *  iken tetiklenir — küçük örneklemde tek bir geçersiz kayıt bile oranı
 *  şişirip yanlış alarm verir. */
function EnteredByBlock({ rows }: { rows: ReviewSummaryEnteredBy[] }) {
  const { t } = useTranslation();
  if (rows.length === 0) return null;
  return (
    <div className={CARD_CLASS}>
      <h3 className="text-sm font-medium">{t("reviews.summary.enteredBy.title")}</h3>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted-foreground text-left">
              <th className="pb-1 font-normal whitespace-nowrap">
                {t("reviews.summary.enteredBy.colValue")}
              </th>
              <th className="pb-1 text-right font-normal whitespace-nowrap">
                {t("reviews.summary.enteredBy.colTotal")}
              </th>
              <th className="pb-1 text-right font-normal whitespace-nowrap">
                {t("reviews.summary.enteredBy.colFlagged")}
              </th>
              <th className="pb-1 text-right font-normal whitespace-nowrap">
                {t("reviews.summary.enteredBy.colQuestion")}
              </th>
              <th className="pb-1 text-right font-normal whitespace-nowrap">
                {t("reviews.summary.enteredBy.colNegative")}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const rate = r.total > 0 ? Math.round((r.flagged / r.total) * 1000) / 10 : null;
              const warn =
                r.total >= ENTERED_BY_WARN_MIN_TOTAL &&
                r.flagged / r.total >= ENTERED_BY_WARN_MIN_RATE;
              return (
                <tr key={r.value} className="border-border/60 border-t">
                  <td className="text-foreground/90 max-w-[7rem] truncate py-1.5">{r.value}</td>
                  <td className="text-muted-foreground py-1.5 text-right tabular-nums">
                    {r.total.toLocaleString("tr-TR")}
                  </td>
                  <td
                    className={`py-1.5 text-right tabular-nums ${
                      warn ? "font-medium text-amber-700 dark:text-amber-400" : "text-muted-foreground"
                    }`}
                  >
                    {r.flagged.toLocaleString("tr-TR")}
                    {rate !== null ? ` · %${rate}` : ""}
                  </td>
                  <td className="text-muted-foreground py-1.5 text-right tabular-nums">
                    {r.question.toLocaleString("tr-TR")}
                  </td>
                  <td className="text-muted-foreground py-1.5 text-right tabular-nums">
                    {r.negative.toLocaleString("tr-TR")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** (h) — question_count===0 iken TAMAMEN gizlenir. */
function TopQuestionsBlock({
  topQuestions,
  questionCount,
}: {
  topQuestions: ReviewSummaryTopQuestion[];
  questionCount: number;
}) {
  const { t } = useTranslation();
  if (questionCount === 0) return null;
  return (
    <div className={CARD_CLASS}>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium">{t("reviews.summary.questions.title")}</h3>
        <span className="text-muted-foreground shrink-0 text-xs">
          {t("reviews.summary.questions.totalCount", {
            count: questionCount.toLocaleString("tr-TR"),
          })}
        </span>
      </div>
      <ul className="mt-2 space-y-1.5">
        {topQuestions.map((q) => (
          <li key={`${q.text}-${q.count}`} className="flex items-start justify-between gap-2 text-xs">
            <span className="text-foreground/90 min-w-0 [overflow-wrap:anywhere]">
              {truncate(q.text, 80)}
            </span>
            <Badge variant="secondary" className="shrink-0 tabular-nums">
              {q.count}×
            </Badge>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** (i) — yalnız sıfır olmayan kovalar tek satırda. Tümü sıfırsa
 *  (mümkün değil — total>0 iken en az bir kova dolu olur ama savunmacı
 *  davranıyoruz) blok gizlenir. */
function QualityLineBlock({ quality }: { quality: ReviewSummaryQuality }) {
  const { t } = useTranslation();
  const entries: Array<[key: string, count: number]> = [
    ["clean", quality.clean],
    ["duplicate", quality.duplicate],
    ["empty", quality.empty],
    ["informational", quality.informational],
    ["meaningless", quality.meaningless],
  ];
  const nonZero = entries.filter(([, count]) => count > 0);
  if (nonZero.length === 0) return null;
  return (
    <div className={CARD_CLASS}>
      <h3 className="text-sm font-medium">{t("reviews.summary.quality.title")}</h3>
      <p className="text-muted-foreground mt-1 text-xs">
        {nonZero
          .map(([key, count]) => {
            const label =
              key === "clean" ? t("reviews.summary.quality.clean") : t(QUALITY_FLAG_LABEL_KEYS[key]!);
            return `${label}: ${count.toLocaleString("tr-TR")}`;
          })
          .join(" · ")}
      </p>
    </div>
  );
}
