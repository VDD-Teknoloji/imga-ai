"use client";

// 2026-09-03 (SWOT/OKR görsel sadeleştirme) — SwotViewer/OkrViewer
// başlığındaki eski düz-metin ReportMeta'nın yerini alan ikonlu şerit.
// PO talimatı: "generated when, period, review count — no paragraph,
// model-free wording". Eski satır model_name + token_usage de
// gösteriyordu; bu ikisi kasıtlı olarak burada YOK — teknik ayrıntı,
// yöneticinin sorduğu soruya cevap vermiyor (Geçmiş sekmesindeki liste
// satırı hâlâ model_name gösterir, o ayrı bir yüzey, bu görevin
// kapsamı dışında).

import { CalendarRange, Clock, Link2, MessageSquare } from "lucide-react";

import { useTranslation } from "@/lib/i18n/use-translation";
import { formatDateTr, relativeTimeTr } from "@/lib/relative-time";
import type { StrategicReportDetail } from "@/lib/types";

function reviewCount(stats: Record<string, unknown>): number | null {
  const n = stats.total_reviews;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

export function ReportMetaStrip({
  report,
  sourceReport,
}: {
  report: StrategicReportDetail;
  /** OKR raporunun üretildiği kaynak SWOT — verilirse ayrı bir çip
   *  eklenir (eski sourceSwotPrefix paragraf-içi metninin yerini alır). */
  sourceReport?: StrategicReportDetail | null;
}) {
  const { t, locale } = useTranslation();
  const numberLocale = locale === "en" ? "en-US" : "tr-TR";
  const period =
    report.date_from && report.date_to
      ? `${report.date_from} → ${report.date_to}`
      : t("dashboard.strategy.allPeriod");
  const n = reviewCount(report.input_stats);

  return (
    <div className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
      <span
        className="inline-flex items-center gap-1.5"
        title={formatDateTr(report.created_at)}
        aria-label={t("dashboard.strategy.meta.generatedAria", {
          time: relativeTimeTr(report.created_at),
        })}
      >
        <Clock className="size-3.5" aria-hidden />
        {relativeTimeTr(report.created_at)}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <CalendarRange className="size-3.5" aria-hidden />
        {period}
      </span>
      {n !== null && (
        <span className="inline-flex items-center gap-1.5">
          <MessageSquare className="size-3.5" aria-hidden />
          {t("dashboard.strategy.meta.reviewCount", {
            n: n.toLocaleString(numberLocale),
          })}
        </span>
      )}
      {sourceReport && (
        <span className="inline-flex items-center gap-1.5">
          <Link2 className="size-3.5" aria-hidden />
          {t("dashboard.strategy.okr.sourceSwotChip", {
            date: new Date(sourceReport.created_at).toLocaleDateString(numberLocale),
          })}
        </span>
      )}
    </div>
  );
}
