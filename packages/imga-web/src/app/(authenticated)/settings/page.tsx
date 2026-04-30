"use client";

import { useMemo } from "react";

import { AutomationModeForm } from "@/components/settings/automation-mode-form";
import { CategoryToggleList } from "@/components/settings/category-toggle-list";
import { CustomCategoriesSection } from "@/components/settings/custom-categories-section";
import { ForbiddenNotice } from "@/components/settings/forbidden-notice";
import { Skeleton } from "@/components/ui/skeleton";
import { useTenantConfig } from "@/hooks/use-tenant-config";
import { useAuthStore } from "@/lib/auth-store";
import type { AutomationMode } from "@/lib/types";

/**
 * Tenant settings page. Single column, sections stack vertically.
 * Tenant_admin (and super_admin) only — analyst / viewer hit
 * ForbiddenNotice. The custom CRUD section lands in the next commit.
 */
export default function SettingsPage() {
  const role = useAuthStore((s) => s.activeContext?.role);
  const isSuperAdmin = useAuthStore((s) => s.user?.is_super_admin ?? false);
  const config = useTenantConfig();

  const sorted = useMemo(() => {
    const all = config.data?.categories ?? [];
    return {
      globals: all
        .filter((c) => c.is_global && !c.is_archived)
        .sort((a, b) => a.code.localeCompare(b.code)),
      // Customs: active first (label A→Z), archived after (also A→Z).
      customs: all
        .filter((c) => !c.is_global)
        .sort((a, b) => {
          if (a.is_archived !== b.is_archived) return a.is_archived ? 1 : -1;
          return a.label_tr.localeCompare(b.label_tr, "tr");
        }),
    };
  }, [config.data]);

  const isAdmin = role === "tenant_admin" || isSuperAdmin;
  if (!isAdmin) return <ForbiddenNotice />;

  return (
    <main className="mx-auto w-full max-w-3xl space-y-6 p-6 md:p-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Ayarlar</h1>
        <p className="text-muted-foreground text-sm">
          Tenant yapılandırması — otomasyon politikası, kategori taksonomisi.
        </p>
      </header>

      {config.isLoading ? (
        <div className="space-y-6">
          <Skeleton className="h-64" />
          <Skeleton className="h-72" />
          <Skeleton className="h-56" />
        </div>
      ) : config.isError ? (
        <p className="text-destructive py-12 text-center text-sm">Ayarlar yüklenemedi.</p>
      ) : config.data ? (
        <>
          <AutomationModeForm current={config.data.automation_mode as AutomationMode} />
          <CategoryToggleList categories={sorted.globals} />
          <CustomCategoriesSection categories={sorted.customs} />
        </>
      ) : null}
    </main>
  );
}
