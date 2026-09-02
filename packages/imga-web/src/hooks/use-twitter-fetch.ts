// "Twitter'dan Çek" — arka plana alınmış içe aktarma akışının FE
// veri katmanı.
//
// POST /tenants/me/analyze/twitter-import artık 202 {job_id,status}
// döner (backend fetch→judge→CSV→enqueue zincirini arq worker'a
// taşıyor); ilerleme GET /tenants/me/analyze/twitter-import/jobs/{id}
// üzerinden 2 sn'de bir poll edilir (Redis hash — backend tarafı bu
// oturumda paralel inşa ediliyor, burada sözleşmeye göre kodlanıyor).
//
// use-batch-uploads.ts'teki useTwitterImportMutation / TwitterImportResult
// bu akışta artık kullanılmıyor (POST yanıt şekli kökten değişti) —
// o dosya bu görevin kapsamı dışında; temizliği ayrı bir iş.

import { useMutation, useQuery } from "@tanstack/react-query";

import { apiRequest, ApiError } from "@/lib/api-client";

export interface TwitterImportSubmitInput {
  term: string;
  count: number;
  excludeHandle?: string;
  /** /plan adımının marka özeti — AI hakemine bağlam (opsiyonel). */
  brandSummary?: string;
  /** AI alaka hakemi (varsayılan açık). */
  relevanceCheck?: boolean;
}

export interface TwitterImportEnqueuedResponse {
  job_id: string;
  status: "queued";
}

export function useTwitterImportSubmitMutation() {
  return useMutation<TwitterImportEnqueuedResponse, Error, TwitterImportSubmitInput>({
    mutationFn: async ({ term, count, excludeHandle, brandSummary, relevanceCheck }) =>
      apiRequest<TwitterImportEnqueuedResponse>("/tenants/me/analyze/twitter-import", {
        method: "POST",
        body: {
          term,
          count,
          exclude_handle: excludeHandle?.trim() || null,
          brand_summary: brandSummary?.trim() || null,
          relevance_check: relevanceCheck ?? true,
        },
      }),
  });
}

export type TwitterFetchJobStatus = "queued" | "running" | "done" | "failed";
export type TwitterFetchJobStage = "fetching" | "judging" | "finalizing";
export type TwitterFetchJobError =
  | "fetch_failed"
  | "no_results"
  | "no_relevant_results"
  | "internal_error";

export interface TwitterFetchJobStatusResponse {
  job_id: string;
  status: TwitterFetchJobStatus;
  stage: TwitterFetchJobStage | null;
  requested: number;
  tweets_found: number;
  pages_done: number;
  fetched_total: number;
  filtered_out: number;
  excluded_collab: number;
  oldest_tweet_at: string | null;
  newest_tweet_at: string | null;
  exhausted: boolean | null;
  kept_after_filter: number | null;
  filtered_by_ai: number | null;
  ai_check_skipped: boolean | null;
  batch_job_id: string | null;
  error: TwitterFetchJobError | null;
}

const TERMINAL_JOB_STATUSES: ReadonlySet<TwitterFetchJobStatus> = new Set(["done", "failed"]);

/** GET /tenants/me/analyze/twitter-import/jobs/{id} — 2 sn poll
 *  (orchestrator'ın açık isteği; useBatchJob'un 3 sn'inden kasıtlı
 *  farklı). 404 → Redis hash yok/TTL düştü, "job kayboldu" durumu —
 *  bu ApiError.status===404 olarak query error'ına düşer, çağıran
 *  bunu "başarısız" ile karıştırmamalı (bkz. twitter-fetch-progress).
 *  Diğer hatalarda (ağ sıçraması) poll DURMAZ — TanStack son bilinen
 *  `data`'yı korur, sonraki tik yeniden dener. */
