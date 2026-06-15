"use client";

import { CheckCircle2, MailCheck } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
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
import { useInvitationPreview } from "@/hooks/use-invitation";
import { ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import type { UserTenantRole } from "@/lib/types";
import { USER_ROLE_LABELS } from "@/lib/user-helpers";

interface TenantInviteAcceptDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * "Yeni davet kabul et" — paste a token, the active session re-auths
 * with their password, the tenant lands in availableTenants.
 *
 * Two-step flow inside one modal:
 *
 *   1. Token field. On change (debounced via React Query staleTime),
 *      hit /preview. The preview card shows tenant + role + invited
 *      email so the user can confirm before committing.
 *   2. Password field appears once the preview resolves. "Kabul et"
 *      runs /accept-existing through `joinTenantViaInvitation`,
 *      which replays the new token pair.
 *
 * If the invited email doesn't match the active session's email we
 * surface a 403 from the backend — caller must use the public
 * /invite/[token] page (link offered in the error toast).
 */
export function TenantInviteAcceptDialog({
  open,
  onOpenChange,
}: TenantInviteAcceptDialogProps) {
  const user = useAuthStore((s) => s.user);
  const joinTenant = useAuthStore((s) => s.joinTenantViaInvitation);

  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Reset form when the dialog closes, render-time conditional
  // setState (Sprint 7.6.5 React 19 pattern). useEffect would also
  // work here but render-time is the project standard.
  const [lastOpen, setLastOpen] = useState(open);
  if (lastOpen !== open) {
    setLastOpen(open);
    if (!open) {
      setToken("");
      setPassword("");
      setSubmitting(false);
    }
  }

  // Only kick the preview fetch once the user has typed something
  // resembling a token — invitation tokens are generated 64-char hex
  // by the backend, but we keep the threshold loose (>=24) to catch
  // pasted variants without spamming the rate limit on every keystroke.
  const previewToken = token.trim().length >= 24 ? token.trim() : undefined;
  const preview = useInvitationPreview(previewToken);

  // Best-effort warning when the token previewed for a different
  // email than the current session: the accept-existing endpoint will
  // 403 anyway, but flagging early is friendlier.
  useEffect(() => {
    if (!preview.data || !user) return;
    if (preview.data.invited_email.toLowerCase() !== user.email.toLowerCase()) {
      toast.warning("Bu davet farklı bir e-posta için", {
        description: `Davet ${preview.data.invited_email} için. Bu modal sadece kendi davetlerini kabul etmek içindir.`,
      });
    }
  }, [preview.data, user]);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (preview.data === undefined) return;
    setSubmitting(true);
    try {
      await joinTenant(token.trim(), password);
      toast.success("Davet kabul edildi", {
        description: `${preview.data.tenant_name} artık kurum listende.`,
      });
      onOpenChange(false);
    } catch (err) {
      toast.error("Davet kabul edilemedi", {
        description: describeError(err),
      });
    } finally {
      setSubmitting(false);
    }
  }

  const previewIsForOtherEmail =
    preview.data !== undefined &&
    user !== null &&
    preview.data.invited_email.toLowerCase() !== user.email.toLowerCase();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Yeni davet kabul et</DialogTitle>
          <DialogDescription>
            Davet linkindeki token&apos;ı yapıştır, mevcut hesabınla yeni
            kuruma katıl.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="invite-token">Davet token&apos;ı</Label>
            <Input
              id="invite-token"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="abc123def456..."
              autoComplete="off"
              spellCheck={false}
              disabled={submitting}
            />
          </div>

          {preview.isLoading && previewToken ? (
            <p className="text-muted-foreground text-xs">
              Davet kontrol ediliyor...
            </p>
          ) : null}
          {preview.isError && previewToken ? (
            <p className="text-destructive text-xs">
              Bu token geçersiz, süresi dolmuş veya kullanılmış.
            </p>
          ) : null}
          {preview.data ? (
            <div className="bg-muted/40 space-y-1.5 rounded-md border p-3 text-xs">
              <div className="flex items-center gap-2">
                <span className="font-medium">{preview.data.tenant_name}</span>
                <Badge variant="secondary" className="ml-auto">
                  {USER_ROLE_LABELS[preview.data.role as UserTenantRole]}
                </Badge>
              </div>
              <div className="text-muted-foreground flex items-center gap-1.5">
                <MailCheck className="size-3.5" aria-hidden />
                {preview.data.invited_email}
              </div>
              {previewIsForOtherEmail ? (
                <p className="text-amber-700 dark:text-amber-400">
                  ⚠ Davet bu hesap için değil. Kabul edilmeyecek.
                </p>
              ) : null}
            </div>
          ) : null}

          {preview.data && !previewIsForOtherEmail ? (
            <div className="space-y-2">
              <Label htmlFor="confirm-password">Şifren</Label>
              <Input
                id="confirm-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
                disabled={submitting}
              />
              <p className="text-muted-foreground text-xs">
                Güvenlik için yeni kuruma katılırken şifrenle doğrulan.
              </p>
            </div>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              Vazgeç
            </Button>
            <Button
              type="submit"
              disabled={
                submitting ||
                !preview.data ||
                previewIsForOtherEmail ||
                password === ""
              }
              className="gap-2"
            >
              {submitting ? "Kabul ediliyor..." : "Daveti kabul et"}
              <CheckCircle2 className="size-4" aria-hidden />
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return "Şifre hatalı.";
    if (err.status === 403) return "Bu davet farklı bir e-posta için.";
    if (err.status === 404)
      return "Davet geçersiz, süresi dolmuş veya zaten kullanılmış.";
  }
  return "Beklenmeyen bir hata oluştu.";
}
