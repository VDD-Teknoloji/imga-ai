// Sprint 8.3.2 reports hooks.
//
// Three primitives:
//   * useGenerateReport     — POST /reports/generate (returns queued job)
//   * useReportJob(id)      — single-job poll (3s while non-terminal)
//   * useReports()          — recent jobs list (infinite-style)
//   * useDeleteReport       — DELETE /reports/{id}
//
// Download is a direct anchor click against /reports/{id}/download — no
// hook needed; the route returns a streamed FileResponse with the
// auth bearer attached via the same apiRequest path.

import { useMutation, useQuery, useQueryClient, useInfiniteQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  GenerateReportRequest,
  GenerateReportResponse,
  ReportEstimateResponse,
  ReportJobView,
  ReportListResponse,
  ReportStatus,
} from "@/lib/types";

const TERMINAL: ReadonlySet<ReportStatus> = new Set(["completed", "failed"]);

/** Dry-run preview the 90-day / 50K-row checks + estimate. Same 400
 * surface as /generate so the user sees the same Turkish error before
 * the modal's "Üret" step. */
export function useEstimateReport() {
  return useMutation<ReportEstimateResponse, Error, GenerateReportRequest>({
    mutationFn: (body) =>
      apiRequest<ReportEstimateResponse>("/tenants/me/reports/estimate", {
        method: "POST",
        body,
      }),
  });
}


export function useGenerateReport() {
  const queryClient = useQueryClient();
  return useMutation<GenerateReportResponse, Error, GenerateReportRequest>({
    mutationFn: (body) =>
      apiRequest<GenerateReportResponse>("/tenants/me/reports/generate", {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    },
  });
}

export function useReportJob(reportId: string | null) {
  return useQuery<ReportJobView>({
    queryKey: ["report-job", reportId],
    queryFn: async () => {
      if (!reportId) throw new Error("missing reportId");
      return apiRequest<ReportJobView>(`/tenants/me/reports/${reportId}`);
    },
    enabled: reportId !== null,
    refetchInterval: (query) => {
      const job = query.state.data;
      if (!job) return 3000;
      return TERMINAL.has(job.status) ? false : 3000;
    },
  });
}

export function useReports(limit = 50) {
  return useInfiniteQuery<ReportListResponse>({
    queryKey: ["reports", limit],
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => {
      const offset = typeof pageParam === "number" ? pageParam : 0;
      return apiRequest<ReportListResponse>(
        `/tenants/me/reports?limit=${limit}&offset=${offset}`,
      );
    },
    getNextPageParam: (lastPage, pages) => {
      const consumed = pages.reduce((sum, p) => sum + p.reports.length, 0);
      return lastPage.reports.length < limit ? undefined : consumed;
    },
  });
}

export function useDeleteReport() {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: async (reportId) => {
      await apiRequest<void>(`/tenants/me/reports/${reportId}`, {
        method: "DELETE",
      });
    },
    onSuccess: (_data, reportId) => {
      queryClient.invalidateQueries({ queryKey: ["reports"] });
      queryClient.invalidateQueries({ queryKey: ["report-job", reportId] });
    },
  });
}
