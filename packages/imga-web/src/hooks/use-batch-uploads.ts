// Sprint 8.3.1 batch upload hooks.
//
// Three TanStack Query primitives:
//   * useBatchUploadMutation — multipart POST, returns the queued job
//   * useBatchJob(jobId)     — single-job poll (3s while processing) —
//                               kept for callers that still want
//                               polling semantics; the upload page
//                               replaces this with SSE in
//                               useBatchProgressStream below.
//   * useBatchHistory()      — recent uploads, infinite-style "load more"
//
// Sprint 9.0.5-B A — useBatchProgressStream is the SSE-driven
// replacement for the upload page's polling. Initial fetch + live
// progress events; no refetchInterval.

import { useEffect, useRef, useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import { openSseStream, type SseHandle } from "@/lib/sse-client";
import type { BatchJob, BatchJobListResponse } from "@/lib/types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

export interface BatchUploadInput {
  file: File;
  /** Sprint 13 — opsiyonel: verilmezse backend REVIEW_TEXT kolonunu
   *  smart detector ile kendisi çözer. */
  textColumn?: string | null;
  sourceColumn?: string | null;
  autoCreateTickets: boolean;
}

const TERMINAL_STATUSES = new Set<BatchJob["status"]>([
  "completed",
  "failed",
  "cancelled",
]);

export function useBatchUploadMutation() {
  const queryClient = useQueryClient();
  return useMutation<BatchJob, Error, BatchUploadInput>({
    mutationFn: async ({ file, textColumn, sourceColumn, autoCreateTickets }) => {
      const fd = new FormData();
      fd.append("file", file);
      if (textColumn) fd.append("text_column", textColumn);
      if (sourceColumn) fd.append("source_column", sourceColumn);
      fd.append("auto_create_tickets", autoCreateTickets ? "true" : "false");
      return apiRequest<BatchJob>("/tenants/me/analyze/batch", {
        method: "POST",
        body: fd,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["batch-history"] });
    },
  });
}

export function useBatchJob(jobId: string | null) {
  return useQuery<BatchJob>({
    queryKey: ["batch-job", jobId],
    queryFn: async () => {
      if (!jobId) throw new Error("missing jobId");
      return apiRequest<BatchJob>(`/tenants/me/analyze/batch/${jobId}`);
    },
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const job = query.state.data;
      if (!job) return 3000;
      return TERMINAL_STATUSES.has(job.status) ? false : 3000;
    },
  });
}

/** BatchJob + canlı SSE karesinden gelen tahmini kalan süre.
 *  ``eta_seconds`` yalnız akış canlıyken dolar; poll yolunda kalmaz. */
export interface LiveBatchJob extends BatchJob {
  eta_seconds?: number | null;
}

export interface BatchProgressStreamState {
  data: LiveBatchJob | null;
  isLoading: boolean;
  error: string | null;
}

/** SSE 'progress'/'complete' kare şekli — backend
 *  ``batch_analyzer._progress_snapshot`` ile birebir. Anahtarları
 *  BatchJob'unkilerden FARKLI (``processed`` vs ``processed_rows``);
 *  spread'lemeden önce eşlenmesi şart, yoksa kareler barı oynatmaz
 *  (Sprint 13 — 200'lük donma bug'ının FE ayağı). */
interface BatchProgressSseSnapshot {
  status?: string;
  processed?: number;
  total?: number;
  succeeded?: number;
  failed?: number;
  tickets_created?: number;
  duplicates_skipped?: number;
  eta_seconds?: number | null;
}

const BATCH_STATUSES: ReadonlySet<string> = new Set([
  "queued",
  "processing",
  "completed",
  "failed",
  "cancelled",
]);

