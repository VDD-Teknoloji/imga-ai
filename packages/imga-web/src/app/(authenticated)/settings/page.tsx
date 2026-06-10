"use client";

import {
  ArrowRight,
  Building2,
  CalendarClock,
  KeyRound,
  Layers,
  ShieldAlert,
  Tags,
  Target,
  Users,
} from "lucide-react";
import Link from "next/link";
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
    <main className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6 md:p-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Ayarlar</h1>
        <p className="text-muted-foreground text-sm">
          Tenant yapılandırması — otomasyon politikası, kategori taksonomisi.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Link
          href="/settings/profile"
          className="bg-card hover:bg-accent flex items-start gap-3 rounded-lg border p-4 transition-colors"
        >
          <Building2 className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">Şirket Profili</p>
            <p className="text-muted-foreground text-xs">
              Sektör, büyüklük ve iş tanımı — strateji raporları için bağlam.
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        <Link
          href="/settings/integrations"
          className="bg-card hover:bg-accent flex items-start gap-3 rounded-lg border p-4 transition-colors"
        >
          <KeyRound className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">Gemini API Anahtarları</p>
            <p className="text-muted-foreground text-xs">
              Strateji raporları için API anahtar yönetimi ve önceliklendirme.
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        <Link
          href="/admin/prompt-templates"
          className="bg-card hover:bg-accent flex items-start gap-3 rounded-lg border p-4 transition-colors"
        >
          <KeyRound className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">Yapay Zeka Prompt&apos;ları</p>
            <p className="text-muted-foreground text-xs">
              SWOT, OKR, Yönetici Özeti ve yorum sınıflandırma
              prompt&apos;larını düzenleyin — deploy gerekmez.
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        <Link
          href="/settings/taxonomies"
          className="bg-card hover:bg-accent flex items-start gap-3 rounded-lg border p-4 transition-colors"
        >
          <Tags className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">Şikayet Kategorileri</p>
            <p className="text-muted-foreground text-xs">
              Şirket-perspektifi taksonomisi — etiket, anahtar kelime, sıralama.
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        <Link
          href="/settings/sla-rules"
          className="bg-card hover:bg-accent flex items-start gap-3 rounded-lg border p-4 transition-colors"
        >
          <ShieldAlert className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">SLA Kuralları</p>
            <p className="text-muted-foreground text-xs">
              Yanıt/çözüm sürelerini koşullara göre yönet (uyarı şu an aktif).
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        {/* Sprint 9.4 I — three Sprint 9.2/9.3 surfaces that were
            URL-only secrets before now show up in the index. */}
        <Link
          href="/settings/kpi-goals"
          className="bg-card hover:bg-accent flex items-start gap-3 rounded-lg border p-4 transition-colors"
        >
          <Target className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">KPI Hedefleri</p>
            <p className="text-muted-foreground text-xs">
              NPS / hacim / manuel inceleme oranı için dönemsel hedef
              koy; dashboard kartları başarımı bu sayıyla ölçer.
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        <Link
          href="/settings/business-dimensions"
          className="bg-card hover:bg-accent flex items-start gap-3 rounded-lg border p-4 transition-colors"
        >
          <Layers className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">İş Boyutları</p>
            <p className="text-muted-foreground text-xs">
              Segment / ürün hattı / kanal / müşteri tier&apos;ı — CSV
              upload eşleştirmesi + dashboard kırılımı.
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        <Link
          href="/settings/users"
          className="bg-card hover:bg-accent flex items-start gap-3 rounded-lg border p-4 transition-colors"
        >
          <Users className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">Kullanıcılar</p>
            <p className="text-muted-foreground text-xs">
              Tenant üyeleri + davet gönderme / iptal etme.
            </p>
          </div>
          <ArrowRight className="text-muted-foreground size-4" aria-hidden />
        </Link>
        <Link
          href="/settings/scheduled-briefings"
          className="bg-card hover:bg-accent flex items-start gap-3 rounded-lg border p-4 transition-colors"
        >
          <CalendarClock className="text-primary mt-0.5 size-5" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-medium">Zamanlanmış Brifingler</p>
            <p className="text-muted-foreground text-xs">
              Haftalık / aylık otomatik yönetici brifingi; alıcı listesi
              + manuel &quot;Şimdi gönder&quot; testi.
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
