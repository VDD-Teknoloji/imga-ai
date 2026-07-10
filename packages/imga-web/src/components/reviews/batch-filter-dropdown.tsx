"use client";

// Sprint 8.3.11 — batch picker for /reviews + /strategy (+ Sprint 13
// ana sayfa filtre çubuğu).
//
// Sprint 13 redesign (ürün sahibi geri bildirimi): aynı güne ait /
// aynı adlı yüklemeler ayırt edilemiyordu — satırlar artık iki
// katmanlı: dosya adı + (saat · satır sayısı · durum noktası).
// Panel genişletildi, kapalı tetik kısaltılmış ad + saat gösterir.

import { Loader2 } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useBatchHistory } from "@/hooks/use-batch-uploads";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { BatchJob, BatchJobStatus } from "@/lib/types";

interface Props {
  selected: string | undefined;
  onChange: (next: string | undefined) => void;
  /** When true, the trigger label reads "Yükleme: …" so the dropdown
   *  reads naturally inline alongside other filter pills. */
  inline?: boolean;
}

const STATUS_DOT: Record<BatchJobStatus, string> = {
  completed: "bg-emerald-500",
  processing: "bg-amber-500",
  queued: "bg-zinc-400",
  failed: "bg-red-500",
  cancelled: "bg-zinc-400",
};

const STATUS_KEY: Record<BatchJobStatus, string> = {
  completed: "common.batchStatus.completed",
  processing: "common.batchStatus.processing",
  queued: "common.batchStatus.queued",
  failed: "common.batchStatus.failed",
  cancelled: "common.batchStatus.cancelled",
};

export function BatchFilterDropdown({ selected, onChange, inline }: Props) {
  const { t, locale } = useTranslation();
  const history = useBatchHistory(50);
  const jobs: BatchJob[] = history.data?.pages.flatMap((p) => p.jobs) ?? [];

  const allLabel = inline
    ? t("common.batchPicker.triggerAll")
    : t("common.batchPicker.all");

  return (
    <Select
      value={selected || "__all__"}
      onValueChange={(v) =>
        onChange(v === "__all__" || v === null ? undefined : v ?? undefined)
      }
    >
      <SelectTrigger className="h-8 max-w-[320px] gap-1 text-xs">
        {history.isLoading ? (
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
        ) : null}
        {/* Base UI Select.Value çocuk verilmezse ham UUID basar —
            kapalı hâlde etiketi children-fn ile çöz. */}
        <SelectValue>
          {(value: string | null) => {
            if (!value || value === "__all__") return allLabel;
            const job = jobs.find((j) => j.job_id === value);
            if (!job) return t("common.batchPicker.selectedFallback");
            const prefix = inline ? `${t("common.batchPicker.prefix")}: ` : "";
            return `${prefix}${shortName(job.file_name)} · ${timeOnly(job.created_at, locale)}`;
          }}
        </SelectValue>
      </SelectTrigger>
      <SelectContent className="min-w-[340px]">
        <SelectItem value="__all__">{allLabel}</SelectItem>
        {jobs.map((j) => (
          <SelectItem key={j.job_id} value={j.job_id} className="py-2">
            <span className="flex min-w-0 flex-col gap-0.5">
              <span
                className="max-w-[300px] truncate text-sm font-medium"
                title={j.file_name}
              >
                {j.file_name}
              </span>
              <span className="text-muted-foreground flex items-center gap-1.5 text-xs tabular-nums">
                <span
                  className={`size-1.5 shrink-0 rounded-full ${STATUS_DOT[j.status]}`}
                  aria-hidden
                />
                {formatJobDate(j.created_at, locale, t)}
                {" · "}
                {t("common.batchPicker.rows", {
                  n: j.total_rows.toLocaleString(
                    locale === "en" ? "en-US" : "tr-TR",
                  ),
                })}
                {" · "}
                {t(STATUS_KEY[j.status])}
              </span>
            </span>
          </SelectItem>
        ))}
        {!history.isLoading && jobs.length === 0 && (
          <SelectItem value="__none__" disabled>
            {t("common.batchPicker.none")}
          </SelectItem>
        )}
      </SelectContent>
    </Select>
  );
}

function shortName(name: string): string {
  return name.length > 28 ? name.slice(0, 25) + "…" : name;
}

function timeOnly(iso: string, locale: string): string {
  return new Date(iso).toLocaleTimeString(
    locale === "en" ? "en-US" : "tr-TR",
    { hour: "2-digit", minute: "2-digit" },
  );
}

/** Bugün/Dün + saat; daha eskiler "11 Haz 2026 14:32". Aynı güne ait
 *  yüklemeleri saat ayırt eder. */
function formatJobDate(
  iso: string,
  locale: string,
  t: (key: string, vars?: Record<string, string | number>) => string,
): string {
  const d = new Date(iso);
  const now = new Date();
  const time = timeOnly(iso, locale);
  const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(d, now)) return `${t("common.batchPicker.today")} ${time}`;
  if (sameDay(d, yesterday)) {
    return `${t("common.batchPicker.yesterday")} ${time}`;
  }
  const date = d.toLocaleDateString(locale === "en" ? "en-US" : "tr-TR", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  return `${date} ${time}`;
}
