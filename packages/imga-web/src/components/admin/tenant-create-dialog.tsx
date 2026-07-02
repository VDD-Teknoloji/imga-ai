"use client";

import { CheckCircle2, Copy, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useCreateAdminTenant } from "@/hooks/use-admin-tenants";
import { ApiError } from "@/lib/api-client";
import { LOCALES, LOCALE_LABELS, type Locale } from "@/lib/i18n/config";
import { useTranslation } from "@/lib/i18n/use-translation";
import { autoSlug, isValidSlug } from "@/lib/slug";
import type { AutomationMode, TenantPlanTier } from "@/lib/types";
import { AUTOMATION_MODE_LABELS, PLAN_TIER_LABELS } from "@/lib/user-helpers";

interface TenantCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const PLAN_OPTIONS: ReadonlyArray<TenantPlanTier> = ["trial", "starter", "business", "enterprise"];

const AUTOMATION_OPTIONS: ReadonlyArray<AutomationMode> = ["manual", "semi_auto", "full_auto"];

/**
 * Two-mode dialog: form view collects tenant fields and (optionally)
 * an initial admin email/name; on success, swaps to a token-display
 * view that shows the plaintext invitation link with a copy button
 * (the token is server-side returned only once — must surface
 * clearly to the operator before they close).
 */
