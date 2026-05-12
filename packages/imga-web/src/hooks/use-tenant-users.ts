// Sprint 9.5 A1 — /settings/users hooks.
//
// Members come from GET /tenants/me/users (read-only, every member can
// hit it). Invitation create/list/revoke run against
// /admin/tenants/{tenant_id}/invitations — those routes accept the
// caller's own active tenant when they're acting as tenant_admin (the
// route guard does the role check, no super_admin needed). The page
// gates itself to tenant_admin / super_admin in the UI so analyst/
// viewer never see the form.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { UserTenantRole } from "@/lib/types";

export interface TenantMember {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  last_login_at: string | null;
  invitation_accepted_at: string | null;
}

interface TenantMembersResponse {
  members: TenantMember[];
}

export interface TenantInvitation {
  id: string;
  email: string;
  role: string;
  invited_by: string | null;
  expires_at: string;
  accepted_at: string | null;
  created_at: string;
}

interface TenantInvitationsResponse {
  invitations: TenantInvitation[];
}

export interface InvitationCreateRequest {
  email: string;
  role: UserTenantRole;
}

export interface InvitationCreateResponse {
  invitation_id: string;
  token: string;
  email: string;
  role: string;
  expires_at: string;
}

const MEMBERS_KEY = ["tenant-members"] as const;
const INVITATIONS_KEY = ["tenant-invitations"] as const;

export function useTenantMembers(search?: string) {
  const q = search?.trim() ? `?search=${encodeURIComponent(search.trim())}` : "";
  return useQuery<TenantMembersResponse>({
    queryKey: [...MEMBERS_KEY, { search: search ?? "" }],
    queryFn: () => apiRequest<TenantMembersResponse>(`/tenants/me/users${q}`),
  });
}

export function useTenantInvitations(
  tenantId: string | null | undefined,
  includeAccepted = false,
) {
  return useQuery<TenantInvitationsResponse>({
    queryKey: [...INVITATIONS_KEY, { tenantId, includeAccepted }],
    queryFn: () =>
      apiRequest<TenantInvitationsResponse>(
        `/admin/tenants/${tenantId}/invitations?include_accepted=${
          includeAccepted ? "true" : "false"
        }`,
      ),
    // The admin path 403s when there's no active tenant context;
    // skip the call until we know which tenant the user is in.
    enabled: !!tenantId,
  });
}

export function useCreateInvitation(tenantId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation<InvitationCreateResponse, Error, InvitationCreateRequest>({
    mutationFn: (body) =>
      apiRequest<InvitationCreateResponse>(
        `/admin/tenants/${tenantId}/invitations`,
        { method: "POST", body },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: INVITATIONS_KEY });
    },
  });
}

export function useRevokeInvitation(tenantId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (invitationId) =>
      apiRequest<void>(
        `/admin/tenants/${tenantId}/invitations/${invitationId}`,
        { method: "DELETE" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: INVITATIONS_KEY });
    },
  });
}
