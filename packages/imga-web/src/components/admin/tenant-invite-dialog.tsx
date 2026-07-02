"use client";

import { MailPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { InviteLinkBlock } from "@/components/admin/tenant-create-dialog";
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
import { useCreateAdminInvitation } from "@/hooks/use-admin-tenants";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { AdminTenantSummary, UserTenantRole } from "@/lib/types";
import { USER_ROLE_LABELS } from "@/lib/user-helpers";

interface TenantInviteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tenant: AdminTenantSummary;
}

const ROLE_OPTIONS: ReadonlyArray<UserTenantRole> = ["tenant_admin", "analyst", "viewer"];

/**
 * Per-row "Davet" action on the admin tenants table. POSTs to
 * /admin/tenants/{id}/invitations and swaps to a token-display view
 * on success — same pattern as the create dialog's seeded admin
 * branch, reusing InviteLinkBlock for visual consistency.
 */
export function TenantInviteDialog({ open, onOpenChange, tenant }: TenantInviteDialogProps) {
  const create = useCreateAdminInvitation();
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<UserTenantRole>("analyst");
  const [token, setToken] = useState<string | null>(null);

  // Reset on close — render-time conditional setState pattern.
  const [lastOpen, setLastOpen] = useState(open);
  if (lastOpen !== open) {
    setLastOpen(open);
    if (!open) {
      setEmail("");
      setRole("analyst");
      setToken(null);
    }
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    try {
      const result = await create.mutateAsync({
        tenantId: tenant.id,
        body: { email: email.trim(), role },
      });
      setToken(result.token);
      toast.success(t("admin.tenantInvite.ready"), {
        description: t("admin.tenantInvite.toast.readyDesc", {
          name: tenant.name,
        }),
      });
    } catch (err) {
      toast.error(t("admin.tenantInvite.toast.error"), {
        description: t(describeError(err)),
      });
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {token ? (
          <div className="space-y-4">
            <DialogHeader>
              <DialogTitle>{t("admin.tenantInvite.ready")}</DialogTitle>
              <DialogDescription>
                {t("admin.tenantInvite.ready.desc1")}
                <strong>{t("admin.invite.onlyOnce")}</strong>
                {t("admin.tenantInvite.ready.desc2")}
              </DialogDescription>
            </DialogHeader>
            <InviteLinkBlock token={token} />
            <DialogFooter>
              <Button onClick={() => onOpenChange(false)}>{t("admin.action.ok")}</Button>
            </DialogFooter>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <DialogHeader>
              <DialogTitle>{t("admin.tenantInvite.title", { name: tenant.name })}</DialogTitle>
              <DialogDescription>{t("admin.tenantInvite.desc")}</DialogDescription>
            </DialogHeader>

            <div className="space-y-2">
              <Label htmlFor="invite-email">{t("admin.field.email")}</Label>
              <Input
                id="invite-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t("admin.tenantInvite.emailPlaceholder")}
                required
                autoFocus
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="invite-role">{t("admin.tenantInvite.role")}</Label>
              <Select value={role} onValueChange={(v) => setRole(v as UserTenantRole)}>
                <SelectTrigger id="invite-role">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ROLE_OPTIONS.map((r) => (
                    <SelectItem key={r} value={r}>
                      {USER_ROLE_LABELS[r]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
              <Button
                type="submit"
                disabled={create.isPending || email.trim().length === 0}
                className="gap-2"
              >
                {create.isPending
                  ? t("admin.tenantInvite.preparing")
                  : t("admin.tenantInvite.create")}
                <MailPlus className="size-4" aria-hidden />
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** i18n anahtarı döndürür; çağıran `t(...)` ile çevirir. */
function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return "admin.tenantInvite.error.forbidden";
    if (err.status === 404) return "admin.error.notFound";
    if (err.status === 409) return "admin.tenantInvite.error.duplicate";
    if (err.status === 422) return "admin.tenantInvite.error.invalidEmail";
  }
  return "admin.error.unexpected";
}