export function TenantCreateDialog({ open, onOpenChange }: TenantCreateDialogProps) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [planTier, setPlanTier] = useState<TenantPlanTier>("trial");
  const [automationMode, setAutomationMode] = useState<AutomationMode>("semi_auto");
  const [language, setLanguage] = useState<Locale>("tr");
  const [seedAdmin, setSeedAdmin] = useState(false);
  const { t } = useTranslation();
  const [adminEmail, setAdminEmail] = useState("");
  const [adminFullName, setAdminFullName] = useState("");

  const [successToken, setSuccessToken] = useState<string | null>(null);
  const [createdTenantName, setCreatedTenantName] = useState<string | null>(null);

  const create = useCreateAdminTenant();

  // Render-time conditional setState (Sprint 7.6.5 React 19 pattern):
  // reset everything when the dialog closes, including the success
  // state that may have been left from a prior open.
  const [lastOpen, setLastOpen] = useState(open);
  if (lastOpen !== open) {
    setLastOpen(open);
    if (!open) {
      setName("");
      setSlug("");
      setSlugTouched(false);
      setPlanTier("trial");
      setAutomationMode("semi_auto");
      setLanguage("tr");
      setSeedAdmin(false);
      setAdminEmail("");
      setAdminFullName("");
      setSuccessToken(null);
      setCreatedTenantName(null);
    }
  }

  // Auto-derive slug from name as long as the user hasn't manually
  // edited it. Once they type in the slug field, we stop overwriting.
  const effectiveSlug = slugTouched ? slug : autoSlug(name);

  const slugIsValid = effectiveSlug.length > 0 && isValidSlug(effectiveSlug);
  const formValid =
    name.trim().length > 0 &&
    slugIsValid &&
    (!seedAdmin || (adminEmail.trim().length > 0 && adminFullName.trim().length > 0));

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!formValid) return;
    try {
      const result = await create.mutateAsync({
        name: name.trim(),
        slug: effectiveSlug,
        plan_tier: planTier,
        automation_mode: automationMode,
        language,
        initial_admin: seedAdmin
          ? {
              email: adminEmail.trim(),
              full_name: adminFullName.trim(),
            }
          : undefined,
      });
      setCreatedTenantName(result.tenant.name);
      if (result.initial_invitation_token) {
        setSuccessToken(result.initial_invitation_token);
        toast.success(t("admin.tenantCreate.toast.createdTitle"), {
          description: t("admin.tenantCreate.toast.createdInvite"),
        });
      } else {
        toast.success(t("admin.tenantCreate.toast.createdTitle"));
        onOpenChange(false);
      }
    } catch (err) {
      toast.error(t("admin.tenantCreate.toast.createError"), {
        description: t(describeError(err)),
      });
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        {successToken && createdTenantName ? (
          <SuccessView
            tenantName={createdTenantName}
            token={successToken}
            onClose={() => onOpenChange(false)}
          />
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <DialogHeader>
              <DialogTitle>{t("admin.tenantCreate.title")}</DialogTitle>
              <DialogDescription>{t("admin.tenantCreate.desc")}</DialogDescription>
            </DialogHeader>

            <div className="space-y-2">
              <Label htmlFor="tenant-name">{t("admin.field.name")}</Label>
              <Input
                id="tenant-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Acme Inc."
                maxLength={255}
                required
                autoFocus
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="tenant-slug">{t("admin.field.slug")}</Label>
              <Input
                id="tenant-slug"
                value={effectiveSlug}
                onChange={(e) => {
                  setSlugTouched(true);
                  setSlug(e.target.value);
                }}
                placeholder="acme-inc"
                maxLength={64}
                aria-invalid={effectiveSlug.length > 0 && !slugIsValid ? "true" : undefined}
              />
              <p className="text-muted-foreground text-xs">{t("admin.tenantCreate.slugHelp")}</p>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="plan-tier">{t("admin.field.plan")}</Label>
                <Select value={planTier} onValueChange={(v) => setPlanTier(v as TenantPlanTier)}>
                  <SelectTrigger id="plan-tier">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PLAN_OPTIONS.map((p) => (
                      <SelectItem key={p} value={p}>
                        {PLAN_TIER_LABELS[p] ?? p}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="automation-mode">{t("admin.field.automation")}</Label>
                <Select
                  value={automationMode}
                  onValueChange={(v) => setAutomationMode(v as AutomationMode)}
                >
                  <SelectTrigger id="automation-mode">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {AUTOMATION_OPTIONS.map((m) => (
                      <SelectItem key={m} value={m}>
                        {AUTOMATION_MODE_LABELS[m]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="tenant-language">{t("tenant.language.label")}</Label>
              <Select value={language} onValueChange={(v) => setLanguage(v as Locale)}>
                <SelectTrigger id="tenant-language">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LOCALES.map((l) => (
                    <SelectItem key={l} value={l}>
                      {LOCALE_LABELS[l]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">{t("tenant.language.help")}</p>
            </div>

            <div className="space-y-3 rounded-md border p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="space-y-0.5">
                  <Label htmlFor="seed-admin">{t("admin.tenantCreate.seedAdminLabel")}</Label>
                  <p className="text-muted-foreground text-xs">
                    {t("admin.tenantCreate.seedAdminHelp")}
                  </p>
                </div>
                <Switch id="seed-admin" checked={seedAdmin} onCheckedChange={setSeedAdmin} />
              </div>
              {seedAdmin ? (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="admin-email">{t("admin.field.email")}</Label>
                    <Input
                      id="admin-email"
                      type="email"
                      value={adminEmail}
                      onChange={(e) => setAdminEmail(e.target.value)}
                      placeholder="alice@acme.com"
                      required={seedAdmin}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="admin-name">{t("admin.tenantCreate.fullName")}</Label>
                    <Input
                      id="admin-name"
                      value={adminFullName}
                      onChange={(e) => setAdminFullName(e.target.value)}
                      placeholder="Alice Smith"
                      maxLength={255}
                      required={seedAdmin}
                    />
                  </div>
                </div>
              ) : null}
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={create.isPending}
              >
                {t("admin.action.cancel")}
              </Button>
              <Button type="submit" disabled={!formValid || create.isPending} className="gap-2">
                {create.isPending
                  ? t("admin.tenantCreate.creating")
                  : t("admin.tenantCreate.create")}
                <Plus className="size-4" aria-hidden />
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

// --- success view (token reveal) -----------------------------------------

function SuccessView({
  tenantName,
  token,
  onClose,
}: {
  tenantName: string;
  token: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <CheckCircle2 className="size-5 text-emerald-600" aria-hidden />
          {t("admin.tenantCreate.success.title", { name: tenantName })}
        </DialogTitle>
        <DialogDescription>
          {t("admin.tenantCreate.success.desc1")}
          <strong>{t("admin.invite.onlyOnce")}</strong>
          {t("admin.tenantCreate.success.desc2")}
        </DialogDescription>
      </DialogHeader>

      <InviteLinkBlock token={token} />

      <DialogFooter>
        <Button onClick={onClose}>{t("admin.tenantCreate.success.done")}</Button>
      </DialogFooter>
    </div>
  );
}

interface InviteLinkBlockProps {
  token: string;
}

export function InviteLinkBlock({ token }: InviteLinkBlockProps) {
  const { t } = useTranslation();
  const url = inviteUrl(token);
  return (
    <div className="space-y-2">
      <Label className="text-xs">{t("admin.invite.linkLabel")}</Label>
      <div className="bg-muted/40 flex items-stretch gap-2 rounded-md border p-1">
        <code className="flex-1 self-center truncate px-2 font-mono text-xs">{url}</code>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="gap-1.5"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(url);
              toast.success(t("admin.invite.copied"));
            } catch {
              toast.error(t("admin.invite.copyFailed"));
            }
          }}
        >
          <Copy className="size-3.5" aria-hidden />
          {t("admin.invite.copy")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">{t("admin.invite.linkHelp")}</p>
    </div>
  );
}

function inviteUrl(token: string): string {
  // Browser-only: window.location.origin gives the current host so
  // staging / production / local all build the right link without
  // hardcoded URLs.
  if (typeof window !== "undefined") {
    return `${window.location.origin}/invite/${token}`;
  }
  return `/invite/${token}`;
}

/** i18n anahtarı döndürür; çağıran `t(...)` ile çevirir (describeError
 *  modül seviyesinde, hook erişimi yok). */
function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "admin.tenantCreate.error.slugTaken";
    if (err.status === 403) return "admin.error.superAdminRequired";
    if (err.status === 422) return "admin.error.invalidForm";
  }
  return "admin.error.unexpected";
}
