"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  AdminInvitationCreateRequest,
  AdminInvitationCreateResponse,
  AdminTenantCreateRequest,
  AdminTenantCreateResponse,
  AdminTenantSummary,
  AdminTenantUpdateRequest,
} from "@/lib/types";

/**
 * Sprint 7.7.4 — super-admin tenant CRUD hooks.
 *
 * Backend lives at /admin/tenants (Sprint 7.5.5 / Alt-Faz 1, see
 * routes/admin/tenants.py). All endpoints require super_admin and
 * run on the BYPASSRLS imga_admin role; calling them as a regular
 * tenant_admin returns 403, which the consumers catch and toast.
 */

const ADMIN_TENANTS_KEY = "admin-tenants";

/**
 * C3/B7 (2026-08-20 süper-admin envanteri) — GET /admin/tenants artık 5
 * opsiyonel envanter alanı dönüyor (bkz. routes/admin/tenants.py
 * TenantSummary + services/tenant_service.py TenantListRow docstring'i).
 * lib/types.ts'teki `AdminTenantSummary`'ye eklenmedi — bu turda
 * types.ts başka bir ajanın bölgesi (use-analytics.ts'teki
 * AnalyticsQueryFilters ile aynı desen: tip burada, hook dosyasında
 * genişletiliyor). Tüm alanlar null olabilir — ya stats hiç
 * hesaplanmadı ya da (yalnız cost_30d_usd) 30 günde bilinen maliyetli
 * çağrı yok.
 */
export interface AdminTenantInventoryStats {
  review_count: number | null;
  last_upload_at: string | null;
  tokens_30d: number | null;
  cost_30d_usd: number | null;
  engagement_band: string | null;
}

export type AdminTenantSummaryWithStats = AdminTenantSummary & AdminTenantInventoryStats;

interface AdminTenantListResponseWithStats {
  tenants: AdminTenantSummaryWithStats[];
}

export function useAdminTenants(includeDeleted = false) {
  return useQuery({
    queryKey: [ADMIN_TENANTS_KEY, "list", includeDeleted],
    queryFn: async (): Promise<AdminTenantSummaryWithStats[]> => {
      const qs = includeDeleted ? "?include_deleted=true" : "";
      const data = await apiRequest<AdminTenantListResponseWithStats>(`/admin/tenants${qs}`);
      return data.tenants;
    },
  });
}

export function useCreateAdminTenant() {
  const qc = useQueryClient();
  return useMutation<AdminTenantCreateResponse, Error, AdminTenantCreateRequest>({
    mutationFn: async (body) => {
      return apiRequest<AdminTenantCreateResponse>("/admin/tenants", {
        method: "POST",
        body,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [ADMIN_TENANTS_KEY] });
    },
  });
}

export interface UpdateAdminTenantInput {
  tenantId: string;
  patch: AdminTenantUpdateRequest;
}

export function useUpdateAdminTenant() {
  const qc = useQueryClient();
  return useMutation<AdminTenantSummary, Error, UpdateAdminTenantInput>({
    mutationFn: async ({ tenantId, patch }) => {
      return apiRequest<AdminTenantSummary>(`/admin/tenants/${tenantId}`, {
        method: "PATCH",
        body: patch,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [ADMIN_TENANTS_KEY] });
    },
  });
}

export function useDeleteAdminTenant() {
  const qc = useQueryClient();
  return useMutation<AdminTenantSummary, Error, { tenantId: string }>({
    mutationFn: async ({ tenantId }) => {
      return apiRequest<AdminTenantSummary>(`/admin/tenants/${tenantId}`, {
        method: "DELETE",
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [ADMIN_TENANTS_KEY] });
    },
  });
}

// --- admin invitation create (used by the per-row "Davet" action) ---

export interface CreateAdminInvitationInput {
  tenantId: string;
  body: AdminInvitationCreateRequest;
}

export function useCreateAdminInvitation() {
  return useMutation<AdminInvitationCreateResponse, Error, CreateAdminInvitationInput>({
    mutationFn: async ({ tenantId, body }) => {
      return apiRequest<AdminInvitationCreateResponse>(`/admin/tenants/${tenantId}/invitations`, {
        method: "POST",
        body,
      });
    },
  });
}
