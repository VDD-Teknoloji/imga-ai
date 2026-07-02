"use client";

import {
  ArrowRight,
  CheckCircle2,
  Download,
  Loader2,
  Plus,
  Trash2,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useDeleteReport,
  useEstimateReport,
  useGenerateReport,
  useReportJob,
  useReports,
} from "@/hooks/use-reports";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";
import type {
  GenerateReportRequest,
  ReportEstimateResponse,
  ReportFormat,
  ReportJobView,
  ReportStatus,
  ReportType,
} from "@/lib/types";
import { cn } from "@/lib/utils";

/** Live translate function type (t) so non-component helpers can render
 *  localised strings without pulling in a hook. */
type TFunc = ReturnType<typeof useTranslation>["t"];

const TYPE_LABEL_KEYS: Record<ReportType, string> = {
  comprehensive: "reports.type.comprehensive",
  reviews_only: "reports.type.reviewsOnly",
  tickets_only: "reports.type.ticketsOnly",
};

const STATUS_LABEL_KEYS: Record<ReportStatus, string> = {
  queued: "reports.status.queued",
  generating: "reports.status.generating",
  completed: "reports.status.completed",
  failed: "reports.status.failed",
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

export default function ReportsPage() {
  const { t } = useTranslation();
  const [modalOpen, setModalOpen] = useState(false);
  const [pollingId, setPollingId] = useState<string | null>(null);

  const list = useReports(50);
  const reports = list.data?.pages.flatMap((p) => p.reports) ?? [];
  const polled = useReportJob(pollingId);

  // Stop polling once the polled job hits a terminal state. The
  // setState here mirrors the async settle of the TanStack Query
  // poll onto sync UI state — there's no event to hang this on and
  // hook-level refetchInterval-stop would still need a setState
  // somewhere to clear the local pollingId. Intentional exception
  // to react-hooks/set-state-in-effect.
  useEffect(() => {
    if (!polled.data) return;
    if (polled.data.status === "completed" || polled.data.status === "failed") {
      list.refetch();
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setPollingId(null);
    }
  }, [polled.data, list]);

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6 md:px-8 md:py-10">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1.5">
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {t("reports.page.title")}
          </h1>
          <p className="text-muted-foreground text-sm">
            {t("reports.page.subtitle")}
          </p>
        </div>
        <Button onClick={() => setModalOpen(true)}>
          <Plus className="size-4" /> {t("reports.newReport")}
        </Button>
      </header>

      {polled.data && polled.data.status !== "completed" && polled.data.status !== "failed" && (
        <Card className="border-primary/30">
          <CardContent className="flex items-center gap-3 p-4">
            <Loader2 className="size-4 animate-spin" />
            <span className="text-sm">
              <span className="font-medium">
                {t(TYPE_LABEL_KEYS[polled.data.report_type])}
              </span>{" "}
              {t("reports.generatingMid")} {t(STATUS_LABEL_KEYS[polled.data.status])}
            </span>
          </CardContent>
        </Card>
      )}

      {list.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
        </div>
      ) : reports.length === 0 ? (
        <p className="text-muted-foreground p-6 text-sm">
          {t("reports.emptyPre")}
          <strong>{t("reports.newReport")}</strong>
          {t("reports.emptyPost")}
        </p>
      ) : (
        <ReportsTable reports={reports} />
      )}

      {modalOpen && (
        <NewReportModal
          onClose={() => setModalOpen(false)}
          onQueued={(id) => {
            setPollingId(id);
            setModalOpen(false);
            list.refetch();
          }}
        />
      )}
    </main>
  );
}

// --------------------------------------------------------------------------
// Reports table
// --------------------------------------------------------------------------

