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

import { RequireRole } from "@/components/auth/require-role";
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
import { useTranslation } from "@/lib/i18n/use-translation";
import type { UserTenantRole } from "@/lib/types";

const ROLE_KEY: Record<string, string> = {
  tenant_admin: "settings.users.role.admin",
  analyst: "settings.users.role.analyst",
  viewer: "settings.users.role.viewer",
};

function roleLabel(
  role: string,
  t: (key: string, vars?: Record<string, string | number>) => string,
): string {
  const key = ROLE_KEY[role];
  return key ? t(key) : role;
}

export default function SettingsUsersPage() {
  return (
    <RequireRole level="admin">
      <SettingsUsersPageInner />
    </RequireRole>
  );
}

function SettingsUsersPageInner() {
  const tenantId = useAuthStore((s) => s.activeContext?.tenant_id ?? null);
  const { t } = useTranslation();

  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-start gap-2">
        <Users className="text-primary mt-1 size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {t("settings.users.title")}
          </h1>
          <p className="text-muted-foreground text-sm">
            {t("settings.users.subtitle")}
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
  const { t } = useTranslation();

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold">
        {t("settings.users.currentMembers")}
      </h2>
      {isLoading ? (
        <Skeleton className="h-24" />
      ) : isError ? (
        <p className="text-destructive text-sm">
          {t("settings.users.membersError")}
        </p>
      ) : members.length === 0 ? (
        <Card>
          <CardContent className="text-muted-foreground p-6 text-center text-sm">
            {t("settings.users.noMembers")}
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
                {roleLabel(m.role, t)}
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
  const { t } = useTranslation();
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
      toast.error(t("settings.users.emailRequired"));
      return;
    }
    if (!tenantId) {
      toast.error(t("settings.users.noActiveOrg"));
      return;
    }
    create.mutate(
      { email: email.trim(), role: inviteRole },
      {
        onSuccess: (resp) => {
          // Kabul sayfasinin route'u /invite/[token] — /invitations/ 404
          // veriyordu (UAT HATA-05).
          const url = `${window.location.origin}/invite/${resp.token}`;
          setLastToken({ email: resp.email, url });
          setEmail("");
          toast.success(t("settings.users.inviteCreated"));
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            toast.error(t("settings.users.inviteExists"));
          } else {
            toast.error(formatApiErrorMessage(err));
          }
        },
      },
    );
  }

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold">{t("settings.users.newInvite")}</h2>
      <Card>
        <CardContent className="space-y-3 p-4">
          <form onSubmit={onSubmit} className="grid gap-3 md:grid-cols-[1fr_auto_auto]">
            <div className="space-y-1">
              <Label className="text-xs">{t("settings.users.email")}</Label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder={t("settings.users.emailPlaceholder")}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">{t("settings.users.role")}</Label>
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value as UserTenantRole)}
                className="border-input bg-background w-full rounded-md border px-2 py-1.5 text-sm"
              >
                <option value="tenant_admin">{t("settings.users.role.admin")}</option>
                <option value="analyst">{t("settings.users.role.analyst")}</option>
                <option value="viewer">{t("settings.users.role.viewer")}</option>
              </select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs invisible">{t("settings.users.send")}</Label>
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
                {t("settings.users.invite")}
              </Button>
            </div>
          </form>

          {lastToken && (
            <div className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-xs dark:border-emerald-900 dark:bg-emerald-950/30">
              <p className="mb-1 font-medium">
                {t("settings.users.inviteLinkLabel", { email: lastToken.email })}
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
                    toast.success(t("settings.users.copied"));
                  }}
                  className="gap-1"
                >
                  <Copy className="size-3.5" aria-hidden /> {t("settings.users.copy")}
                </Button>
              </div>
              <p className="text-muted-foreground mt-1">
                {t("settings.users.inviteLinkHelp")}
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
  const { t } = useTranslation();
  const pending = useMemo(
    () => (data?.invitations ?? []).filter((i) => !i.accepted_at),
    [data],
  );

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold">
        {t("settings.users.pendingInvites")}
      </h2>
      {isLoading ? (
        <Skeleton className="h-24" />
      ) : isError ? (
        <p className="text-destructive text-sm">
          {t("settings.users.invitesError")}
        </p>
      ) : pending.length === 0 ? (
        <Card>
          <CardContent className="text-muted-foreground p-6 text-center text-sm">
            {t("settings.users.noPending")}
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
  const { t } = useTranslation();
  return (
    <li className="bg-card flex items-center gap-3 rounded-lg border p-3">
      <div className="flex-1 space-y-0.5">
        <p className="text-sm font-medium">{inv.email}</p>
        <p className="text-muted-foreground text-xs">
          {roleLabel(inv.role, t)} · {t("settings.users.expiresLabel")}{" "}
          {new Date(inv.expires_at).toLocaleDateString("tr-TR")}
        </p>
      </div>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          if (!confirm(t("settings.users.revokeConfirm"))) return;
          revoke.mutate(inv.id, {
            onSuccess: () => toast.success(t("settings.users.revoked")),
            onError: (err) => toast.error(formatApiErrorMessage(err)),
          });
        }}
        disabled={revoke.isPending}
        className="gap-1 text-red-700 hover:text-red-900"
      >
        <Trash2 className="size-3.5" aria-hidden /> {t("common.cancel")}
      </Button>
    </li>
  );
}