function sseSnapshotToPatch(raw: object): Partial<LiveBatchJob> {
  const s = raw as BatchProgressSseSnapshot;
  const patch: Partial<LiveBatchJob> = {};
  if (typeof s.status === "string" && BATCH_STATUSES.has(s.status)) {
    patch.status = s.status as BatchJob["status"];
  }
  if (typeof s.processed === "number") patch.processed_rows = s.processed;
  if (typeof s.total === "number") patch.total_rows = s.total;
  if (typeof s.succeeded === "number") patch.succeeded_rows = s.succeeded;
  if (typeof s.failed === "number") patch.failed_rows = s.failed;
  if (typeof s.tickets_created === "number") {
    patch.tickets_created = s.tickets_created;
  }
  if (typeof s.duplicates_skipped === "number") {
    patch.duplicates_skipped = s.duplicates_skipped;
  }
  if (s.eta_seconds === null || typeof s.eta_seconds === "number") {
    patch.eta_seconds = s.eta_seconds;
  }
  return patch;
}

/**
 * Sprint 9.0.5-B A — SSE-driven replacement for ``useBatchJob`` on
 * the upload page. Combines:
 *   * One initial GET (so the UI has structured fields like
 *     ``file_name`` immediately).
 *   * SSE subscription for live processed/total/percent updates +
 *     terminal transitions.
 *
 * Returns a shape close to TanStack Query's so the upload page
 * doesn't need a structural rewrite — ``data`` is a partial
 * BatchJob (initial fetch + last SSE snapshot folded together).
 */
export function useBatchProgressStream(
  jobId: string | null,
): BatchProgressStreamState {
  const [data, setData] = useState<LiveBatchJob | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(jobId !== null);
  const [error, setError] = useState<string | null>(null);
  const handleRef = useRef<SseHandle | null>(null);
  // Sprint 11.5 — emniyet sorgusu zamanlayıcısı (aşağıya bakın).
  const safetyPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // jobId değişiminde state sıfırlama — async-mirror istisnası
  // (upload/page.tsx'teki onaylı pattern ile aynı): tetikleyici bir
  // event değil, prop'un kendisi; SSE aboneliği de bu effect'te
  // kurulduğu için reset'in başka bir eve taşınamaz.
  useEffect(() => {
    if (!jobId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setData(null);
      setIsLoading(false);
      setError(null);
      return;
    }
     
    setIsLoading(true);
    setError(null);
    let cancelled = false;

    // Initial fetch — gives the UI the structured fields (file_name,
    // text_column, etc.) that the SSE snapshot doesn't include.
    void apiRequest<BatchJob>(`/tenants/me/analyze/batch/${jobId}`)
      .then((row) => {
        if (cancelled) return;
        setData(row);
        setIsLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setIsLoading(false);
      });

    const url = `${API_BASE}/tenants/me/analyze/batch/${jobId}/progress`;
    const handle = openSseStream(url, {
      reconnect: true,
      handlers: {
        progress: (payload) => {
          if (!payload || typeof payload !== "object") return;
          // SSE karesi BatchJob anahtarlarını kullanmaz; eşleyip
          // mevcut satırın üstüne katla — structured alanlar ilk
          // GET'ten kalır, canlı eta_seconds da yüzeye çıkar.
          const patch = sseSnapshotToPatch(payload);
          setData((prev) => mergeProgress(prev, patch));
          // Sprint 11.4 — terminal durum 'progress' karesiyle de
          // gelebilir (iş bittikten sonra kurulan SSE'nin ilk karesi).
          // Akışı kapat ki reconnect döngüsü oluşmasın; sayfanın
          // adım-ilerletme effect'i data.status üzerinden zaten
          // tetiklenir.
          if (patch.status && TERMINAL_STATUSES.has(patch.status)) {
            handleRef.current?.close();
            handleRef.current = null;
          }
        },
        complete: (payload) => {
          if (!payload || typeof payload !== "object") return;
          setData((prev) => mergeProgress(prev, sseSnapshotToPatch(payload)));
          handleRef.current?.close();
          handleRef.current = null;
        },
        ping: () => {
          /* keepalive */
        },
      },
      onError: (err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      },
    });
    handleRef.current = handle;

    // Sprint 11.5 — HER DURUMDA çalışan emniyet sorgusu. Üretim
    // kanıtı (Kitap1.xlsx, 0/98'de donma): SSE bağlantısı proxy
    // katmanında sessizce ölebiliyor — ne kare ne hata geliyor;
    // sayfa ilk GET'in görüntüsünde sonsuza dek kalıyordu. 9.5.5
    // B'nin watchdog'u yalnız BatchProgressStream BİLEŞENİNE
    // eklenmişti; bu hook (upload sayfası) korumasızdı. Çözüm,
    // bileşendekinden de basit: terminal duruma kadar 5 sn'de bir
    // job satırını oku (tek-satır GET — ucuz), DB durumu her zaman
    // otoritedir. SSE sağlıklıysa aradaki kareler saniye-altı
    // canlılığı zaten verir; ölüyse emniyet sorgusu hem ilerlemeyi
    // hem bitişi garanti eder.
    safetyPollRef.current = setInterval(() => {
      void apiRequest<BatchJob>(`/tenants/me/analyze/batch/${jobId}`)
        .then((row) => {
          if (cancelled) return;
          setData((prev) => mergeProgress(prev, row));
          if (TERMINAL_STATUSES.has(row.status)) {
            if (safetyPollRef.current) {
              clearInterval(safetyPollRef.current);
              safetyPollRef.current = null;
            }
            handleRef.current?.close();
            handleRef.current = null;
          }
        })
        .catch(() => {
          // Geçici hata — sonraki tik yeniden dener; kalıcı 401
          // api-client'ın onSessionExpired akışından yürür.
        });
    }, 5_000);

    return () => {
      cancelled = true;
      handle.close();
      handleRef.current = null;
      if (safetyPollRef.current) {
        clearInterval(safetyPollRef.current);
        safetyPollRef.current = null;
      }
    };
  }, [jobId]);

  return { data, isLoading, error };
}

