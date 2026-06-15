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
import type { AdminTenantSummary, UserTenantRole } from "@/lib/types";
import { USER_ROLE_LABELS } from "@/lib/user-helpers";

interface TenantInviteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tenant: AdminTenantSummary;
}

const ROLE_OPTIONS: ReadonlyArray<UserTenantRole> = [
  "tenant_admin",
  "analyst",
  "viewer",
];

/**
 * Per-row "Davet" action on the admin tenants table. POSTs to
 * /admin/tenants/{id}/invitations and swaps to a token-display view
 * on success — same pattern as the create dialog's seeded admin
 * branch, reusing InviteLinkBlock for visual consistency.
 */
export function TenantInviteDialog({
  open,
  onOpenChange,
  tenant,
}: TenantInviteDialogProps) {
  const create = useCreateAdminInvitation();
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
      toast.success("Davet hazır", { description: `${tenant.name} için.` });
    } catch (err) {
      toast.error("Davet oluşturulamadı", { description: describeError(err) });
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {token ? (
          <div className="space-y-4">
            <DialogHeader>
              <DialogTitle>Davet hazır</DialogTitle>
              <DialogDescription>
                Bu link sadece <strong>tek sefer</strong> gösterilir —
                modal&apos;ı kapatmadan davet edilenle paylaş. 7 gün
                geçerli.
              </DialogDescription>
            </DialogHeader>
            <InviteLinkBlock token={token} />
            <DialogFooter>
              <Button onClick={() => onOpenChange(false)}>Tamam</Button>
            </DialogFooter>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <DialogHeader>
              <DialogTitle>{tenant.name} için davet</DialogTitle>
              <DialogDescription>
                Davet edilecek e-posta ve rolü seç. Token tek seferlik
                gösterilir, doğrudan kullanıcıyla paylaşmak için.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-2">
              <Label htmlFor="invite-email">E-posta</Label>
              <Input
                id="invite-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="kullanici@firma.com"
                required
                autoFocus
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="invite-role">Rol</Label>
              <Select
                value={role}
                onValueChange={(v) => setRole(v as UserTenantRole)}
              >
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
                Vazgeç
              </Button>
              <Button
                type="submit"
                disabled={
                  create.isPending || email.trim().length === 0
                }
                className="gap-2"
              >
                {create.isPending ? "Hazırlanıyor..." : "Davet oluştur"}
                <MailPlus className="size-4" aria-hidden />
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return "Yetkin yok.";
    if (err.status === 404) return "Kurum bulunamadı.";
    if (err.status === 409) return "Bu e-posta için zaten açık davet var.";
    if (err.status === 422) return "E-posta geçersiz.";
  }
  return "Beklenmeyen bir hata oluştu.";
}
