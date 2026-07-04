// Sprint 13 — merkezi rol okuma helper'ı.
//
// Rol kararları bugüne dek her bileşende elle yazılıyordu
// ("role === 'tenant_admin' || isSuperAdmin" tekrarları). Tek
// kaynak: backend'in require_role matrisiyle ayna —
//
//   isAdmin  : tenant_admin veya super admin (ayarlar, denetim).
//   canWrite : + analyst — operasyonel yazma (yükleme, analiz,
//              ticket aksiyonu, rapor/SWOT/OKR üretimi).
//   isViewer : salt-okuma üye.

import { useAuthStore } from "@/lib/auth-store";
import type { UserTenantRole } from "@/lib/types";

export interface RoleFlags {
  role: UserTenantRole | null;
  isSuperAdmin: boolean;
  isAdmin: boolean;
  canWrite: boolean;
  isViewer: boolean;
}

export function useRoleFlags(): RoleFlags {
  const role = useAuthStore((s) => s.activeContext?.role ?? null);
  const isSuperAdmin = useAuthStore((s) => s.user?.is_super_admin ?? false);
  const isAdmin = isSuperAdmin || role === "tenant_admin";
  const canWrite = isAdmin || role === "analyst";
  return { role, isSuperAdmin, isAdmin, canWrite, isViewer: !canWrite };
}
