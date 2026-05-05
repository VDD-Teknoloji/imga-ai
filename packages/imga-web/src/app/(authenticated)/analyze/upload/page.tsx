"use client";

import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ChevronLeft,
  FileSpreadsheet,
  Loader2,
  Upload,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import { toast } from "sonner";

import { ColumnMappingPreview } from "@/components/analyze/column-mapping-preview";
import { PiiWarningBanner } from "@/components/analyze/pii-warning-banner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  useBatchJob,
  useBatchUploadMutation,
  useCancelBatchJobMutation,
} from "@/hooks/use-batch-uploads";
import { useSmartPreview } from "@/hooks/use-smart-preview";
import { ApiError } from "@/lib/api-client";
import type {
  BatchJob,
  SmartFieldName,
  SmartPreviewResponse,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type Step = 1 | 2 | 3 | 4;

const ACCEPTED_EXTENSIONS = [".csv", ".xlsx"];
const MAX_FILE_BYTES = 50 * 1024 * 1024;

/**
 * Sprint 8.3.1 — multi-step batch upload page.
 *
 *   1. Drag & drop file
 *   2. Column mapping + auto-create toggle
 *   3. Progress polling (3s)
 *   4. Completion summary + CTA to /reviews?batch_job_id=X
 */
export default function BatchUploadPage() {
  const [step, setStep] = useState<Step>(1);
  const [file, setFile] = useState<File | null>(null);
  const [textColumn, setTextColumn] = useState("text");
  const [sourceColumn, setSourceColumn] = useState("");
  const [autoCreateTickets, setAutoCreateTickets] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  // Sprint 8.3.8 — preview state. ``overrides`` lets the user
  // change a column's detected field via the dropdown; ``preview``
  // is the detector verdict; ``piiConsented`` gates the submit
  // button when the file carries PII columns (currently only
  // customer_name).
  const [preview, setPreview] = useState<SmartPreviewResponse | null>(null);
  const [overrides, setOverrides] = useState<
    Record<string, SmartFieldName | undefined>
  >({});
  const [piiConsented, setPiiConsented] = useState(false);

  const upload = useBatchUploadMutation();
  const cancel = useCancelBatchJobMutation();
  const job = useBatchJob(activeJobId);
  const previewMutation = useSmartPreview();

  // Auto-advance to step 4 when the polled job hits a terminal status.
  // Mirror of an async result onto sync UI state — the standard
  // exception to react-hooks/set-state-in-effect: there's no event to
  // hang this on, the transition is driven by the polled query
  // settling. Intentional, reviewed.
  useEffect(() => {
    if (!job.data) return;
    const terminal = ["completed", "failed", "cancelled"].includes(job.data.status);
    if (terminal && step === 3) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setStep(4);
    }
  }, [job.data, step]);

  function reset() {
    setFile(null);
    setTextColumn("text");
    setSourceColumn("");
    setAutoCreateTickets(false);
    setActiveJobId(null);
    setPreview(null);
    setOverrides({});
    setPiiConsented(false);
    setStep(1);
  }

  function handleFilePicked(picked: File | null) {
    setFile(picked);
    setPreview(null);
    setOverrides({});
    setPiiConsented(false);
    if (!picked) return;
    setStep(2);
    // Fire detection — best-effort. On failure the user still sees
    // the manual text_column input below.
    previewMutation.mutate(picked, {
      onSuccess: (data) => {
        setPreview(data);
        // Auto-set text_column from detector verdict + auto-set
        // source_column if a customer_id column was detected.
        const reviewText = data.detected.find(
          (d) => d.field_name === "review_text",
        );
        if (reviewText) setTextColumn(reviewText.column_name);
        const customerId = data.detected.find(
          (d) => d.field_name === "customer_id",
        );
        if (customerId) setSourceColumn(customerId.column_name);
      },
      onError: (err) => {
        if (err instanceof ApiError) {
          toast.error("Önizleme alınamadı: " + err.detail);
        } else {
          toast.error("Önizleme alınamadı.");
        }
      },
    });
  }

  return (
    <main className="mx-auto w-full max-w-3xl space-y-6 px-4 py-8">
      <header className="space-y-2">
        <Link
          href="/analyze"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
        >
          <ChevronLeft className="size-4" /> Manuel Analiz
        </Link>
        <h1 className="text-2xl font-semibold">Toplu Yükleme</h1>
        <p className="text-muted-foreground text-sm">
          CSV ya da XLSX yükleyin; metinler arka planda analiz edilir, sonuç
          /reviews sayfasında görünür.
        </p>
      </header>

      <StepIndicator step={step} />

      {step === 1 && (
        <Step1FilePick file={file} setFile={handleFilePicked} />
      )}

      {step === 2 && file && (
        <Step2ColumnMapping
          file={file}
          textColumn={textColumn}
          sourceColumn={sourceColumn}
          autoCreateTickets={autoCreateTickets}
          setTextColumn={setTextColumn}
          setSourceColumn={setSourceColumn}
          setAutoCreateTickets={setAutoCreateTickets}
          preview={preview}
          previewLoading={previewMutation.isPending}
          overrides={overrides}
          onOverrideChange={(column, next) =>
            setOverrides((prev) => ({ ...prev, [column]: next }))
          }
          piiConsented={piiConsented}
          onPiiConsentChange={setPiiConsented}
          onBack={() => setStep(1)}
          onSubmit={() => {
            upload.mutate(
              {
                file,
                textColumn: textColumn.trim() || "text",
                sourceColumn: sourceColumn.trim() || null,
                autoCreateTickets,
              },
              {
                onSuccess: (data: BatchJob) => {
                  setActiveJobId(data.job_id);
                  setStep(3);
                },
                onError: (err) => {
                  if (err instanceof ApiError) {
                    toast.error(err.detail);
                  } else {
                    toast.error("Yükleme sırasında hata oluştu.");
                  }
                },
              },
            );
          }}
          submitting={upload.isPending}
        />
      )}

      {step === 3 && activeJobId && (
        <Step3Progress
          job={job.data ?? null}
          onCancel={() => {
            if (!activeJobId) return;
            cancel.mutate(activeJobId, {
              onError: (err) =>
                toast.error(
                  err instanceof ApiError ? err.detail : "İptal başarısız.",
                ),
            });
          }}
        />
      )}

      {step === 4 && job.data && (
        <Step4Summary job={job.data} onReset={reset} />
      )}
    </main>
  );
}