function ReportsTable({ reports }: { reports: ReportJobView[] }) {
  const { t } = useTranslation();
  const del = useDeleteReport();
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("reports.table.date")}</TableHead>
          <TableHead>{t("reports.table.type")}</TableHead>
          <TableHead>{t("reports.table.format")}</TableHead>
          <TableHead className="text-right">{t("reports.table.rows")}</TableHead>
          <TableHead className="text-right">{t("reports.table.size")}</TableHead>
          <TableHead>{t("reports.table.status")}</TableHead>
          <TableHead className="text-right" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {reports.map((r) => (
          <TableRow key={r.report_id}>
            <TableCell className="text-muted-foreground text-xs">
              {new Date(r.created_at).toLocaleString("tr-TR")}
            </TableCell>
            <TableCell className="font-medium">
              {t(TYPE_LABEL_KEYS[r.report_type])}
            </TableCell>
            <TableCell className="text-xs uppercase">{r.format}</TableCell>
            <TableCell className="text-right tabular-nums">
              {r.row_count ?? "—"}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {r.file_size_bytes ? formatBytes(r.file_size_bytes) : "—"}
            </TableCell>
            <TableCell>
              <StatusBadge status={r.status} message={r.error_message} />
            </TableCell>
            <TableCell className="flex justify-end gap-2">
              {r.status === "completed" && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => downloadReport(r.report_id, t)}
                >
                  <Download className="size-3.5" /> {t("reports.download")}
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  if (!confirm(t("reports.deleteConfirm"))) {
                    return;
                  }
                  del.mutate(r.report_id, {
                    onError: () => toast.error(t("reports.deleteError")),
                    onSuccess: () => toast.success(t("reports.deleteSuccess")),
                  });
                }}
                disabled={del.isPending}
              >
                <Trash2 className="size-3.5" />
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function StatusBadge({
  status,
  message,
}: {
  status: ReportStatus;
  message: string | null;
}) {
  const { t } = useTranslation();
  const Icon =
    status === "completed"
      ? CheckCircle2
      : status === "failed"
        ? XCircle
        : Loader2;
  const tone =
    status === "completed"
      ? "bg-emerald-100 text-emerald-700"
      : status === "failed"
        ? "bg-red-100 text-red-700"
        : "bg-amber-100 text-amber-700";
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs", tone)}
      title={message ?? undefined}
    >
      <Icon
        className={cn("size-3", status !== "completed" && status !== "failed" && "animate-spin")}
        aria-hidden
      />
      {t(STATUS_LABEL_KEYS[status])}
    </span>
  );
}

