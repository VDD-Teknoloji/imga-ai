"use client";

// Sprint 13 — ana sayfa filtre çubuğu: dönem presetleri + özel tarih
// aralığı + yükleme (batch) seçici. TimeWindowFilter'ın evrimi.
//
// Tek gerçek kaynak kuralı (url-state-patterns.md + recon brifi):
// özel tarih girilince ?window silinir, preset seçilince
// ?date_from/?date_to silinir; ?batch_job_id ikisiyle de birleşir.
// State URL'de yaşar — bu bileşen saf controlled, push'lar sayfada.

import { X } from "lucide-react";

import { IncludeFlaggedToggle } from "@/components/analytics/include-flagged-toggle";
import { TimeWindowFilter, type TimeWindowKey } from "@/components/dashboard/time-window-filter";
import { BatchFilterDropdown } from "@/components/reviews/batch-filter-dropdown";
import { DateField } from "@/components/ui/date-field";
import { useBatchHistory } from "@/hooks/use-batch-uploads";
import { useTranslation } from "@/lib/i18n/use-translation";

interface Props {
  windowKey: TimeWindowKey;
  onWindowChange: (next: TimeWindowKey) => void;
  /** YYYY-MM-DD veya "" (seçili değil). */
  dateFrom: string;
  dateTo: string;
  onDateFromChange: (next: string) => void;
  onDateToChange: (next: string) => void;
  /** Batch job UUID veya "" (seçili değil). */
  batchJobId: string;
  onBatchChange: (next: string | undefined) => void;
  /** 2026-08-18 (Dalga 3, WS2) — "Düşük kaliteli veriyi dahil et" switch. */
  includeFlagged: boolean;
  onIncludeFlaggedChange: (next: boolean) => void;
  onClear: () => void;
}

export function DashboardFilterBar({
  windowKey,
  onWindowChange,
  dateFrom,
  dateTo,
  onDateFromChange,
  onDateToChange,
  batchJobId,
  onBatchChange,
  includeFlagged,
  onIncludeFlaggedChange,
  onClear,
}: Props) {
  const { t } = useTranslation();
  // BatchFilterDropdown ile aynı query key — chip etiketi için ek
  // istek atmaz, cache'ten okur.
  const history = useBatchHistory(50);
  const selectedJob = batchJobId
    ? history.data?.pages.flatMap((p) => p.jobs).find((j) => j.job_id === batchJobId)
    : undefined;

  const hasAnyFilter =
    windowKey !== "all" ||
    dateFrom !== "" ||
    dateTo !== "" ||
    batchJobId !== "" ||
    includeFlagged;

  return (
    <div className="rise-in flex flex-wrap items-center gap-x-5 gap-y-3">
      <TimeWindowFilter value={windowKey} onChange={onWindowChange} />

      <div
        className="flex flex-wrap items-center gap-2"
        role="group"
        aria-label={t("dashboard.filterBar.customRange")}
      >
        <span className="text-muted-foreground text-sm font-medium">
          {t("dashboard.filterBar.customRange")}
        </span>
        <DateField
          value={dateFrom}
          max={dateTo || undefined}
          aria-label={t("dashboard.filterBar.dateFromAria")}
          onChange={(e) => onDateFromChange(e.target.value)}
        />
        <span className="text-muted-foreground text-xs" aria-hidden>
          –
        </span>
        <DateField
          value={dateTo}
          min={dateFrom || undefined}
          aria-label={t("dashboard.filterBar.dateToAria")}
          onChange={(e) => onDateToChange(e.target.value)}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <BatchFilterDropdown
          selected={batchJobId || undefined}
          onChange={onBatchChange}
          inline
        />
        {batchJobId !== "" && (
          <span className="bg-primary/10 text-primary inline-flex max-w-[280px] items-center gap-1.5 rounded-full py-1 pl-3 pr-1.5 text-xs font-medium">
            <span className="truncate">
              {t("dashboard.filterBar.batchLabel")}:{" "}
              {selectedJob?.file_name ?? "…"}
            </span>
            <button
              type="button"
              aria-label={t("dashboard.filterBar.batchChipRemove")}
              onClick={() => onBatchChange(undefined)}
              className="hover:bg-primary/15 rounded-full p-0.5 transition-colors"
            >
              <X className="size-3" aria-hidden />
            </button>
          </span>
        )}
      </div>

      <IncludeFlaggedToggle checked={includeFlagged} onChange={onIncludeFlaggedChange} />

      {hasAnyFilter && (
        <button
          type="button"
          onClick={onClear}
          className="text-muted-foreground hover:text-foreground text-xs font-medium underline-offset-2 transition-colors hover:underline"
        >
          {t("dashboard.filterBar.clear")}
        </button>
      )}
    </div>
  );
}