// --------------------------------------------------------------------------
// Steps
// --------------------------------------------------------------------------

function StepIndicator({ step }: { step: Step }) {
  const labels = ["Dosya", "Sütunlar", "İlerleme", "Tamamlandı"];
  return (
    <ol className="flex items-center gap-2 text-sm">
      {labels.map((label, idx) => {
        const n = (idx + 1) as Step;
        const active = n === step;
        const done = n < step;
        return (
          <li key={label} className="flex items-center gap-2">
            <span
              className={cn(
                "flex size-6 items-center justify-center rounded-full text-xs font-medium",
                active && "bg-primary text-primary-foreground",
                done && "bg-emerald-100 text-emerald-700",
                !active && !done && "bg-muted text-muted-foreground",
              )}
            >
              {done ? <CheckCircle2 className="size-4" /> : n}
            </span>
            <span className={cn(active && "font-medium")}>{label}</span>
            {idx < labels.length - 1 && (
              <ArrowRight className="text-muted-foreground size-3.5" />
            )}
          </li>
        );
      })}
    </ol>
  );
}

function Step1FilePick({
  file,
  setFile,
}: {
  file: File | null;
  setFile: (f: File | null) => void;
}) {
  const [dragOver, setDragOver] = useState(false);

  function handle(f: File | null) {
    if (!f) return;
    const ext = "." + f.name.split(".").pop()?.toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(ext)) {
      toast.error("Sadece .csv veya .xlsx dosyaları kabul edilir.");
      return;
    }
    if (f.size > MAX_FILE_BYTES) {
      toast.error("Dosya 50 MB sınırını aşıyor.");
      return;
    }
    setFile(f);
  }

  function onDrop(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setDragOver(false);
    handle(e.dataTransfer.files?.[0] ?? null);
  }

  function onSelect(e: ChangeEvent<HTMLInputElement>) {
    handle(e.target.files?.[0] ?? null);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Adım 1 — Dosya Seç</CardTitle>
      </CardHeader>
      <CardContent>
        <label
          htmlFor="batch-file-input"
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className={cn(
            "border-muted-foreground/30 hover:border-primary flex cursor-pointer flex-col items-center gap-3 rounded-lg border-2 border-dashed p-12 text-center transition",
            dragOver && "border-primary bg-primary/5",
          )}
        >
          <FileSpreadsheet className="text-muted-foreground size-12" />
          <div>
            <p className="text-sm font-medium">
              Dosyayı buraya bırakın veya tıklayarak seçin
            </p>
            <p className="text-muted-foreground text-xs">
              CSV, XLSX — en fazla 50 MB, en fazla 10.000 satır
            </p>
          </div>
          {file && (
            <p className="text-foreground text-sm">{file.name}</p>
          )}
          <input
            id="batch-file-input"
            type="file"
            accept={ACCEPTED_EXTENSIONS.join(",")}
            onChange={onSelect}
            className="hidden"
          />
        </label>
      </CardContent>
    </Card>
  );
}