export function useTwitterFetchJobStatus(jobId: string | null) {
  return useQuery<TwitterFetchJobStatusResponse>({
    queryKey: ["twitter-fetch-job", jobId],
    queryFn: async () => {
      if (!jobId) throw new Error("missing jobId");
      return apiRequest<TwitterFetchJobStatusResponse>(
        `/tenants/me/analyze/twitter-import/jobs/${jobId}`,
      );
    },
    enabled: jobId !== null,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      return failureCount < 3;
    },
    refetchInterval: (query) => {
      const err = query.state.error;
      if (err instanceof ApiError && err.status === 404) return false;
      const data = query.state.data;
      if (!data) return 2000;
      return TERMINAL_JOB_STATUSES.has(data.status) ? false : 2000;
    },
  });
}

/** Tamamlanma özeti — hem canlı geçişte atılan toast'ta (page.tsx)
 *  hem de F5/geri-tuşuyla "zaten done" bulunan job'ın kartında
 *  (twitter-fetch-progress.tsx) aynı metni üretmek için tek yerde. */
export function buildTwitterImportSummary(
  data: Pick<
    TwitterFetchJobStatusResponse,
    | "requested"
    | "tweets_found"
    | "kept_after_filter"
    | "exhausted"
    | "filtered_out"
    | "filtered_by_ai"
    | "ai_check_skipped"
  >,
  relevanceCheckRequested: boolean,
  t: (key: string, vars?: Record<string, string | number>) => string,
): string {
  const found = data.kept_after_filter ?? data.tweets_found;
  const base =
    data.exhausted === true && found < data.requested
      ? t("analyze.twitter.queuedPartial", { found, requested: data.requested })
      : t("analyze.twitter.queued", { found });
  const notes = [
    (data.filtered_out ?? 0) > 0 ? t("analyze.twitter.filteredNote", { n: data.filtered_out }) : "",
    (data.filtered_by_ai ?? 0) > 0
      ? t("analyze.twitter.aiFilteredNote", { n: data.filtered_by_ai ?? 0 })
      : "",
    relevanceCheckRequested && data.ai_check_skipped === true
      ? t("analyze.twitter.aiSkippedNote")
      : "",
  ].join("");
  return `${base}${notes}`;
}

// --- Reload/back-tuşu emniyeti ---------------------------------------
// job_id URL'de kalıcı (url-state-patterns.md), ama arama terimi ve
// "AI alaka kontrolü açık mıydı" formdan gelir — form F5'te sıfırlanır.
// Bu küçük localStorage önbelleği yalnız (a) hata mesajında terimi
// göstermek ve (b) geçen süre sayacını F5 sonrası kaldığı yerden
// sürdürmek için — en iyi çaba, yoksa zarifçe düşer (bkz. okuyucular).

export interface TwitterFetchJobMemo {
  term: string;
  relevanceCheckRequested: boolean;
  startedAt: number;
}

const JOB_MEMO_PREFIX = "imga:twitter-fetch:";

export function writeTwitterFetchJobMemo(jobId: string, memo: TwitterFetchJobMemo): void {
  try {
    localStorage.setItem(JOB_MEMO_PREFIX + jobId, JSON.stringify(memo));
  } catch {
    // Gizli sekme / depolama engeli — best-effort, sessizce geç.
  }
}

export function readTwitterFetchJobMemo(jobId: string): TwitterFetchJobMemo | null {
  try {
    const raw = localStorage.getItem(JOB_MEMO_PREFIX + jobId);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<TwitterFetchJobMemo>;
    if (
      typeof parsed.term !== "string" ||
      typeof parsed.startedAt !== "number" ||
      typeof parsed.relevanceCheckRequested !== "boolean"
    ) {
      return null;
    }
    return {
      term: parsed.term,
      startedAt: parsed.startedAt,
      relevanceCheckRequested: parsed.relevanceCheckRequested,
    };
  } catch {
    return null;
  }
}

export function clearTwitterFetchJobMemo(jobId: string): void {
  try {
    localStorage.removeItem(JOB_MEMO_PREFIX + jobId);
  } catch {
    // ignore
  }
}
