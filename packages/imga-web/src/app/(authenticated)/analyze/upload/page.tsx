"use client";

import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ChevronLeft,
  Download,
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
import { RequireRole } from "@/components/auth/require-role";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  useActiveBatchJob,
  useBatchProgressStream,
  useBatchUploadMutation,
  useCancelBatchJobMutation,
  type LiveBatchJob,
} from "@/hooks/use-batch-uploads";
import { useSmartPreview } from "@/hooks/use-smart-preview";
import { useSmoothProgress } from "@/hooks/use-smooth-progress";
import { ApiError, apiRawFetch } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";
import type {
  BatchJob,
  SmartFieldName,
  SmartPreviewResponse,
  ValidationReport,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type Step = 1 | 2 | 3 | 4;

const ACCEPTED_EXTENSIONS = [".csv", ".xlsx"];
const MAX_FILE_BYTES = 50 * 1024 * 1024;

export default function BatchUploadPage() {
  return (
    <RequireRole level="write">
      <BatchUploadPageInner />
    </RequireRole>
  );
}

/**
 * Sprint 8.3.1 — multi-step batch upload page.
 *
 *   1. Drag & drop file
 *   2. Column mapping + auto-create toggle
 *   3. Progress polling (3s)
 *   4. Completion summary + CTA to /reviews?batch_job_id=X
 */
function BatchUploadPageInner() {
  const { t } = useTranslation();
  const [step, setStep] = useState<Step>(1);
  const [file, setFile] = useState<File | null>(null);
  // Sprint 13 — manuel "Metin/Kaynak sütunu" inputları kaldırıldı.
  // sourceColumn yalnız preview'dan sessizce türetilir; text kolonu
  // sütun kartlarındaki override'lardan (derivedTextColumn) gelir,
  // hiçbiri bulunamazsa backend REVIEW_TEXT'i kendisi çözer.
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

  // Sprint 8.3.8/13 — detector verdict + kullanıcı override'ından
  // kanonik text kolonu. null ise upload isteğine text_column hiç
  // yazılmaz; backend smart detector ile kendisi çözer.
  const derivedTextColumn = useMemo(() => {
    if (!preview) return null;
    for (const col of preview.detected) {
      const effective = overrides[col.column_name] ?? col.field_name;
      if (effective === "review_text") return col.column_name;
    }
    return null;
  }, [preview, overrides]);

  // 2026-08-20 (migration 0044) — derivedTextColumn ile BİREBİR AYNI
  // desen: smart parser'ın "date" önerisi ön-seçili gelir, kullanıcı
  // herhangi bir kolonun dropdown'ını "Tarih"e çevirerek override
  // edebilir. Hiçbir kolon "date"e eşlenmemişse ("tarih yok") null
  // kalır — upload isteğine date_column hiç yazılmaz, backend
  // otomatik tespite düşer.
  const derivedDateColumn = useMemo(() => {
    if (!preview) return null;
    for (const col of preview.detected) {
      const effective = overrides[col.column_name] ?? col.field_name;
      if (effective === "date") return col.column_name;
    }
    return null;
  }, [preview, overrides]);

  const upload = useBatchUploadMutation();
  const cancel = useCancelBatchJobMutation();
  // Sprint 9.0.5-B A — was useBatchJob(activeJobId) (3s polling);
  // SSE stream gives sub-second progress updates while the worker
  // commits chunks, plus a clean terminal event so we don't keep
  // hitting the API after the job finishes.
  const job = useBatchProgressStream(activeJobId);
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

  // Sprint 11.1 — yeniden bağlanma. Kullanıcı sayfadan ayrılıp
  // dönünce iş sunucuda koşmaya devam ediyordu ama UI step 1'e
  // sıfırlandığı için "iptal oldu" sanılıyordu. Mount'ta devam eden
  // iş bulunursa doğrudan ilerleme adımına bağlan. Aynı async-mirror
  // istisnası: tetikleyici, sorgunun sonuçlanması.
  const activeJob = useActiveBatchJob();
  useEffect(() => {
    if (step !== 1 || activeJobId !== null) return;
    const running = activeJob.data;
    if (running) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActiveJobId(running.job_id);
      setStep(3);
      toast.info(
        t("analyze.upload.reconnected", { file: running.file_name }),
      );
    }
  }, [activeJob.data, step, activeJobId, t]);

  function reset() {
    setFile(null);
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
    // Fire detection — best-effort. On failure the upload still
    // works; the backend resolves REVIEW_TEXT itself.
    previewMutation.mutate(picked, {
      onSuccess: (data) => {
        setPreview(data);
        // source_column'u sessizce türet: customer_id tespit edilen
        // kolon varsa onu kullan (eski manuel inputun auto-fill'i).
        const customerId = data.detected.find(
          (d) => d.field_name === "customer_id",
        );
        if (customerId) setSourceColumn(customerId.column_name);
      },
      onError: (err) => {
        if (err instanceof ApiError) {
          toast.error(t("analyze.upload.previewFailedDetail", { detail: err.detail }));
        } else {
          toast.error(t("analyze.upload.previewFailed"));
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
          <ChevronLeft className="size-4" /> {t("analyze.upload.backManual")}
        </Link>
        <h1 className="text-2xl font-semibold">{t("analyze.upload.title")}</h1>
        <p className="text-muted-foreground text-sm">
          {t("analyze.upload.subtitle")}
        </p>
      </header>

      <StepIndicator step={step} />

      {step === 1 && (
        <>
          <TemplateBanner />
          <Step1FilePick file={file} setFile={handleFilePicked} />
        </>
      )}

      {step === 2 && file && (
        <Step2ColumnMapping
          file={file}
          autoCreateTickets={autoCreateTickets}
          setAutoCreateTickets={setAutoCreateTickets}
          preview={preview}
          previewLoading={previewMutation.isPending}
          overrides={overrides}
          onOverrideChange={(column, next) =>
            setOverrides((prev) => ({ ...prev, [column]: next }))
          }
          hasDateColumn={derivedDateColumn !== null}
          piiConsented={piiConsented}
          onPiiConsentChange={setPiiConsented}
          onBack={() => setStep(1)}
          onSubmit={() => {
            upload.mutate(
              {
                file,
                textColumn: derivedTextColumn,
                sourceColumn: sourceColumn.trim() || null,
                dateColumn: derivedDateColumn,
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
                    toast.error(t("analyze.upload.uploadError"));
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
                  err instanceof ApiError ? err.detail : t("analyze.upload.cancelFailed"),
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
  const { t } = useTranslation();
  const labels = [
    t("analyze.upload.step.file"),
    t("analyze.upload.step.columns"),
    t("analyze.upload.step.progress"),
    t("analyze.upload.step.done"),
  ];
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

function TemplateBanner() {
  // Sprint 9.8 — OTAN feedback: kullanıcı bir formata zorlanmalı,
  // şablon indirilebilir olmalı. Banner Step 1 üstünde duruyor —
  // ilk işi şablonu indirmek olsun. İndirme isteği server'dan
  // bytes alıp blob → <a download> ile dosyayı kullanıcıya
  // veriyor (cookie credentials:'include' lazım, bu yüzden plain
  // <a href> yerine fetch). Sprint 13 (HATA-04) — apiRawFetch:
  // access cookie süresi dolmuşsa indirme de refresh+replay'den geçer.
  const { t } = useTranslation();
  const [downloading, setDownloading] = useState(false);

  async function handleDownload() {
    setDownloading(true);
    try {
      const res = await apiRawFetch("/tenants/me/analyze/batch/template");
      if (!res.ok) {
        toast.error(t("analyze.upload.template.downloadFailedRetry"));
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "imga-toplu-yukleme-sablonu.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      toast.error(t("analyze.upload.template.downloadFailed"));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <Card className="border-primary/30 bg-primary/5">
      <CardContent className="flex flex-wrap items-center gap-4 p-4">
        <div className="bg-primary/15 text-primary flex size-10 shrink-0 items-center justify-center rounded-xl">
          <FileSpreadsheet className="size-5" aria-hidden />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold">
            {t("analyze.upload.template.heading")}
          </p>
          <p className="text-muted-foreground text-xs leading-relaxed">
            {t("analyze.upload.template.bodyBefore")}<strong>yorum</strong>{t("analyze.upload.template.bodyAfter")}
          </p>
          <p className="text-muted-foreground text-xs leading-relaxed">
            {t("analyze.upload.template.dateHint")}
          </p>
        </div>
        <Button
          variant="outline"
          onClick={handleDownload}
          disabled={downloading}
          className="gap-2"
        >
          {downloading ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <Download className="size-4" aria-hidden />
          )}
          {t("analyze.upload.template.download")}
        </Button>
      </CardContent>
    </Card>
  );
}

function Step1FilePick({
  file,
  setFile,
}: {
  file: File | null;
  setFile: (f: File | null) => void;
}) {
  const { t } = useTranslation();
  const [dragOver, setDragOver] = useState(false);

  function handle(f: File | null) {
    if (!f) return;
    const ext = "." + f.name.split(".").pop()?.toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(ext)) {
      toast.error(t("analyze.upload.onlyCsvXlsx"));
      return;
    }
    if (f.size > MAX_FILE_BYTES) {
      toast.error(t("analyze.upload.fileTooLarge"));
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
        <CardTitle>{t("analyze.upload.step1Title")}</CardTitle>
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
              {t("analyze.upload.dropzone")}
            </p>
            <p className="text-muted-foreground text-xs">
              {t("analyze.upload.dropzoneHint")}
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
  autoCreateTickets,
  setAutoCreateTickets,
  preview,
  previewLoading,
  overrides,
  onOverrideChange,
  hasDateColumn,
  piiConsented,
  onPiiConsentChange,
  onBack,
  onSubmit,
  submitting,
}: {
  file: File;
  autoCreateTickets: boolean;
  setAutoCreateTickets: (v: boolean) => void;
  preview: SmartPreviewResponse | null;
  previewLoading: boolean;
  overrides: Record<string, SmartFieldName | undefined>;
  onOverrideChange: (column: string, next: SmartFieldName | undefined) => void;
  /** 2026-08-20 — bir kolon şu an "Tarih"e eşli mi (auto-detect ya da
   *  override ile). ValidationReportPanel'in no_date_column uyarısını
   *  yerel olarak bastırmak için — sunucu önizleme anında kullanıcının
   *  SONRADAN yapacağı seçimden habersizdir. */
  hasDateColumn: boolean;
  piiConsented: boolean;
  onPiiConsentChange: (next: boolean) => void;
  onBack: () => void;
  onSubmit: () => void;
  submitting: boolean;
}) {
  const { t } = useTranslation();
  const piiBlocked = preview !== null && preview.pii_warnings.length > 0 && !piiConsented;
  // Sprint 12 — engelleyici doğrulama hatası varsa (zorunlu kolon yok,
  // dosya boş, satır limiti) yükleme açılmaz; kullanıcı önce düzeltir.
  const validationBlocked = preview !== null && !preview.validation.ok;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("analyze.upload.step2Title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <p className="text-muted-foreground text-sm">
          <span className="font-medium text-foreground">{file.name}</span>{" "}
          ({(file.size / 1024 / 1024).toFixed(1)} MB)
          {preview && (
            <>
              <span className="text-muted-foreground"> · </span>
              {t("analyze.upload.rowCount", { n: preview.row_count })}
            </>
          )}
        </p>

        {previewLoading ? (
          <div className="bg-muted/30 flex items-center gap-2 rounded-md border p-4 text-sm">
            <Loader2 className="size-4 animate-spin" /> {t("analyze.upload.analyzingColumns")}
          </div>
        ) : preview ? (
          <>
            <ValidationReportPanel
              report={preview.validation}
              hasDateColumn={hasDateColumn}
            />
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
            {t("analyze.upload.noAutoDetect")}
          </div>
        )}

        <label className="flex cursor-pointer items-start gap-3 rounded-md border p-4">
          <input
            type="checkbox"
            checked={autoCreateTickets}
            onChange={(e) => setAutoCreateTickets(e.target.checked)}
            className="mt-1"
          />
          <span className="text-sm">
            <span className="font-medium">{t("analyze.upload.autoCreateTitle")}</span>
            <span className="text-muted-foreground mt-1 block text-xs">
              {t("analyze.upload.autoCreateHelp")}
            </span>
          </span>
        </label>

        <div className="flex justify-between gap-2">
          <Button variant="outline" type="button" onClick={onBack}>
            {t("analyze.upload.back")}
          </Button>
          <Button
            type="button"
            onClick={onSubmit}
            disabled={submitting || piiBlocked || validationBlocked}
            title={
              validationBlocked
                ? t("analyze.upload.fixErrorsTitle")
                : piiBlocked
                  ? t("analyze.upload.piiConsentFirst")
                  : undefined
            }
          >
            {submitting ? (
              <>
                <Loader2 className="size-4 animate-spin" /> {t("analyze.upload.uploading")}
              </>
            ) : (
              <>
                <Upload className="size-4" /> {t("analyze.upload.startUpload")}
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
  job: LiveBatchJob | null;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const realPercent = useMemo(() => {
    if (!job) return 0;
    return Math.min(
      100,
      (job.processed_rows / Math.max(1, job.total_rows)) * 100,
    );
  }, [job]);
  const running = job?.status === "queued" || job?.status === "processing";
  // Sprint 13 — gerçek kareler chunk başına gelir (200 satırda bir);
  // aradaki boşlukta bar tahmini hızla akmaya devam eder.
  const percent = useSmoothProgress(
    realPercent,
    job?.eta_seconds ?? null,
    running === true,
  );

  if (!job) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 p-6">
          <Loader2 className="size-5 animate-spin" /> {t("analyze.upload.loadingJob")}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("analyze.upload.step3Title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm">
          <span className="font-medium">{job.file_name}</span>
          <span className="text-muted-foreground"> · {t("analyze.upload.rowCount", { n: job.total_rows })}</span>
        </p>

        <div className="bg-muted h-2 w-full overflow-hidden rounded">
          <div
            className="bg-primary h-full transition-[width] duration-200 ease-linear"
            style={{ width: `${percent}%` }}
          />
        </div>
        <p className="text-muted-foreground text-xs">
          {job.processed_rows} / {job.total_rows} ({Math.round(percent)}%)
        </p>

        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Stat label={t("analyze.upload.stat.succeeded")} value={job.succeeded_rows} />
          <Stat label={t("analyze.upload.stat.failed")} value={job.failed_rows} tone="danger" />
          <Stat label={t("analyze.upload.stat.duplicates")} value={job.duplicates_skipped} />
          <Stat label={t("analyze.upload.stat.tickets")} value={job.tickets_created} tone="success" />
        </dl>

        {(() => {
          // Canlı SSE ETA'sı varsa onu göster — estimated_seconds
          // yükleme anında bir kez hesaplanan kaba heuristik.
          const eta = job.eta_seconds ?? job.estimated_seconds;
          return eta !== null && eta !== undefined && eta > 0 ? (
            <p className="text-muted-foreground text-xs">
              {t("analyze.upload.estimatedTime", { n: Math.max(1, Math.ceil(eta / 60)) })}
            </p>
          ) : null;
        })()}

        {(job.status === "queued" || job.status === "processing") && (
          <Button variant="outline" type="button" onClick={onCancel}>
            <XCircle className="size-4" /> {t("analyze.upload.cancel")}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function Step4Summary({ job, onReset }: { job: LiveBatchJob; onReset: () => void }) {
  const { t } = useTranslation();
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
          {t("analyze.upload.step4Prefix")}
          {ok
            ? t("analyze.upload.status.completed")
            : t(statusLabelKey(job.status))}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Stat label={t("analyze.upload.stat.processed")} value={job.processed_rows} />
          <Stat label={t("analyze.upload.stat.succeeded")} value={job.succeeded_rows} tone="success" />
          <Stat label={t("analyze.upload.stat.failed")} value={job.failed_rows} tone="danger" />
          <Stat label={t("analyze.upload.stat.tickets")} value={job.tickets_created} />
        </dl>
        <QualityCard job={job} />
        {job.error_summary.length > 0 && (
          <details className="rounded border p-3 text-sm">
            <summary className="cursor-pointer">
              {t("analyze.upload.errorSummary", { n: job.error_summary.length })}
            </summary>
            <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto text-xs">
              {job.error_summary.map((entry, idx) => (
                <li key={idx} className="text-muted-foreground">
                  {entry.row !== null
                    ? t("analyze.upload.rowPrefix", { n: entry.row })
                    : t("analyze.upload.general")}{" "}
                  {entry.error}
                </li>
              ))}
            </ul>
          </details>
        )}
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            {/* Ana sayfa ?batch_job_id paramını okuyup dashboard'u bu
                yüklemeye filtreler (dashboard ajanıyla sözleşme). */}
            <Button render={<Link href={`/?batch_job_id=${job.job_id}`} />}>
              {t("analyze.upload.viewAnalyses")} <ArrowRight className="size-4" />
            </Button>
            <Button variant="outline" type="button" onClick={onReset}>
              {t("analyze.upload.newUpload")}
            </Button>
          </div>
          <Link
            href={`/reviews?batch_job_id=${job.job_id}`}
            className="text-muted-foreground hover:text-foreground text-xs underline underline-offset-2"
          >
            {t("analyze.upload.openReviewList")}
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * 2026-08-18 (Dalga 3, WS2) — "Veri Kalitesi" kartı. Sayaçlar
 * succeeded_rows'un ALT KÜMESİdir (backend garantisi); "temiz" satır
 * sayısı bu yüzden succeeded_rows - (4 sayacın toplamı) ile hesaplanır.
 */
function QualityCard({ job }: { job: LiveBatchJob }) {
  const { t } = useTranslation();
  const duplicate = job.quality_duplicate_rows ?? 0;
  const empty = job.quality_empty_rows ?? 0;
  const informational = job.quality_informational_rows ?? 0;
  const meaningless = job.quality_meaningless_rows ?? 0;
  const flagged = duplicate + empty + informational + meaningless;
  const cleanValid = Math.max(0, job.succeeded_rows - flagged);

  return (
    <div className="space-y-3 rounded-2xl border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{t("analyze.upload.quality.title")}</h3>
        <span className="text-muted-foreground text-xs tabular-nums">
          {t("analyze.upload.quality.validCount", { n: cleanValid.toLocaleString("tr-TR") })}
        </span>
      </div>
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <Stat label={t("analyze.upload.quality.duplicate")} value={duplicate} />
        <Stat label={t("analyze.upload.quality.empty")} value={empty} />
        <Stat label={t("analyze.upload.quality.informational")} value={informational} />
        <Stat label={t("analyze.upload.quality.meaningless")} value={meaningless} />
      </dl>
    </div>
  );
}

/**
 * Sprint 12 — yüklemeden önce nokta-atışı doğrulama raporu.
 *
 *   * Engelleyici hata (zorunlu kolon yok / boş dosya / satır limiti):
 *     kırmızı panel + düzeltme ipucu; "Yüklemeyi Başlat" kilitli.
 *   * Yalnız uyarı (boş hücre): gri/soluk bilgi paneli, satır
 *     numaralarıyla; yükleme açılabilir, o satırlar atlanır.
 *   * Temiz: yeşil onay + analiz edilecek satır sayısı.
 *
 * Sprint 13 — code="duplicate" uyarıları tamamen gizlenir (kopyalar
 * zaten bir kez analiz edilir; kullanıcı bunu hata sanıyordu).
 * Sayaçlar ve yeşil-panel kararı filtrelenmiş listeden hesaplanır.
 *
 * 2026-08-20 — code="no_date_column" da koşullu gizlenir: sunucu bu
 * bulguyu ÖNİZLEME anında, kullanıcı henüz hiçbir kolonu "Tarih"e
 * eşlemeden üretir. Kullanıcı sonradan mapping dropdown'ından bir
 * kolonu "Tarih" yaparsa (``hasDateColumn``) bulgu artık geçersizdir
 * — sunucu bunu yeniden hesaplamaz, o yüzden burada yerel olarak
 * bastırılır.
 */
function ValidationReportPanel({
  report,
  hasDateColumn,
}: {
  report: ValidationReport;
  hasDateColumn: boolean;
}) {
  const { t } = useTranslation();
  const errors = report.issues.filter((i) => i.severity === "error");
  const warnings = report.issues.filter(
    (i) =>
      i.severity === "warning" &&
      i.code !== "duplicate" &&
      !(i.code === "no_date_column" && hasDateColumn),
  );
  // Satır-bazlı bulgular birebir sayılır; 50+ satırlık taşma tek
  // "…ve N daha" özet bulgusuna katlandığı için burada ancak
  // listelenen kadarı sayılabilir (report.warning_count kopyaları
  // da içerdiğinden kullanılamaz).
  const visibleWarningRows = warnings.filter((i) => i.row !== null).length;

  if (!report.ok) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-4 dark:border-red-900/60 dark:bg-red-950/30">
        <div className="flex items-start gap-2.5">
          <XCircle
            className="mt-0.5 size-5 shrink-0 text-red-600 dark:text-red-400"
            aria-hidden
          />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-red-800 dark:text-red-300">
              {t("analyze.upload.validation.cannotUpload")}
            </p>
            <ul className="mt-2 space-y-2.5">
              {errors.map((iss, idx) => (
                <li
                  key={idx}
                  className="text-sm leading-relaxed text-red-800/90 [overflow-wrap:anywhere] dark:text-red-200"
                >
                  {iss.message}
                  {iss.hint && (
                    <span className="mt-0.5 block text-xs text-red-700/70 dark:text-red-300/70">
                      {iss.hint}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    );
  }

  if (warnings.length === 0) {
    return (
      <div className="flex items-center gap-2.5 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900/60 dark:bg-emerald-950/30">
        <CheckCircle2
          className="size-5 shrink-0 text-emerald-600 dark:text-emerald-400"
          aria-hidden
        />
        <p className="text-sm text-emerald-800 dark:text-emerald-300">
          {t("analyze.upload.validation.okBefore")}
          <strong className="font-semibold tabular-nums">
            {report.valid_rows.toLocaleString("tr-TR")}
          </strong>
          {t("analyze.upload.validation.okAfter")}
        </p>
      </div>
    );
  }

  // Gri/soluk bilgi paneli — amber "uyarı" tonu kullanıcıya hata
  // varmış hissi veriyordu; atlanan satırlar engelleyici değil.
  return (
    <div className="bg-muted/50 rounded-2xl border p-4">
      <div className="flex items-start gap-2.5">
        <AlertCircle
          className="text-zinc-400 mt-0.5 size-5 shrink-0 dark:text-zinc-500"
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <p className="text-muted-foreground text-sm font-semibold">
            {t("analyze.upload.validation.warnSummary", {
              valid: report.valid_rows.toLocaleString("tr-TR"),
              warn: visibleWarningRows.toLocaleString("tr-TR"),
            })}
          </p>
          <ul className="mt-2 max-h-44 space-y-1.5 overflow-y-auto pr-1">
            {warnings.map((iss, idx) => (
              <li
                key={idx}
                className="text-muted-foreground text-xs leading-relaxed [overflow-wrap:anywhere]"
              >
                {iss.message}
              </li>
            ))}
          </ul>
          <p className="text-muted-foreground/70 mt-2 text-xs">
            {t("analyze.upload.validation.warnFooter")}
          </p>
        </div>
      </div>
    </div>
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

function statusLabelKey(s: BatchJob["status"]): string {
  switch (s) {
    case "completed":
      return "analyze.upload.status.completed";
    case "failed":
      return "analyze.upload.status.failed";
    case "cancelled":
      return "analyze.upload.status.cancelled";
    case "processing":
      return "analyze.upload.status.processing";
    case "queued":
      return "analyze.upload.status.queued";
  }
}
