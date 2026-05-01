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
import { autoSlug, isValidSlug } from "@/lib/slug";
import type { AutomationMode, TenantPlanTier } from "@/lib/types";
import { AUTOMATION_MODE_LABELS, PLAN_TIER_LABELS } from "@/lib/user-helpers";

interface TenantCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const PLAN_OPTIONS: ReadonlyArray<TenantPlanTier> = [
  "trial",
  "starter",
  "business",
  "enterprise",
];

const AUTOMATION_OPTIONS: ReadonlyArray<AutomationMode> = [
  "manual",
  "semi_auto",
  "full_auto",
];

/**
 * Two-mode dialog: form view collects tenant fields and (optionally)
 * an initial admin email/name; on success, swaps to a token-display
 * view that shows the plaintext invitation link with a copy button
 * (the token is server-side returned only once — must surface
 * clearly to the operator before they close).
 */
export function TenantCreateDialog({
  open,
  onOpenChange,
}: TenantCreateDialogProps) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [planTier, setPlanTier] = useState<TenantPlanTier>("trial");
  const [automationMode, setAutomationMode] =
    useState<AutomationMode>("semi_auto");
  const [seedAdmin, setSeedAdmin] = useState(false);
  const [adminEmail, setAdminEmail] = useState("");
  const [adminFullName, setAdminFullName] = useState("");

  const [successToken, setSuccessToken] = useState<string | null>(null);
  const [createdTenantName, setCreatedTenantName] = useState<string | null>(
    null,
  );

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
    (!seedAdmin ||
      (adminEmail.trim().length > 0 && adminFullName.trim().length > 0));

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!formValid) return;
    try {
      const result = await create.mutateAsync({
        name: name.trim(),
        slug: effectiveSlug,
        plan_tier: planTier,
        automation_mode: automationMode,
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
        toast.success("Tenant oluşturuldu", {
          description: "İlk admin daveti hazır — linki paylaşın.",
        });
      } else {
        toast.success("Tenant oluşturuldu");
        onOpenChange(false);
      }
    } catch (err) {
      toast.error("Tenant oluşturulamadı", {
        description: describeError(err),
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
              <DialogTitle>Yeni tenant</DialogTitle>
              <DialogDescription>
                İsim ve slug zorunlu. Opsiyonel olarak ilk admin daveti
                aynı işlemde oluşturulabilir.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-2">
              <Label htmlFor="tenant-name">İsim</Label>
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
              <Label htmlFor="tenant-slug">Slug</Label>
              <Input
                id="tenant-slug"
                value={effectiveSlug}
                onChange={(e) => {
                  setSlugTouched(true);
                  setSlug(e.target.value);
                }}
                placeholder="acme-inc"
                maxLength={64}
                aria-invalid={
                  effectiveSlug.length > 0 && !slugIsValid
                    ? "true"
                    : undefined
                }
              />
              <p className="text-muted-foreground text-xs">
                URL&apos;de görünür. Sadece lowercase harf, rakam ve tire.
                Sonradan değiştirilemez.
              </p>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="plan-tier">Plan</Label>
                <Select
                  value={planTier}
                  onValueChange={(v) => setPlanTier(v as TenantPlanTier)}
                >
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
                <Label htmlFor="automation-mode">Otomasyon</Label>
                <Select
                  value={automationMode}
                  onValueChange={(v) =>
                    setAutomationMode(v as AutomationMode)
                  }
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

            <div className="space-y-3 rounded-md border p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="space-y-0.5">
                  <Label htmlFor="seed-admin">İlk admin daveti gönder</Label>
                  <p className="text-muted-foreground text-xs">
                    Tenant oluşturulurken davet token&apos;ı üretilir.
                  </p>
                </div>
                <Switch
                  id="seed-admin"
                  checked={seedAdmin}
                  onCheckedChange={setSeedAdmin}
                />
              </div>
              {seedAdmin ? (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="admin-email">E-posta</Label>
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
                    <Label htmlFor="admin-name">Tam ad</Label>
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
                Vazgeç
              </Button>
              <Button
                type="submit"
                disabled={!formValid || create.isPending}
                className="gap-2"
              >
                {create.isPending ? "Oluşturuluyor..." : "Oluştur"}
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
  return (
    <div className="space-y-4">
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <CheckCircle2 className="size-5 text-emerald-600" aria-hidden />
          {tenantName} oluşturuldu
        </DialogTitle>
        <DialogDescription>
          İlk admin için davet linki hazır. Bu link sadece <strong>tek
          sefer</strong> gösterilir — modal&apos;ı kapatmadan paylaş.
        </DialogDescription>
      </DialogHeader>

      <InviteLinkBlock token={token} />

      <DialogFooter>
        <Button onClick={onClose}>Tamam, paylaştım</Button>
      </DialogFooter>
    </div>
  );
}

interface InviteLinkBlockProps {
  token: string;
}

export function InviteLinkBlock({ token }: InviteLinkBlockProps) {
  const url = inviteUrl(token);
  return (
    <div className="space-y-2">
      <Label className="text-xs">Davet linki</Label>
      <div className="bg-muted/40 flex items-stretch gap-2 rounded-md border p-1">
        <code className="flex-1 truncate self-center px-2 font-mono text-xs">
          {url}
        </code>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="gap-1.5"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(url);
              toast.success("Link kopyalandı");
            } catch {
              toast.error("Kopyalanamadı; manuel seç ve kopyala.");
            }
          }}
        >
          <Copy className="size-3.5" aria-hidden />
          Kopyala
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">
        Bu linki davet edilenle paylaşın. 7 gün geçerli.
      </p>
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

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "Bu slug zaten kullanılıyor.";
    if (err.status === 403) return "Bu işlem için süper-yönetici yetkisi gerekli.";
    if (err.status === 422) return "Form alanları geçersiz.";
  }
  return "Beklenmeyen bir hata oluştu.";
}
