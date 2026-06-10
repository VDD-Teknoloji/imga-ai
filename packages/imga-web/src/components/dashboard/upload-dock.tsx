"use client";

// Sprint 10.3 — Hızlı Yükleme rıhtımı.
//
// Ürün sahibi isteği: "ana sayfadaki toplu yükleme bölümü toplu
// yükleme ekranına GÖNDERMESİN — direkt ana sayfada işlem yapsın."
// Yönetici dosyayı bu karta bırakır; yükleme + analiz + canlı
// ilerleme + sonuç, hepsi dashboard'dan ayrılmadan akar:
//
//   bırak → yükle (şablon standardı 'yorum' kolonu) → canlı
//   progress (BatchProgressBar: aşama etiketleri + shimmer) →
//   tamamlanınca özet + "Sonuçları gör" + hero otomatik tazelenir.
//
// Şablona uymayan dosyada backend 422 + Türkçe yönlendirme döner;
// kart hatayı gösterir, şablon indirme + gelişmiş yükleme (sütun
// eşleştirmeli /analyze/upload) çıkışlarını sunar.

import {
  ArrowRight,
  CheckCircle2,
  FileSpreadsheet,
  Loader2,
  RotateCcw,
  UploadCloud,
} from "lucide-react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { BatchProgressBar } from "@/components/batch/BatchProgressStream";
import {
  useActiveBatchJob,
  useBatchUploadMutation,
} from "@/hooks/use-batch-uploads";
import { ApiError } from "@/lib/api-client";
import type { BatchJob } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACCEPTED_EXTENSIONS = [".csv", ".xlsx"];
const MAX_FILE_BYTES = 50 * 1024 * 1024;

type DockState =
  | { phase: "idle" }
  | { phase: "uploading"; fileName: string }
  | { phase: "processing"; jobId: string; fileName: string }
  | { phase: "done"; fileName: string; succeeded: number; failed: number; jobId: string }
  | { phase: "error"; message: string };

