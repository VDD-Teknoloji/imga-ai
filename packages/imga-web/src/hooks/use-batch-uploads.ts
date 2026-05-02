// Sprint 8.3.1 batch upload hooks.
//
// Three TanStack Query primitives:
//   * useBatchUploadMutation — multipart POST, returns the queued job
//   * useBatchJob(jobId)     — single-job poll (3s while processing)
//   * useBatchHistory()      — recent uploads, infinite-style "load more"
//
// Polling is keyed on the job's status — once we see a terminal state
// (completed / failed / cancelled), the refetchInterval flips to false
// so we don't keep hitting the API.

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { BatchJob, BatchJobListResponse } from "@/lib/types";

export interface BatchUploadInput {
  file: File;
  textColumn: string;
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
      fd.append("text_column", textColumn);
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
