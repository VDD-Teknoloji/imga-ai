"use client";

// Sprint 13 — sayfa düzeyi rol koruması.
//
// Backend guard'larının (require_role) frontend aynası: yetkisiz rol
// sayfanın İÇERİĞİNİ hiç kurmaz (sorgular tetiklenmez), ForbiddenNotice
// görür. Kullanım: default export'u sarmala —
//
//   export default function Page() {
//     return <RequireRole level="admin"><PageInner /></RequireRole>;
//   }
//
// level eşiği: "write" = tenant_admin | analyst | super admin;
// "admin" = tenant_admin | super admin; "super" = yalnız super admin.

import type { ReactNode } from "react";

import { ForbiddenNotice } from "@/components/settings/forbidden-notice";
import { useRoleFlags } from "@/hooks/use-role-flags";

interface Props {
  level: "write" | "admin" | "super";
  children: ReactNode;
}

export function RequireRole({ level, children }: Props) {
  const { canWrite, isAdmin, isSuperAdmin } = useRoleFlags();
  const allowed =
    level === "super" ? isSuperAdmin : level === "admin" ? isAdmin : canWrite;
  if (!allowed) return <ForbiddenNotice />;
  return <>{children}</>;
}
