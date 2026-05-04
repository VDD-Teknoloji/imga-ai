// Sprint 8.3.6.6 — tenant SWOT/OKR context profile (industry / size /
// description). Two hooks: one read, one write.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  TenantProfile,
  TenantProfileUpdateRequest,
} from "@/lib/types";

const QUERY_KEY = ["tenant-profile"] as const;

export function useTenantProfile() {
  return useQuery<TenantProfile>({
    queryKey: QUERY_KEY,
    queryFn: () => apiRequest<TenantProfile>("/tenants/me/profile"),
  });
}

export function useUpdateTenantProfile() {
  const qc = useQueryClient();
  return useMutation<TenantProfile, Error, TenantProfileUpdateRequest>({
    mutationFn: (body) =>
      apiRequest<TenantProfile>("/tenants/me/profile", {
        method: "PATCH",
        body,
      }),
    onSuccess: (data) => {
      qc.setQueryData(QUERY_KEY, data);
    },
  });
}
