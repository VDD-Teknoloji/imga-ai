"use client";

// F1 (2026-09-02) — sağ ray, QuickLinks'in altında, yalnız yöneticiye
// (tenant_admin/super admin) görünen küçük bir dürtme kartı. Kurum
// profilinde sektör (industry) hiç seçilmemişse kök neden önerilerinin
// jenerik kaldığını hatırlatır ve /settings/profile'a yönlendirir.
// Yükleniyorken veya sektör zaten doluysa tamamen sessiz (görev
// kuralı: "render null while loading or when industry is set").

import Link from "next/link";

import { useRoleFlags } from "@/hooks/use-role-flags";
import { useTenantProfile } from "@/hooks/use-tenant-profile";
import { useTranslation } from "@/lib/i18n/use-translation";

export function ContextNudge() {
  const { t } = useTranslation();
  const { isAdmin } = useRoleFlags();
  const profile = useTenantProfile();

  if (!isAdmin) return null;
  if (profile.isLoading || profile.isError || !profile.data) return null;
  if (profile.data.industry) return null;

  return (
    <Link
      href="/settings/profile"
      className="rise-in shadow-soft bg-card ring-foreground/5 hover:bg-accent/40 block rounded-3xl p-4 ring-1 transition-colors"
    >
      <p className="text-muted-foreground text-sm leading-relaxed">
        {t("dashboard.contextNudge.text")}
      </p>
    </Link>
  );
}