function Step2ColumnMapping({
  file,
  textColumn,
  sourceColumn,
  autoCreateTickets,
  setTextColumn,
  setSourceColumn,
  setAutoCreateTickets,
  preview,
  previewLoading,
  overrides,
  onOverrideChange,
  piiConsented,
  onPiiConsentChange,
  onBack,
  onSubmit,
  submitting,
}: {
  file: File;
  textColumn: string;
  sourceColumn: string;
  autoCreateTickets: boolean;
  setTextColumn: (v: string) => void;
  setSourceColumn: (v: string) => void;
  setAutoCreateTickets: (v: boolean) => void;
  preview: SmartPreviewResponse | null;
  previewLoading: boolean;
  overrides: Record<string, SmartFieldName | undefined>;
  onOverrideChange: (column: string, next: SmartFieldName | undefined) => void;
  piiConsented: boolean;
  onPiiConsentChange: (next: boolean) => void;
  onBack: () => void;
  onSubmit: () => void;
  submitting: boolean;
}) {
  // Sprint 8.3.8 — derive the canonical text column from the
  // detector verdict + the user's overrides. The textColumn local
  // state stays the source of truth for the upload mutation; the
  // preview just nudges it. If the user clears overrides AND the
  // detector finds review_text, that column becomes the value.
  const derivedTextColumn = useMemo(() => {
    if (!preview) return null;
    for (const col of preview.detected) {
      const override = overrides[col.column_name];
      const effective = override ?? col.field_name;
      if (effective === "review_text") return col.column_name;
    }
    return null;
  }, [preview, overrides]);

  // Auto-sync derivedTextColumn → textColumn while the user hasn't
  // typed manually. Keep the existing input as the override path so
  // a tenant whose CSV uses an unusual header can still type it.
  useEffect(() => {
    if (derivedTextColumn && derivedTextColumn !== textColumn) {
      setTextColumn(derivedTextColumn);
    }
  }, [derivedTextColumn, textColumn, setTextColumn]);

  const piiBlocked = preview !== null && preview.pii_warnings.length > 0 && !piiConsented;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Adım 2 — Sütun Eşleştirme</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <p className="text-muted-foreground text-sm">
          <span className="font-medium text-foreground">{file.name}</span>{" "}
          ({(file.size / 1024 / 1024).toFixed(1)} MB)
          {preview && (
            <>
              <span className="text-muted-foreground"> · </span>
              {preview.row_count} satır
            </>
          )}
        </p>

        {previewLoading ? (
          <div className="bg-muted/30 flex items-center gap-2 rounded-md border p-4 text-sm">
            <Loader2 className="size-4 animate-spin" /> Sütunlar analiz ediliyor…
          </div>
        ) : preview ? (
          <>
            <PiiWarningBanner
              preview={preview}
              consented={piiConsented}
              onConsentChange={onPiiConsentChange}
            />
            <ColumnMappingPreview
              preview={preview}
              overrides={overrides}
              onOverrideChange={onOverrideChange}
            />
          </>
        ) : (
          <div className="bg-muted/30 rounded-md border p-3 text-xs text-muted-foreground">
            Otomatik tespit alınamadı; sütunları aşağıdan elle girebilirsiniz.
          </div>
        )}

        <div className="space-y-3">
          <Label htmlFor="text-column">Metin sütunu</Label>
          <input
            id="text-column"
            value={textColumn}
            onChange={(e) => setTextColumn(e.target.value)}
            placeholder="text / yorum"
            className="border-input bg-background w-full rounded-md border px-3 py-2 text-sm"
          />
          <p className="text-muted-foreground text-xs">
            Analiz edilecek metni içeren sütunun başlığı.
            {derivedTextColumn && (
              <>
                {" "}Otomatik tespit:{" "}
                <code className="font-mono">{derivedTextColumn}</code>
              </>
            )}
          </p>
        </div>

        <div className="space-y-3">
          <Label htmlFor="source-column">Kaynak sütunu (opsiyonel)</Label>
          <input
            id="source-column"
            value={sourceColumn}
            onChange={(e) => setSourceColumn(e.target.value)}
            placeholder="kaynak / source"
            className="border-input bg-background w-full rounded-md border px-3 py-2 text-sm"
          />
        </div>

        <label className="flex cursor-pointer items-start gap-3 rounded-md border p-4">
          <input
            type="checkbox"
            checked={autoCreateTickets}
            onChange={(e) => setAutoCreateTickets(e.target.checked)}
            className="mt-1"
          />
          <span className="text-sm">
            <span className="font-medium">Otomatik bilet aç</span>
            <span className="text-muted-foreground mt-1 block text-xs">
              Tenant&apos;ın automation_mode ayarına göre eşik tutturan satırlar
              için otomatik ticket yaratılır. Kapalıysa hiçbir satır ticket
              açmaz; tüm analizler /reviews sayfasında listelenir.
            </span>
          </span>
        </label>

        <div className="flex justify-between gap-2">
          <Button variant="outline" type="button" onClick={onBack}>
            Geri
          </Button>
          <Button
            type="button"
            onClick={onSubmit}
            disabled={submitting || piiBlocked}
            title={piiBlocked ? "Önce PII onayı verin" : undefined}
          >
            {submitting ? (
              <>
                <Loader2 className="size-4 animate-spin" /> Yükleniyor…
              </>
            ) : (
              <>
                <Upload className="size-4" /> Yüklemeyi Başlat
              </>
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function Step3Progress({
  job,
  onCancel,
}: {
  job: BatchJob | null;
  onCancel: () => void;
}) {
  const percent = useMemo(() => {
    if (!job) return 0;
    return Math.min(
      100,
      Math.round((job.processed_rows / Math.max(1, job.total_rows)) * 100),
    );
  }, [job]);

  if (!job) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 p-6">
          <Loader2 className="size-5 animate-spin" /> Job bilgisi yükleniyor…
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Adım 3 — İlerleme</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm">
          <span className="font-medium">{job.file_name}</span>
          <span className="text-muted-foreground"> · {job.total_rows} satır</span>
        </p>

        <div className="bg-muted h-2 w-full overflow-hidden rounded">
          <div
            className="bg-primary h-full transition-all"
            style={{ width: `${percent}%` }}
          />
        </div>
        <p className="text-muted-foreground text-xs">
          {job.processed_rows} / {job.total_rows} ({percent}%)
        </p>

        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Stat label="Başarılı" value={job.succeeded_rows} />
          <Stat label="Hatalı" value={job.failed_rows} tone="danger" />
          <Stat label="Tekrar" value={job.duplicates_skipped} />
          <Stat label="Bilet" value={job.tickets_created} tone="success" />
        </dl>

        {job.estimated_seconds !== null && job.estimated_seconds > 0 && (
          <p className="text-muted-foreground text-xs">
            Kalan tahmini süre: ~{Math.ceil(job.estimated_seconds / 60)} dakika
          </p>
        )}

        {(job.status === "queued" || job.status === "processing") && (
          <Button variant="outline" type="button" onClick={onCancel}>
            <XCircle className="size-4" /> İptal Et
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function Step4Summary({ job, onReset }: { job: BatchJob; onReset: () => void }) {
  const ok = job.status === "completed";
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {ok ? (
            <CheckCircle2 className="size-5 text-emerald-600" />
          ) : (
            <AlertCircle className="size-5 text-amber-600" />
          )}
          Adım 4 — {ok ? "Tamamlandı" : statusLabel(job.status)}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Stat label="İşlenen" value={job.processed_rows} />
          <Stat label="Başarılı" value={job.succeeded_rows} tone="success" />
          <Stat label="Hatalı" value={job.failed_rows} tone="danger" />
          <Stat label="Bilet" value={job.tickets_created} />
        </dl>
        {job.error_summary.length > 0 && (
          <details className="rounded border p-3 text-sm">
            <summary className="cursor-pointer">
              Hata özeti ({job.error_summary.length})
            </summary>
            <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto text-xs">
              {job.error_summary.map((entry, idx) => (
                <li key={idx} className="text-muted-foreground">
                  {entry.row !== null ? `Satır ${entry.row}:` : "Genel:"} {entry.error}
                </li>
              ))}
            </ul>
          </details>
        )}
        <div className="flex flex-wrap gap-2">
          <Button render={<Link href={`/reviews?batch_job_id=${job.job_id}`} />}>
            Bu Batch&apos;in Analizlerini Gör <ArrowRight className="size-4" />
          </Button>
          <Button variant="outline" type="button" onClick={onReset}>
            Yeni Yükleme
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "success" | "danger";
}) {
  return (
    <div className="bg-muted/30 rounded-md border p-3">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd
        className={cn(
          "text-lg font-semibold",
          tone === "success" && "text-emerald-700",
          tone === "danger" && value > 0 && "text-red-600",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

function statusLabel(s: BatchJob["status"]): string {
  switch (s) {
    case "completed":
      return "Tamamlandı";
    case "failed":
      return "Başarısız";
    case "cancelled":
      return "İptal edildi";
    case "processing":
      return "İşleniyor";
    case "queued":
      return "Sıraya alındı";
  }
}
