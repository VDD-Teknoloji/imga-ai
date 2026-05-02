"use client";

import {
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
  useGenerateReport,
  useReportJob,
  useReports,
} from "@/hooks/use-reports";
import { ApiError } from "@/lib/api-client";
import type {
  GenerateReportRequest,
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
  // Direct anchor click with auth header injected via fetch; falls back
  // to opening the URL if fetch fails (browser will surface the 401).
  const path = `/tenants/me/reports/${reportId}/download`;
  fetch(`${API_BASE}${path}`, {
    headers: {
      Authorization: `Bearer ${localStorage.getItem("imga.access_token") ?? ""}`,
    },
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
// New Report modal (3 steps)
// --------------------------------------------------------------------------

function NewReportModal({
  onClose,
  onQueued,
}: {
  onClose: () => void;
  onQueued: (id: string) => void;
}) {
  const [reportType, setReportType] = useState<ReportType>("comprehensive");
  const [format, setFormat] = useState<ReportFormat>("xlsx");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");

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

  function handleSubmit() {
    const body: GenerateReportRequest = {
      report_type: reportType,
      format,
      filters: {
        date_from: dateFrom ? new Date(dateFrom).toISOString() : undefined,
        date_to: dateTo
          ? new Date(`${dateTo}T23:59:59`).toISOString()
          : undefined,
      },
    };
    generate.mutate(body, {
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
          <CardTitle>Yeni Rapor</CardTitle>
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
                onChange={(e) => setDateFrom(e.target.value)}
                className="border-input bg-background rounded-md border px-3 py-2 text-sm"
              />
              <input
                type="date"
                value={dateTo}
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

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" type="button" onClick={onClose}>
              İptal
            </Button>
            <Button
              type="button"
              onClick={handleSubmit}
              disabled={overLimit || generate.isPending}
            >
              {generate.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Plus className="size-4" />
              )}
              Üret
            </Button>
          </div>

          <Badge variant="outline" className="text-xs font-normal">
            ⓘ Hard limit: 90 gün, 50.000 satır.
          </Badge>
        </CardContent>
      </Card>
    </div>
  );
}
