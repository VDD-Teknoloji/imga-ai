"use client";

// 2026-08-09 — /settings/integrations artık SALT OKUNUR.
//
// Yapay zekâ modeli ve API anahtarı yönetimi kurumdan alınıp IMGA'ya
// (süper yönetici) verildi; yönetim yüzeyi /admin/tenants/{id}/llm
// altında. Burada kurum yalnızca kendi adına neyin yapılandırıldığını
// görür: sağlayıcı, model, öncelik, durum ve maskeli anahtar
// önizlemesi. Ekleme / düzenleme / silme / sıralama arayüzü yok —
// backend'de o uçlar da kaldırıldı.

import { AlertTriangle, Info, Loader2 } from "lucide-react";

import { RequireRole } from "@/components/auth/require-role";
import { Badge } from "@/components/ui/badge";
import { useLlmCredentials } from "@/hooks/use-llm-credentials";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { LlmCredential } from "@/lib/types";
import { cn } from "@/lib/utils";

const PROVIDER_BADGE: Record<string, string> = {
  gemini: "Gemini",
  openrouter: "OpenRouter",
};

export default function IntegrationsPage() {
  return (
    <RequireRole level="admin">
      <IntegrationsPageInner />
    </RequireRole>
  );
}

function IntegrationsPageInner() {
  const list = useLlmCredentials();
  const credentials = list.data ?? [];
  const { t } = useTranslation();

  return (
    <main className="mx-auto w-full max-w-3xl space-y-6 p-6 md:p-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {t("settings.integrations.title")}
        </h1>
        <p className="text-muted-foreground text-sm">
          {t("settings.integrations.subtitle")}
        </p>
      </header>

      <ManagedByImgaNote />

      {list.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
        </div>
      ) : list.isError ? (
        <p className="text-destructive p-6 text-sm">
          {t("settings.integrations.loadError")}
        </p>
      ) : credentials.length === 0 ? (
        <EmptyState />
      ) : (
        <ul className="space-y-2">
          {credentials.map((cred, idx) => (
            <CredentialRow key={cred.id} credential={cred} index={idx} />
          ))}
        </ul>
      )}
    </main>
  );
}

function ManagedByImgaNote() {
  const { t } = useTranslation();
  return (
    <div className="bg-muted/40 flex items-start gap-3 rounded-lg border p-4">
      <Info className="text-muted-foreground mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="space-y-1 text-sm">
        <p className="font-medium">{t("settings.integrations.managedTitle")}</p>
        <p className="text-muted-foreground">
          {t("settings.integrations.managedDesc")}
        </p>
      </div>
    </div>
  );
}

function EmptyState() {
  const { t } = useTranslation();
  return (
    <div className="bg-card rounded-lg border border-dashed p-8 text-center">
      <p className="text-muted-foreground text-sm">
        {t("settings.integrations.empty")}
      </p>
    </div>
  );
}

function CredentialRow({
  credential,
  index,
}: {
  credential: LlmCredential;
  index: number;
}) {
  const { t } = useTranslation();
  return (
    <li className="bg-card space-y-1 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{credential.label}</span>
        <Badge variant="outline" className="text-xs">
          {index === 0
            ? t("settings.integrations.primary")
            : t("settings.integrations.backup", { n: index })}
        </Badge>
        <Badge
          variant="outline"
          className={cn(
            "text-xs",
            credential.provider === "openrouter"
              ? "border-violet-300 bg-violet-50 text-violet-700"
              : "border-sky-300 bg-sky-50 text-sky-700",
          )}
        >
          {PROVIDER_BADGE[credential.provider] ?? credential.provider}
        </Badge>
        <Badge variant={credential.is_active ? "secondary" : "outline"} className="text-xs">
          {credential.is_active
            ? t("settings.integrations.statusActive")
            : t("settings.integrations.statusInactive")}
        </Badge>
        {credential.last_failed_at && (
          <Badge
            variant="outline"
            className="border-amber-400 bg-amber-50 text-xs text-amber-700"
            title={t("settings.integrations.lastFailed", {
              date: new Date(credential.last_failed_at).toLocaleString("tr-TR"),
            })}
          >
            <AlertTriangle className="mr-1 size-3" aria-hidden />
            {t("settings.integrations.warning")}
          </Badge>
        )}
      </div>
      <p className="text-muted-foreground font-mono text-xs">
        {credential.value_preview}
      </p>
      <p className="text-muted-foreground text-xs">
        {t("settings.integrations.modelField")}:{" "}
        <span className="font-mono">
          {credential.model ?? t("settings.integrations.modelDefault")}
        </span>
      </p>
    </li>
  );
}
