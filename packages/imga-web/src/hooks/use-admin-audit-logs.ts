"use client";

// C4/B2 (2026-08-20 süper-admin envanteri) — çapraz-kurum denetim kaydı
// listesi. Backend: imga_api routes/admin/audit_logs.py +
// services/audit_service.py (AuditService.list).

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export interface AdminAuditLogItem {
  id: string;
  tenant_id: string | null;
  tenant_name: string | null;
  actor_user_id: string | null;
  actor_email: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  ip_address: string | null;
  created_at: string;
}

export interface AdminAuditLogListResponse {
  items: AdminAuditLogItem[];
  total: number;
}

export interface AdminAuditLogFilters {
  tenant_id?: string;
  /** Serbest metin — backend ILIKE %action% (bkz. AuditService.list). */
  action?: string;
  /** YYYY-MM-DD (URL-friendly bare date, url-state-patterns.md kuralı). */
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

/**
 * AuditService.list `date_to`'yu `<` (exclusive) karşılaştırır —
 * docstring'i birebir: "pass the instant right after the window you
 * want included." Bu yüzden burada use-analytics.ts'in
 * end-of-day-23:59:59 deseni UYGUN DEĞİL (son saniyeyi kaybeder);
 * ertesi günün YEREL gece yarısına genişletiyoruz.
 */
function dateOnlyToLocalIsoExclusive(
  value: string | undefined,
  nextDay: boolean,
): string | undefined {
  if (!value) return undefined;
  const d = new Date(`${value}T00:00:00`);
  if (Number.isNaN(d.getTime())) return undefined;
  if (nextDay) d.setDate(d.getDate() + 1);
  return d.toISOString();
}

export function useAdminAuditLogs(filters: AdminAuditLogFilters = {}) {
  const qs = new URLSearchParams();
  if (filters.tenant_id) qs.set("tenant_id", filters.tenant_id);
  if (filters.action) qs.set("action", filters.action);
  const isoFrom = dateOnlyToLocalIsoExclusive(filters.date_from, false);
  const isoTo = dateOnlyToLocalIsoExclusive(filters.date_to, true);
  if (isoFrom) qs.set("date_from", isoFrom);
  if (isoTo) qs.set("date_to", isoTo);
  qs.set("limit", String(filters.limit ?? 50));
  qs.set("offset", String(filters.offset ?? 0));
  const qsStr = qs.toString();
  return useQuery<AdminAuditLogListResponse>({
    queryKey: ["admin-audit-logs", filters],
    queryFn: () => apiRequest<AdminAuditLogListResponse>(`/admin/audit-logs?${qsStr}`),
  });
}
