"use client";

// Sprint 9.5 A1 — /settings/users.
//
// Tenant member directory + invitation management. Three sections:
//   1. Mevcut üyeler — read-only list of active members, role badge.
//   2. Yeni davet gönder — form (email + role), shows the resulting
//      invitation URL exactly once (the plaintext token leaves the
//      backend only on the initial 201 response).
//   3. Bekleyen davetler — list of unaccepted invitations with revoke.
//
// Member role change + remove-from-tenant are intentionally out of
// scope for this commit: they need new backend routes and Sprint 9.5
// targets unblocking the "operator can't invite users" production
// gap. Role-change UI lands in a follow-up sprint.

import { Copy, Loader2, Trash2, UserPlus, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { ForbiddenNotice } from "@/components/settings/forbidden-notice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useCreateInvitation,
  useRevokeInvitation,
  useTenantInvitations,
  useTenantMembers,
} from "@/hooks/use-tenant-users";
import { ApiError, formatApiErrorMessage } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import type { UserTenantRole } from "@/lib/types";

const ROLE_LABEL: Record<string, string> = {
  tenant_admin: "Yönetici",
  analyst: "Analist",
  viewer: "İzleyici",
};

export default function SettingsUsersPage() {
  const role = useAuthStore((s) => s.activeContext?.role);
  const tenantId = useAuthStore((s) => s.activeContext?.tenant_id ?? null);
  const isSuperAdmin = useAuthStore((s) => s.user?.is_super_admin ?? false);

  const isAdmin = role === "tenant_admin" || isSuperAdmin;
  if (!isAdmin) return <ForbiddenNotice />;

  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-start gap-2">
        <Users className="text-primary mt-1 size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            Kullanıcılar
          </h1>
          <p className="text-muted-foreground text-sm">
            Tenant&apos;a kayıtlı kullanıcılar ve bekleyen davetler.
          </p>
        </div>
      </header>

      <MembersSection />
      <InviteForm tenantId={tenantId} />
      <PendingInvitationsSection tenantId={tenantId} />
    </main>
  );
}

