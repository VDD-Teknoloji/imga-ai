// Sprint 8.3.6.6 — strategic reports (SWOT + OKR).
//
// Four hooks against /tenants/me/strategic-reports/*:
//   * useStrategicReports(filters) — paginated history list.
//   * useStrategicReport(id) — single-report detail (cache).
//   * useGenerateSwot — POST mutation; invalidates the list on success.
//   * useGenerateOkr — POST mutation; invalidates the list on success.
//
// Backend endpoints: POST .../swot/generate, POST .../okr/generate,
// GET .../, GET .../{id}. PDF download is a direct browser GET — no
// hook, just a window.open / anchor link in the page component.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  OkrGenerateRequest,
  StrategicReportDetail,
  StrategicReportListResponse,
  StrategicReportType,
  SwotGenerateRequest,
} from "@/lib/types";

interface ListFilters {
  report_type?: StrategicReportType;
  limit?: number;
  offset?: number;
}

function listQueryString(filters: ListFilters): string {
  const params = new URLSearchParams();
  if (filters.report_type) params.set("report_type", filters.report_type);
  params.set("limit", String(filters.limit ?? 20));
  params.set("offset", String(filters.offset ?? 0));
  return params.toString();
}

export function useStrategicReports(filters: ListFilters = {}) {
  const qs = listQueryString(filters);
  return useQuery<StrategicReportListResponse>({
    queryKey: ["strategic-reports", qs],
    queryFn: () =>
      apiRequest<StrategicReportListResponse>(
        `/tenants/me/strategic-reports?${qs}`,
      ),
  });
}

export function useStrategicReport(id: string | null) {
  return useQuery<StrategicReportDetail>({
    queryKey: ["strategic-report", id],
    queryFn: () => {
      if (!id) throw new Error("missing report id");
      return apiRequest<StrategicReportDetail>(
        `/tenants/me/strategic-reports/${id}`,
      );
    },
    enabled: id !== null,
  });
}

export function useGenerateSwot() {
  const qc = useQueryClient();
  return useMutation<StrategicReportDetail, Error, SwotGenerateRequest>({
    mutationFn: (body) =>
      apiRequest<StrategicReportDetail>(
        "/tenants/me/strategic-reports/swot/generate",
        { method: "POST", body },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategic-reports"] });
    },
  });
}

export function useGenerateOkr() {
  const qc = useQueryClient();
  return useMutation<StrategicReportDetail, Error, OkrGenerateRequest>({
    mutationFn: (body) =>
      apiRequest<StrategicReportDetail>(
        "/tenants/me/strategic-reports/okr/generate",
        { method: "POST", body },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategic-reports"] });
    },
  });
}