export function UploadDock() {
  const [state, setState] = useState<DockState>({ phase: "idle" });
  const [dragOver, setDragOver] = useState(false);
  const upload = useBatchUploadMutation();
  const queryClient = useQueryClient();

  // Sprint 11.1 — yeniden bağlanma: başka sayfadan/dashboard'a
  // dönüldüğünde devam eden iş varsa kart kendiliğinden onun canlı
  // ilerlemesini gösterir ("sayfayı terk edince iptal oluyor"
  // algısının dashboard ayağı). Async-mirror istisnası: tetikleyici
  // sorgunun sonuçlanması.
  const activeJob = useActiveBatchJob();
  useEffect(() => {
    if (state.phase !== "idle") return;
    const running = activeJob.data;
    if (running) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setState({
        phase: "processing",
        jobId: running.job_id,
        fileName: running.file_name,
      });
    }
  }, [activeJob.data, state.phase]);

  function handleFile(file: File | null) {
    if (!file) return;
    const ext = "." + file.name.split(".").pop()?.toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(ext)) {
      toast.error("Sadece .csv veya .xlsx dosyaları kabul edilir.");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      toast.error("Dosya 50 MB sınırını aşıyor.");
      return;
    }
    setState({ phase: "uploading", fileName: file.name });
    upload.mutate(
      {
        file,
        // Hızlı yol: şablon standardı. Farklı kolon adı olan dosya
        // 422 yer ve kart gelişmiş yüklemeye yönlendirir.
        textColumn: "yorum",
        sourceColumn: null,
        autoCreateTickets: false,
      },
      {
        onSuccess: (job: BatchJob) =>
          setState({
            phase: "processing",
            jobId: job.job_id,
            fileName: file.name,
          }),
        onError: (err) =>
          setState({
            phase: "error",
            message:
              err instanceof ApiError
                ? err.detail
                : "Yükleme sırasında beklenmeyen bir hata oluştu.",
          }),
      },
    );
  }

  return (
    <section
      aria-label="Hızlı yükleme"
      className="rise-in shadow-elevated bg-card ring-foreground/8 overflow-hidden rounded-2xl ring-1"
    >
      <header className="bg-navy flex items-center gap-2.5 px-4 py-3">
        <span className="bg-brand/20 text-brand ring-brand/30 flex size-8 items-center justify-center rounded-lg ring-1">
          <UploadCloud className="size-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-white">Hızlı Yükleme</h2>
          <p className="text-[11px] text-zinc-300">
            Dosyayı bırakın — analiz burada başlasın
          </p>
        </div>
      </header>

      <div className="p-4">
        {state.phase === "idle" && (
          <DropZone dragOver={dragOver} setDragOver={setDragOver} onFile={handleFile} />
        )}

        {state.phase === "uploading" && (
          <div className="flex items-center gap-3 py-6 text-sm">
            <Loader2 className="text-primary size-5 animate-spin" aria-hidden />
            <div className="min-w-0">
              <p className="truncate font-medium">{state.fileName}</p>
              <p className="text-muted-foreground text-xs">Dosya yükleniyor…</p>
            </div>
          </div>
        )}

        {state.phase === "processing" && (
          <div className="space-y-2">
            <p className="truncate text-xs font-medium text-muted-foreground">
              {state.fileName}
            </p>
            <BatchProgressBar
              jobId={state.jobId}
              onComplete={(snapshot) => {
                setState({
                  phase: "done",
                  fileName: state.fileName,
                  succeeded: snapshot.succeeded,
                  failed: snapshot.failed,
                  jobId: state.jobId,
                });
                // Hero + rapor blokları yeni veriyle tazelensin.
                void queryClient.invalidateQueries({
                  queryKey: ["executive-overview"],
                });
              }}
            />
          </div>
        )}

        {state.phase === "done" && (
          <div className="space-y-3 py-1">
            <div className="flex items-start gap-2.5">
              <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-emerald-600" aria-hidden />
              <div className="min-w-0 text-sm">
                <p className="font-semibold">Analiz tamamlandı</p>
                <p className="text-muted-foreground text-xs">
                  {state.succeeded.toLocaleString("tr-TR")} yorum analiz edildi
                  {state.failed > 0 &&
                    ` · ${state.failed.toLocaleString("tr-TR")} satır hatalı`}
                  . Yukarıdaki rapor güncellendi.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Link
                href={`/reviews?batch_job_id=${state.jobId}`}
                className="bg-primary text-primary-foreground inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-transform hover:scale-[1.02]"
              >
                Sonuçları gör
                <ArrowRight className="size-3.5" aria-hidden />
              </Link>
              <button
                type="button"
                onClick={() => setState({ phase: "idle" })}
                className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold ring-1 ring-border transition-colors"
              >
                <RotateCcw className="size-3.5" aria-hidden />
                Yeni yükleme
              </button>
            </div>
          </div>
        )}

        {state.phase === "error" && (
          <div className="space-y-3 py-1">
            <p className="text-sm leading-relaxed text-red-700 dark:text-red-400 [overflow-wrap:anywhere]">
              {state.message}
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setState({ phase: "idle" })}
                className="bg-primary text-primary-foreground inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-transform hover:scale-[1.02]"
              >
                <RotateCcw className="size-3.5" aria-hidden />
                Tekrar dene
              </button>
              <Link
                href="/analyze/upload"
                className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold ring-1 ring-border transition-colors"
              >
                Gelişmiş yükleme
                <ArrowRight className="size-3.5" aria-hidden />
              </Link>
            </div>
          </div>
        )}

        {state.phase === "idle" && (
          <p className="text-muted-foreground mt-3 text-[11px] leading-relaxed">
            Şablon standardı: yorumlar <strong>yorum</strong> kolonunda.
            Farklı düzendeki dosyalar için{" "}
            <Link href="/analyze/upload" className="text-primary font-semibold hover:underline">
              gelişmiş yükleme
            </Link>
            .
          </p>
        )}
      </div>
    </section>
  );
}

function DropZone({
  dragOver,
  setDragOver,
  onFile,
}: {
  dragOver: boolean;
  setDragOver: (v: boolean) => void;
  onFile: (f: File | null) => void;
}) {
  return (
    <label
      htmlFor="dock-file-input"
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e: React.DragEvent<HTMLLabelElement>) => {
        e.preventDefault();
        setDragOver(false);
        onFile(e.dataTransfer.files?.[0] ?? null);
      }}
      className={cn(
        "border-primary/30 hover:border-primary hover:bg-accent/40 flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-7 text-center transition-colors",
        dragOver && "border-primary bg-accent/60",
      )}
    >
      <FileSpreadsheet className="text-primary size-8" aria-hidden />
      <div>
        <p className="text-sm font-semibold">
          CSV / XLSX dosyanızı buraya bırakın
        </p>
        <p className="text-muted-foreground text-xs">
          veya tıklayarak seçin · en fazla 50 MB
        </p>
      </div>
      <input
        id="dock-file-input"
        type="file"
        accept={ACCEPTED_EXTENSIONS.join(",")}
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
        className="hidden"
      />
    </label>
  );
}