function MembersSection() {
  const { data, isLoading, isError } = useTenantMembers();
  const members = data?.members ?? [];

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold">Mevcut üyeler</h2>
      {isLoading ? (
        <Skeleton className="h-24" />
      ) : isError ? (
        <p className="text-destructive text-sm">Üye listesi alınamadı.</p>
      ) : members.length === 0 ? (
        <Card>
          <CardContent className="text-muted-foreground p-6 text-center text-sm">
            Henüz üye yok.
          </CardContent>
        </Card>
      ) : (
        <ul className="space-y-2">
          {members.map((m) => (
            <li
              key={m.user_id}
              className="bg-card flex items-center gap-3 rounded-lg border p-3"
            >
              <div className="flex-1 space-y-0.5">
                <p className="text-sm font-medium">{m.full_name}</p>
                <p className="text-muted-foreground text-xs">{m.email}</p>
              </div>
              <Badge variant="outline" className="text-xs">
                {ROLE_LABEL[m.role] ?? m.role}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function InviteForm({ tenantId }: { tenantId: string | null }) {
  const create = useCreateInvitation(tenantId);
  const [email, setEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<UserTenantRole>("analyst");
  // Sprint 9.5 A1 — the plaintext token is returned exactly once.
  // The user must copy the link before navigating away; once this state
  // clears, there's no way to retrieve it (by design — a stale token
  // sitting in the UI is a credential-leak vector).
  const [lastToken, setLastToken] = useState<{
    email: string;
    url: string;
  } | null>(null);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) {
      toast.error("E-posta zorunlu.");
      return;
    }
    if (!tenantId) {
      toast.error("Aktif tenant bulunamadı.");
      return;
    }
    create.mutate(
      { email: email.trim(), role: inviteRole },
      {
        onSuccess: (resp) => {
          const url = `${window.location.origin}/invitations/${resp.token}`;
          setLastToken({ email: resp.email, url });
          setEmail("");
          toast.success("Davet oluşturuldu.");
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            toast.error("Bu e-posta için açık davet zaten var.");
          } else {
            toast.error(formatApiErrorMessage(err));
          }
        },
      },
    );
  }

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold">Yeni davet gönder</h2>
      <Card>
        <CardContent className="space-y-3 p-4">
          <form onSubmit={onSubmit} className="grid gap-3 md:grid-cols-[1fr_auto_auto]">
            <div className="space-y-1">
              <Label className="text-xs">E-posta</Label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="kullanici@sirket.com"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Rol</Label>
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value as UserTenantRole)}
                className="border-input bg-background w-full rounded-md border px-2 py-1.5 text-sm"
              >
                <option value="tenant_admin">Yönetici</option>
                <option value="analyst">Analist</option>
                <option value="viewer">İzleyici</option>
              </select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs invisible">Gönder</Label>
              <Button
                type="submit"
                disabled={create.isPending}
                className="gap-1.5"
              >
                {create.isPending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <UserPlus className="size-4" aria-hidden />
                )}
                Davet et
              </Button>
            </div>
          </form>

          {lastToken && (
            <div className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-xs dark:border-emerald-900 dark:bg-emerald-950/30">
              <p className="mb-1 font-medium">
                {lastToken.email} için davet bağlantısı (tek seferlik):
              </p>
              <div className="flex items-center gap-2">
                <code className="flex-1 truncate font-mono text-[11px]">
                  {lastToken.url}
                </code>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    navigator.clipboard.writeText(lastToken.url);
                    toast.success("Kopyalandı.");
                  }}
                  className="gap-1"
                >
                  <Copy className="size-3.5" aria-hidden /> Kopyala
                </Button>
              </div>
              <p className="text-muted-foreground mt-1">
                Bu bağlantıyı şimdi davet ettiğiniz kişiye iletin —
                kapatınca bir daha gösterilmez.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

function PendingInvitationsSection({ tenantId }: { tenantId: string | null }) {
  const { data, isLoading, isError } = useTenantInvitations(tenantId, false);
  const pending = useMemo(
    () => (data?.invitations ?? []).filter((i) => !i.accepted_at),
    [data],
  );

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold">Bekleyen davetler</h2>
      {isLoading ? (
        <Skeleton className="h-24" />
      ) : isError ? (
        <p className="text-destructive text-sm">Davet listesi alınamadı.</p>
      ) : pending.length === 0 ? (
        <Card>
          <CardContent className="text-muted-foreground p-6 text-center text-sm">
            Bekleyen davet yok.
          </CardContent>
        </Card>
      ) : (
        <ul className="space-y-2">
          {pending.map((inv) => (
            <PendingInvitationRow key={inv.id} inv={inv} tenantId={tenantId} />
          ))}
        </ul>
      )}
    </section>
  );
}

function PendingInvitationRow({
  inv,
  tenantId,
}: {
  inv: { id: string; email: string; role: string; expires_at: string };
  tenantId: string | null;
}) {
  const revoke = useRevokeInvitation(tenantId);
  return (
    <li className="bg-card flex items-center gap-3 rounded-lg border p-3">
      <div className="flex-1 space-y-0.5">
        <p className="text-sm font-medium">{inv.email}</p>
        <p className="text-muted-foreground text-xs">
          {ROLE_LABEL[inv.role] ?? inv.role} · Son geçerlilik:{" "}
          {new Date(inv.expires_at).toLocaleDateString("tr-TR")}
        </p>
      </div>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          if (!confirm("Daveti iptal etmek istediğinizden emin misiniz?"))
            return;
          revoke.mutate(inv.id, {
            onSuccess: () => toast.success("Davet iptal edildi."),
            onError: (err) => toast.error(formatApiErrorMessage(err)),
          });
        }}
        disabled={revoke.isPending}
        className="gap-1 text-red-700 hover:text-red-900"
      >
        <Trash2 className="size-3.5" aria-hidden /> İptal
      </Button>
    </li>
  );
}