function downloadReport(reportId: string, t: TFunc): void {
  // Browser-native <a download> can't ride credentials:'include', so
  // we fetch the bytes ourselves (the cookie does flow on fetch with
  // credentials), then trigger a synthetic anchor-click against an
  // ObjectURL so Chrome / Firefox / Safari all save the file with
  // the right content-disposition filename.
  const path = `/tenants/me/reports/${reportId}/download`;
  fetch(`${API_BASE}${path}`, {
    credentials: "include",
  })
    .then(async (res) => {
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        toast.error(
          t("reports.downloadError", {
            status: res.status,
            detail: detail.slice(0, 80),
          }),
        );
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download =
        res.headers
          .get("content-disposition")
          ?.match(/filename="?([^"]+)"?/)?.[1] ?? `imga-rapor-${reportId}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    })
    .catch(() => toast.error(t("reports.downloadStartError")));
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

// --------------------------------------------------------------------------
// New Report modal — 3 steps: type → filters → preview/confirm.
// --------------------------------------------------------------------------

type ModalStep = 1 | 2 | 3;

function NewReportModal({
  onClose,
  onQueued,
}: {
  onClose: () => void;
  onQueued: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [step, setStep] = useState<ModalStep>(1);
  const [reportType, setReportType] = useState<ReportType>("comprehensive");
  const [format, setFormat] = useState<ReportFormat>("xlsx");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [estimate, setEstimate] = useState<ReportEstimateResponse | null>(null);
  const [estimateError, setEstimateError] = useState<string | null>(null);

  const estimateMut = useEstimateReport();
  const generate = useGenerateReport();

  function quickRange(rangeKey: "this-month" | "last-month" | "this-quarter") {
    const now = new Date();
    let from = new Date(now);
    let to = new Date(now);
    if (rangeKey === "this-month") {
      from = new Date(now.getFullYear(), now.getMonth(), 1);
    } else if (rangeKey === "last-month") {
      from = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      to = new Date(now.getFullYear(), now.getMonth(), 0);
    } else {
      const qStart = Math.floor(now.getMonth() / 3) * 3;
      from = new Date(now.getFullYear(), qStart, 1);
    }
    setDateFrom(from.toISOString().slice(0, 10));
    setDateTo(to.toISOString().slice(0, 10));
  }

  const dayDiff =
    dateFrom && dateTo
      ? Math.round(
          (new Date(dateTo).getTime() - new Date(dateFrom).getTime()) /
            (1000 * 60 * 60 * 24),
        )
      : 0;
  const overLimit = dayDiff > 90;

  function buildBody(): GenerateReportRequest {
    return {
      report_type: reportType,
      format,
      filters: {
        date_from: dateFrom ? new Date(dateFrom).toISOString() : undefined,
        date_to: dateTo ? new Date(`${dateTo}T23:59:59`).toISOString() : undefined,
      },
    };
  }

  function goToPreview() {
    setEstimateError(null);
    setEstimate(null);
    estimateMut.mutate(buildBody(), {
      onSuccess: (data) => {
        setEstimate(data);
        setStep(3);
      },
      onError: (err) => {
        // Stay on Step 2 with the inline error so the user can fix
        // filters without losing their inputs.
        if (err instanceof ApiError) {
          setEstimateError(err.detail);
        } else {
          setEstimateError(t("reports.estimateError"));
        }
      },
    });
  }

  function handleSubmit() {
    generate.mutate(buildBody(), {
      onSuccess: (data) => {
        toast.success(t("reports.queuedSuccess"));
        onQueued(data.report_id);
      },
      onError: (err) => {
        if (err instanceof ApiError) {
          toast.error(err.detail);
        } else {
          toast.error(t("reports.generateError"));
        }
      },
    });
  }

  return (
    <div className="bg-foreground/40 fixed inset-0 z-50 flex items-center justify-center p-4">
      <Card className="w-full max-w-lg">
        <CardHeader className="flex items-center justify-between">
          <CardTitle>{t("reports.modalTitle", { step })}</CardTitle>
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
            aria-label={t("reports.close")}
          >
            <XCircle className="size-5" />
          </button>
        </CardHeader>
        <CardContent className="space-y-5">
          {step === 1 && (
            <Step1Type
              reportType={reportType}
              format={format}
              setReportType={setReportType}
              setFormat={setFormat}
            />
          )}
          {step === 2 && (
            <Step2Filters
              dateFrom={dateFrom}
              dateTo={dateTo}
              setDateFrom={setDateFrom}
              setDateTo={setDateTo}
              quickRange={quickRange}
              dayDiff={dayDiff}
              overLimit={overLimit}
              estimateError={estimateError}
            />
          )}
          {step === 3 && estimate && (
            <Step3Preview
              estimate={estimate}
              reportType={reportType}
              format={format}
              dateFrom={dateFrom}
              dateTo={dateTo}
            />
          )}

          <div className="flex justify-between gap-2 pt-2">
            <Button
              variant="outline"
              type="button"
              onClick={step === 1 ? onClose : () => setStep((step - 1) as ModalStep)}
              disabled={generate.isPending}
            >
              {step === 1 ? t("common.cancel") : t("reports.back")}
            </Button>
            {step === 1 && (
              <Button type="button" onClick={() => setStep(2)}>
                {t("reports.continue")} <ArrowRight className="size-4" aria-hidden />
              </Button>
            )}
            {step === 2 && (
              <Button
                type="button"
                onClick={goToPreview}
                disabled={overLimit || estimateMut.isPending}
              >
                {estimateMut.isPending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <ArrowRight className="size-4" />
                )}
                {t("reports.preview")}
              </Button>
            )}
            {step === 3 && estimate && (
              <Button
                type="button"
                onClick={handleSubmit}
                disabled={generate.isPending}
              >
                {generate.isPending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Plus className="size-4" />
                )}
                {t("reports.generate")}
              </Button>
            )}
          </div>

          <Badge variant="outline" className="text-xs font-normal">
            ⓘ {t("reports.hardLimit")}
          </Badge>
        </CardContent>
      </Card>
    </div>
  );
}

// --- modal step components -----------------------------------------------

function Step1Type({
  reportType,
  format,
  setReportType,
  setFormat,
}: {
  reportType: ReportType;
  format: ReportFormat;
  setReportType: (t: ReportType) => void;
  setFormat: (f: ReportFormat) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-5">
      <div>
        <Label className="text-xs">{t("reports.reportType")}</Label>
        <div className="mt-2 space-y-2">
          {(["comprehensive", "reviews_only", "tickets_only"] as ReportType[]).map(
            (rt) => (
              <label
                key={rt}
                className="flex cursor-pointer items-center gap-2 text-sm"
              >
                <input
                  type="radio"
                  name="report-type"
                  checked={reportType === rt}
                  onChange={() => setReportType(rt)}
                />
                {t(TYPE_LABEL_KEYS[rt])}
              </label>
            ),
          )}
        </div>
      </div>
      <div>
        <Label className="text-xs">Format</Label>
        <div className="mt-2 flex gap-4 text-sm">
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="radio"
              name="format"
              checked={format === "xlsx"}
              onChange={() => setFormat("xlsx")}
            />
            Excel (.xlsx)
          </label>
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="radio"
              name="format"
              checked={format === "csv"}
              onChange={() => setFormat("csv")}
            />
            CSV (.zip)
          </label>
        </div>
      </div>
    </div>
  );
}

function Step2Filters({
  dateFrom,
  dateTo,
  setDateFrom,
  setDateTo,
  quickRange,
  dayDiff,
  overLimit,
  estimateError,
}: {
  dateFrom: string;
  dateTo: string;
  setDateFrom: (v: string) => void;
  setDateTo: (v: string) => void;
  quickRange: (k: "this-month" | "last-month" | "this-quarter") => void;
  dayDiff: number;
  overLimit: boolean;
  estimateError: string | null;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <Label className="text-xs">{t("reports.dateRange")}</Label>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => quickRange("this-month")}
        >
          {t("reports.thisMonth")}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => quickRange("last-month")}
        >
          {t("reports.lastMonth")}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => quickRange("this-quarter")}
        >
          {t("reports.thisQuarter")}
        </Button>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <input
          type="date"
          value={dateFrom}
          max={dateTo || undefined}
          onChange={(e) => setDateFrom(e.target.value)}
          className="border-input bg-background rounded-md border px-3 py-2 text-sm"
        />
        <input
          type="date"
          value={dateTo}
          min={dateFrom || undefined}
          onChange={(e) => setDateTo(e.target.value)}
          className="border-input bg-background rounded-md border px-3 py-2 text-sm"
        />
      </div>
      {dayDiff > 0 && (
        <p
          className={cn(
            "mt-1 text-xs",
            overLimit ? "text-red-600" : "text-muted-foreground",
          )}
        >
          {t("reports.rangeDays", { days: dayDiff })}
          {overLimit && t("reports.rangeOverLimit")}
        </p>
      )}
      {estimateError && (
        <p className="text-destructive mt-2 text-xs">{estimateError}</p>
      )}
    </div>
  );
}

