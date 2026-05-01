"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  AdminInvitationCreateRequest,
  AdminInvitationCreateResponse,
  AdminTenantCreateRequest,
  AdminTenantCreateResponse,
  AdminTenantListResponse,
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

export function useAdminTenants(includeDeleted = false) {
  return useQuery({
    queryKey: [ADMIN_TENANTS_KEY, "list", includeDeleted],
    queryFn: async (): Promise<AdminTenantSummary[]> => {
      const qs = includeDeleted ? "?include_deleted=true" : "";
      const data = await apiRequest<AdminTenantListResponse>(
        `/admin/tenants${qs}`,
      );
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
  return useMutation<
    AdminInvitationCreateResponse,
    Error,
    CreateAdminInvitationInput
  >({
    mutationFn: async ({ tenantId, body }) => {
      return apiRequest<AdminInvitationCreateResponse>(
        `/admin/tenants/${tenantId}/invitations`,
        { method: "POST", body },
      );
    },
  });
}