function mergeProgress(
  prev: LiveBatchJob | null,
  patch: Partial<LiveBatchJob>,
): LiveBatchJob | null {
  if (prev === null) {
    // No initial-fetch result yet; keep the SSE snapshot until the
    // GET resolves and back-fills the structured fields.
    return patch as LiveBatchJob;
  }
  return { ...prev, ...patch };
}


export function useBatchHistory(limit = 50) {
  return useInfiniteQuery<BatchJobListResponse>({
    queryKey: ["batch-history", limit],
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => {
      const offset = typeof pageParam === "number" ? pageParam : 0;
      return apiRequest<BatchJobListResponse>(
        `/tenants/me/analyze/batch?limit=${limit}&offset=${offset}`,
      );
    },
    getNextPageParam: (lastPage, pages) => {
      const consumed = pages.reduce((sum, p) => sum + p.jobs.length, 0);
      return lastPage.jobs.length < limit ? undefined : consumed;
    },
  });
}

/** Sprint 11.1 — "sayfayı terk edince işlem iptal oluyor" algısının
 * çözümü. İş sunucuda (api-worker) tarayıcıdan bağımsız koşmaya
 * devam eder; kaybolan şey UI'ın işe BAĞLANTISIYDI — sayfaya dönen
 * kullanıcı ilerlemeyi göremiyordu ve işi iptal olmuş sanıyordu.
 * Bu hook en yeni queued/processing job'ı bulur; upload sayfası ve
 * dashboard Hızlı Yükleme kartı mount'ta ona yeniden bağlanır. */
export function useActiveBatchJob() {
  return useQuery<BatchJob | null>({
    queryKey: ["batch-active"],
    queryFn: async () => {
      const data = await apiRequest<BatchJobListResponse>(
        "/tenants/me/analyze/batch?limit=10&offset=0",
      );
      return (
        data.jobs.find(
          (j) => j.status === "queued" || j.status === "processing",
        ) ?? null
      );
    },
    // Mount'ta bir kez yeter — aktif iş bulunursa SSE devralır.
    staleTime: 5_000,
  });
}

export function useCancelBatchJobMutation() {
  const queryClient = useQueryClient();
  return useMutation<BatchJob, Error, string>({
    mutationFn: async (jobId) =>
      apiRequest<BatchJob>(`/tenants/me/analyze/batch/${jobId}`, {
        method: "DELETE",
      }),
    onSuccess: (_data, jobId) => {
      queryClient.invalidateQueries({ queryKey: ["batch-job", jobId] });
      queryClient.invalidateQueries({ queryKey: ["batch-history"] });
    },
  });
}