function Step3Preview({
  estimate,
  reportType,
  format,
  dateFrom,
  dateTo,
}: {
  estimate: ReportEstimateResponse;
  reportType: ReportType;
  format: ReportFormat;
  dateFrom: string;
  dateTo: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="bg-muted/30 space-y-3 rounded-xl border p-4 text-sm">
      <p className="font-medium">{t("reports.preview")}</p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <dt className="text-muted-foreground">{t("reports.est.rows")}</dt>
        <dd className="tabular-nums">{estimate.row_count_estimate.toLocaleString("tr-TR")}</dd>
        <dt className="text-muted-foreground">{t("reports.est.time")}</dt>
        <dd>{t("reports.est.seconds", { n: estimate.estimated_seconds })}</dd>
        <dt className="text-muted-foreground">{t("reports.est.type")}</dt>
        <dd>{t(TYPE_LABEL_KEYS[reportType])}</dd>
        <dt className="text-muted-foreground">{t("reports.est.format")}</dt>
        <dd>{format === "xlsx" ? "Excel (.xlsx)" : "CSV (.zip)"}</dd>
        {dateFrom && dateTo && (
          <>
            <dt className="text-muted-foreground">{t("reports.est.dateRange")}</dt>
            <dd>
              {dateFrom} – {dateTo}
            </dd>
          </>
        )}
        {estimate.review_rows > 0 && (
          <>
            <dt className="text-muted-foreground">{t("reports.est.reviewRows")}</dt>
            <dd className="tabular-nums">{estimate.review_rows.toLocaleString("tr-TR")}</dd>
          </>
        )}
        {estimate.ticket_rows > 0 && (
          <>
            <dt className="text-muted-foreground">{t("reports.est.ticketRows")}</dt>
            <dd className="tabular-nums">{estimate.ticket_rows.toLocaleString("tr-TR")}</dd>
          </>
        )}
      </dl>
    </div>
  );
}
