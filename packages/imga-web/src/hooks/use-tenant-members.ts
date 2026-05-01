"use client";

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { TenantMember, TenantMembersResponse } from "@/lib/types";

/**
 * Sprint 7.7.2 — assignee picker / actor name resolution.
 *
 * Backed by Sprint 7.5.5's GET /tenants/me/users (roadmap A7). Returns
 * active members of the bound tenant; sorted by full_name ASC server-
 * side. Cached for the active tenant — auth-store changes (tenant
 * switch) drop the cache via the tenant-id key segment.
 */
export function useTenantMembers(activeTenantId: string | null | undefined) {
  return useQuery({
    queryKey: ["tenant-members", activeTenantId],
    queryFn: async (): Promise<TenantMember[]> => {
      const data = await apiRequest<TenantMembersResponse>("/tenants/me/users");
      return data.members;
    },
    // No tenant context → no fetch.
    enabled:
      typeof activeTenantId === "string" && activeTenantId.length > 0,
  });
}
