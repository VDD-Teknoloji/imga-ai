"use client";

import {
  ArrowRight,
  CheckCircle2,
  Download,
  FileBarChart,
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
import { tokenStorage } from "@/lib/token-storage";
import type {
  GenerateReportRequest,
  ReportEstimateResponse,
  ReportFormat,
  ReportJobView,
  ReportStatus,
  ReportType,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const TYPE_LABELS: Record<ReportType, string> = {
  comprehensive: "Kapsamlı",
  reviews_only: "Sadece Analizler",
  tickets_only: "Sadece Biletler",
};

const STATUS_LABELS: Record<ReportStatus, string> = {
  queued: "Sırada",
  generating: "Üretiliyor",
  completed: "Tamamlandı",
  failed: "Başarısız",
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

export default function ReportsPage() {
  const [modalOpen, setModalOpen] = useState(false);
  const [pollingId, setPollingId] = useState<string | null>(null);

  const list = useReports(50);
  const reports = list.data?.pages.flatMap((p) => p.reports) ?? [];
  const polled = useReportJob(pollingId);

  // Stop polling once the polled job hits a terminal state.
  useEffect(() => {
    if (!polled.data) return;
    if (polled.data.status === "completed" || polled.data.status === "failed") {
      list.refetch();
      setPollingId(null);
    }
  }, [polled.data, list]);

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-8">
      <header className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <FileBarChart className="text-primary size-6" aria-hidden />
          <div>
            <h1 className="text-2xl font-semibold">Raporlar</h1>
            <p className="text-muted-foreground text-sm">
              Excel veya CSV olarak çok-sayfalı analiz + bilet raporları
              üretip 24 saat boyunca indirin.
            </p>
          </div>
        </div>
        <Button onClick={() => setModalOpen(true)}>
          <Plus className="size-4" /> Yeni Rapor
        </Button>
      </header>

      {polled.data && polled.data.status !== "completed" && polled.data.status !== "failed" && (
        <Card className="border-primary/30">
          <CardContent className="flex items-center gap-3 p-4">
            <Loader2 className="size-4 animate-spin" />
            <span className="text-sm">
              <span className="font-medium">{TYPE_LABELS[polled.data.report_type]}</span>{" "}
              raporu üretiliyor… durum: {STATUS_LABELS[polled.data.status]}
            </span>
          </CardContent>
        </Card>
      )}

      {list.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> Yükleniyor…
        </div>
      ) : reports.length === 0 ? (
        <p className="text-muted-foreground p-6 text-sm">
          Henüz rapor yok. Üstteki <strong>Yeni Rapor</strong> butonu ile
          ilk raporunuzu üretebilirsiniz.
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
  const del = useDeleteReport();
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Tarih</TableHead>
          <TableHead>Tip</TableHead>
          <TableHead>Format</TableHead>
          <TableHead className="text-right">Satır</TableHead>
          <TableHead className="text-right">Boyut</TableHead>
          <TableHead>Durum</TableHead>
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
              {TYPE_LABELS[r.report_type]}
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
                  onClick={() => downloadReport(r.report_id)}
                >
                  <Download className="size-3.5" /> İndir
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  if (!confirm("Raporu silmek istediğinizden emin misiniz?")) {
                    return;
                  }
                  del.mutate(r.report_id, {
                    onError: () => toast.error("Silinemedi."),
                    onSuccess: () => toast.success("Rapor silindi."),
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
      className={cn("inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs", tone)}
      title={message ?? undefined}
    >
      <Icon
        className={cn("size-3", status !== "completed" && status !== "failed" && "animate-spin")}
        aria-hidden
      />
      {STATUS_LABELS[status]}
    </span>
  );
}

function downloadReport(reportId: string): void {
  // Browser-native <a download> can't carry the bearer header — every
  // request hit /reports/{id}/download as anonymous and got 401. We
  // fetch the bytes ourselves with the token from `tokenStorage`
  // (canonical key `imga_access_token`; the previous attempt used
  // `imga.access_token` and silently sent an empty Authorization
  // header), then trigger a synthetic anchor-click against an
  // ObjectURL so Chrome / Firefox / Safari all save the file with
  // the right content-disposition filename.
  const path = `/tenants/me/reports/${reportId}/download`;
  const accessToken = tokenStorage.getAccessToken();
  if (!accessToken) {
    toast.error("Oturum süresi dolmuş, lütfen tekrar giriş yapın.");
    return;
  }
  fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
    .then(async (res) => {
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        toast.error(`İndirilemedi: ${res.status} ${detail.slice(0, 80)}`);
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
    .catch(() => toast.error("İndirme başlatılamadı."));
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
          setEstimateError("Tahmin alınamadı.");
        }
      },
    });
  }

  function handleSubmit() {
    generate.mutate(buildBody(), {
      onSuccess: (data) => {
        toast.success("Rapor sıraya alındı.");
        onQueued(data.report_id);
      },
      onError: (err) => {
        if (err instanceof ApiError) {
          toast.error(err.detail);
        } else {
          toast.error("Rapor üretilemedi.");
        }
      },
    });
  }

  return (
    <div className="bg-foreground/40 fixed inset-0 z-50 flex items-center justify-center p-4">
      <Card className="w-full max-w-lg">
        <CardHeader className="flex items-center justify-between">
          <CardTitle>Yeni Rapor — Adım {step}/3</CardTitle>
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Kapat"
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
              {step === 1 ? "İptal" : "Geri"}
            </Button>
            {step === 1 && (
              <Button type="button" onClick={() => setStep(2)}>
                Devam <ArrowRight className="size-4" aria-hidden />
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
                Önizleme
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
                Üret
              </Button>
            )}
          </div>

          <Badge variant="outline" className="text-xs font-normal">
            ⓘ Hard limit: 90 gün, 50.000 satır.
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
  return (
    <div className="space-y-5">
      <div>
        <Label className="text-xs">Rapor Tipi</Label>
        <div className="mt-2 space-y-2">
          {(["comprehensive", "reviews_only", "tickets_only"] as ReportType[]).map(
            (t) => (
              <label
                key={t}
                className="flex cursor-pointer items-center gap-2 text-sm"
              >
                <input
                  type="radio"
                  name="report-type"
                  checked={reportType === t}
                  onChange={() => setReportType(t)}
                />
                {TYPE_LABELS[t]}
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
  return (
    <div>
      <Label className="text-xs">Tarih Aralığı</Label>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => quickRange("this-month")}
        >
          Bu ay
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => quickRange("last-month")}
        >
          Geçen ay
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => quickRange("this-quarter")}
        >
          Bu çeyrek
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
          Aralık: {dayDiff} gün
          {overLimit && " — 90 gün limitini aşıyor."}
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
  return (
    <div className="bg-muted/30 space-y-3 rounded-md border p-4 text-sm">
      <p className="font-medium">Önizleme</p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <dt className="text-muted-foreground">Tahmini satır:</dt>
        <dd className="tabular-nums">{estimate.row_count_estimate.toLocaleString("tr-TR")}</dd>
        <dt className="text-muted-foreground">Tahmini süre:</dt>
        <dd>~{estimate.estimated_seconds} saniye</dd>
        <dt className="text-muted-foreground">Tip:</dt>
        <dd>{TYPE_LABELS[reportType]}</dd>
        <dt className="text-muted-foreground">Format:</dt>
        <dd>{format === "xlsx" ? "Excel (.xlsx)" : "CSV (.zip)"}</dd>
        {dateFrom && dateTo && (
          <>
            <dt className="text-muted-foreground">Tarih aralığı:</dt>
            <dd>
              {dateFrom} – {dateTo}
            </dd>
          </>
        )}
        {estimate.review_rows > 0 && (
          <>
            <dt className="text-muted-foreground">Analiz satırı:</dt>
            <dd className="tabular-nums">{estimate.review_rows.toLocaleString("tr-TR")}</dd>
          </>
        )}
        {estimate.ticket_rows > 0 && (
          <>
            <dt className="text-muted-foreground">Bilet satırı:</dt>
            <dd className="tabular-nums">{estimate.ticket_rows.toLocaleString("tr-TR")}</dd>
          </>
        )}
      </dl>
    </div>
  );
}
