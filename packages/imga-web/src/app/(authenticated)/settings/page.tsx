"use client";

import {
  ArrowRight,
  Building2,
  CalendarClock,
  KeyRound,
  Layers,
  Mail,
  ShieldAlert,
  Tags,
  Target,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { RequireRole } from "@/components/auth/require-role";
import { AutomationModeForm } from "@/components/settings/automation-mode-form";
import { CategoryToggleList } from "@/components/settings/category-toggle-list";
import { CustomCategoriesSection } from "@/components/settings/custom-categories-section";
import { Skeleton } from "@/components/ui/skeleton";
import { useTenantConfig } from "@/hooks/use-tenant-config";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { AutomationMode } from "@/lib/types";

/**
 * Tenant settings page. Single column, sections stack vertically.
 * Tenant_admin (and super_admin) only — analyst / viewer hit
 * ForbiddenNotice. The custom CRUD section lands in the next commit.
 */
export default function SettingsPage() {
  return (
    <RequireRole level="admin">
      <SettingsPageInner />
    </RequireRole>
  );
}

function SettingsPageInner() {
  const config = useTenantConfig();
  const { t } = useTranslation();

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

  return (
    <main className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6 md:px-8 md:py-10">
      <header className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {t("settings.index.title")}
        </h1>
        <p className="text-muted-foreground text-sm">
          {t("settings.index.subtitle")}
        </p>
      </header>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Link
          href="/settings/profile"
          className="bg-card hover:bg-accent ring-foreground/5 shadow-soft flex items-start gap-3 rounded-2xl p-5 ring-1 transition-colors"
        >
          <Building2 className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">
              {t("settings.index.profile.title")}
            </p>
            <p className="text-muted-foreground text-xs">
              {t("settings.index.profile.desc")}
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        <Link
          href="/settings/integrations"
          className="bg-card hover:bg-accent ring-foreground/5 shadow-soft flex items-start gap-3 rounded-2xl p-5 ring-1 transition-colors"
        >
          <KeyRound className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">
              {t("settings.index.integrations.title")}
            </p>
            <p className="text-muted-foreground text-xs">
              {t("settings.index.integrations.desc")}
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        <Link
          href="/admin/prompt-templates"
          className="bg-card hover:bg-accent ring-foreground/5 shadow-soft flex items-start gap-3 rounded-2xl p-5 ring-1 transition-colors"
        >
          <KeyRound className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">
              {t("settings.index.prompts.title")}
            </p>
            <p className="text-muted-foreground text-xs">
              {t("settings.index.prompts.desc")}
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        <Link
          href="/settings/taxonomies"
          className="bg-card hover:bg-accent ring-foreground/5 shadow-soft flex items-start gap-3 rounded-2xl p-5 ring-1 transition-colors"
        >
          <Tags className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">
              {t("settings.index.taxonomies.title")}
            </p>
            <p className="text-muted-foreground text-xs">
              {t("settings.index.taxonomies.desc")}
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        <Link
          href="/settings/sla-rules"
          className="bg-card hover:bg-accent ring-foreground/5 shadow-soft flex items-start gap-3 rounded-2xl p-5 ring-1 transition-colors"
        >
          <ShieldAlert className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">{t("settings.index.sla.title")}</p>
            <p className="text-muted-foreground text-xs">
              {t("settings.index.sla.desc")}
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        <Link
          href="/settings/ticket-routing"
          className="bg-card hover:bg-accent ring-foreground/5 shadow-soft flex items-start gap-3 rounded-2xl p-5 ring-1 transition-colors"
        >
          <Mail className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">
              {t("settings.index.ticketRouting.title")}
            </p>
            <p className="text-muted-foreground text-xs">
              {t("settings.index.ticketRouting.desc")}
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        {/* Sprint 9.4 I — three Sprint 9.2/9.3 surfaces that were
            URL-only secrets before now show up in the index. */}
        <Link
          href="/settings/kpi-goals"
          className="bg-card hover:bg-accent ring-foreground/5 shadow-soft flex items-start gap-3 rounded-2xl p-5 ring-1 transition-colors"
        >
          <Target className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">{t("settings.index.kpi.title")}</p>
            <p className="text-muted-foreground text-xs">
              {t("settings.index.kpi.desc")}
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        <Link
          href="/settings/business-dimensions"
          className="bg-card hover:bg-accent ring-foreground/5 shadow-soft flex items-start gap-3 rounded-2xl p-5 ring-1 transition-colors"
        >
          <Layers className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">
              {t("settings.index.dimensions.title")}
            </p>
            <p className="text-muted-foreground text-xs">
              {t("settings.index.dimensions.desc")}
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        <Link
          href="/settings/users"
          className="bg-card hover:bg-accent ring-foreground/5 shadow-soft flex items-start gap-3 rounded-2xl p-5 ring-1 transition-colors"
        >
          <Users className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">
              {t("settings.index.users.title")}
            </p>
            <p className="text-muted-foreground text-xs">
              {t("settings.index.users.desc")}
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        <Link
          href="/settings/scheduled-briefings"
          className="bg-card hover:bg-accent ring-foreground/5 shadow-soft flex items-start gap-3 rounded-2xl p-5 ring-1 transition-colors"
        >
          <CalendarClock className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">
              {t("settings.index.briefings.title")}
            </p>
            <p className="text-muted-foreground text-xs">
              {t("settings.index.briefings.desc")}
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
      </div>

      {config.isLoading ? (
        <div className="space-y-6">
          <Skeleton className="h-64" />
          <Skeleton className="h-72" />
          <Skeleton className="h-56" />
        </div>
      ) : config.isError ? (
        <p className="text-destructive py-12 text-center text-sm">
          {t("settings.index.loadError")}
        </p>
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
