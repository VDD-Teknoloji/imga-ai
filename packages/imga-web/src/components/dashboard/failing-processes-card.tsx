"use client";

// F1 (2026-09-02) — "Aksayan süreçler" sağ ray kartı (ürün sahibi
// talimatı: kısa, dikkat çeken, sayı-önce değil sinyal-önce kartlar,
// detay bir tıklama arkasında; hiçbir şey ateşlemiyorsa kart tamamen
// sessiz kalır — DataQualityCoach'un "hata da boş de gizlen" ilkesiyle
// aynı).
//
// Üç bağımsız sinyal, her biri kendi eşiğini geçerse EN FAZLA bir
// satır üretir (toplamda en çok 3 satır):
//   (a) aktif trend uyarısı sayısı (useTrendAlerts) -> /trend-alerts
//   (b) SLA ihlali — önce çözüm SLA'sı, kapsamı yoksa/ihlal düşükse ilk
//       yanıt SLA'sı (useOperationsSummary, aynı eşik: %10) -> /insights?tab=operations
//   (c) viral olumsuz tweet sayısı (özet panelinden, page.tsx'ten prop
//       olarak akar — bkz. data-quality-coach.tsx üstündeki not) ->
//       /reviews?sources=twitter&sentiment_labels=NEGATIF&order_by=engagement
//
// NOT (2026-09-02): Bu görev backend'e paralel yürüdü. tenant_reviews.py
// order_by Literal'ı "engagement"i ve ReviewSummaryResponse.
// viral_negative_count alanını görev sırasında (eşzamanlı bir backend
// ajanı tarafından) kazandı — kontrol edildi, ikisi de artık kodda var.
// Web + api bağımsız deploy edildiğinden hangisinin önce canlıya çıktığı
// önemli değil: alan gelmeden bu satır sessizce ateşlemez, sonra kendini
// gösterir. Uçtan uca (gerçek API'ye karşı) doğrulanmadı — bkz. görev
// raporu open_issues.

import Link from "next/link";

import { useOperationsSummary } from "@/hooks/use-operations";
import type { ReviewSummaryResponse } from "@/hooks/use-review-summary";
import { useTrendAlerts } from "@/hooks/use-trend-alerts";
import { useTranslation } from "@/lib/i18n/use-translation";

/** SLA ihlal oranı bu yüzdeyi (veya üstünü) geçerse sinyal sayılır —
 *  görev notundaki örnek kopya (%18) bu eşiğin üstünde bir değer. */
const SLA_VIOLATION_THRESHOLD_PCT = 10;

interface Props {
  /** page.tsx'in tek useReviewSummary çağrısından prop olarak akar —
   *  DataQualityCoach ile aynı sorgu, ikinci bir istek açılmaz. */
  summary: ReviewSummaryResponse | undefined;
  summaryLoading: boolean;
  dateFrom?: string;
  dateTo?: string;
}

export function FailingProcessesCard({
  summary,
  summaryLoading,
  dateFrom,
  dateTo,
}: Props) {
  const { t } = useTranslation();
  const trendAlerts = useTrendAlerts("active");
  const operations = useOperationsSummary({ date_from: dateFrom, date_to: dateTo });

  // Görev notu: "loading = render nothing (no skeleton in the rail)" —
  // üç sinyal kaynağından biri hâlâ ilk yüklemesindeyse kart hiç
  // çizilmez; yarım dolu görünüp sonra satır eklenmesin diye tek seferde
  // kararlaştırılır.
  if (trendAlerts.isLoading || operations.isLoading || summaryLoading) {
    return null;
  }

  const lines: { key: string; text: string; href: string }[] = [];

  const activeAlertCount = trendAlerts.data?.length ?? 0;
  if (activeAlertCount > 0) {
    lines.push({
      key: "trend",
      text: t("dashboard.failingProcesses.trendAlerts", { n: activeAlertCount }),
      href: "/trend-alerts",
    });
  }

  const ops = operations.data;
  if (ops) {
    const insightsHref = operationsHref(dateFrom, dateTo);
    if (
      ops.facts_coverage.sla_resolution > 0 &&
      ops.sla.resolution.violation_rate_pct >= SLA_VIOLATION_THRESHOLD_PCT
    ) {
      lines.push({
        key: "sla-resolution",
        text: t("dashboard.failingProcesses.slaResolution", {
          pct: Math.round(ops.sla.resolution.violation_rate_pct),
        }),
        href: insightsHref,
      });
    } else if (
      ops.facts_coverage.sla_first_response > 0 &&
      ops.sla.first_response.violation_rate_pct >= SLA_VIOLATION_THRESHOLD_PCT
    ) {
      lines.push({
        key: "sla-first-response",
        text: t("dashboard.failingProcesses.slaFirstResponse", {
          pct: Math.round(ops.sla.first_response.violation_rate_pct),
        }),
        href: insightsHref,
      });
    }
  }

  // Backend alanı henüz yoksa (bkz. dosya üstü not) summary.
  // viral_negative_count JS'te undefined gelir; `> 0` karşılaştırması
  // undefined için false olduğundan ek bir guard'a gerek yok.
  if (summary && summary.viral_negative_count > 0) {
    lines.push({
      key: "viral",
      text: t("dashboard.failingProcesses.viral", { n: summary.viral_negative_count }),
      href: "/reviews?sources=twitter&sentiment_labels=NEGATIF&order_by=engagement",
    });
  }

  // Sessizlik kuralı: hiçbir sinyal ateşlemediyse kart hiç yok.
  if (lines.length === 0) return null;

  return (
    <section
      className="rise-in shadow-soft bg-card ring-foreground/5 break-words rounded-3xl p-5 ring-1"
      aria-label={t("dashboard.failingProcesses.title")}
    >
      <h2 className="text-sm font-semibold">{t("dashboard.failingProcesses.title")}</h2>
      <ul className="mt-2 space-y-1.5">
        {lines.map((line) => (
          <li key={line.key}>
            <Link
              href={line.href}
              className="text-muted-foreground hover:text-foreground text-sm leading-relaxed underline underline-offset-2 transition-colors"
            >
              {line.text}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** /insights'ın operasyon sekmesine, sayfanın aktif dönemi taşınarak
 *  gider (insights/page.tsx tab + date_from/date_to URL state'ini
 *  okuyor). */
function operationsHref(dateFrom: string | undefined, dateTo: string | undefined): string {
  const params = new URLSearchParams();
  params.set("tab", "operations");
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  return `/insights?${params.toString()}`;
}
