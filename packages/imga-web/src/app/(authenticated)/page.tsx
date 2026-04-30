"use client";

import { useAuthStore } from "@/lib/auth-store";

/**
 * Placeholder dashboard. The real overview (SHI, crisis count,
 * category distribution, recent tickets) ships in Sprint 7.6.3.
 * Today this page only proves the auth flow and the active-tenant
 * binding work end to end.
 */
export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const activeContext = useAuthStore((s) => s.activeContext);
  const availableTenants = useAuthStore((s) => s.availableTenants);

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-8">
      <header className="flex flex-col gap-1">
        <h1 className="text-3xl font-semibold tracking-tight">imga.ai</h1>
        <p className="text-muted-foreground text-sm">
          Sprint 7.6.1 — auth foundation. Dashboard 7.6.3&apos;te.
        </p>
      </header>

      <section className="bg-card rounded-lg border p-6">
        <h2 className="text-lg font-medium">Aktif oturum</h2>
        <dl className="mt-4 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-muted-foreground">Kullanıcı</dt>
          <dd>
            {user?.full_name} <span className="text-muted-foreground">({user?.email})</span>
          </dd>
          <dt className="text-muted-foreground">Aktif tenant</dt>
          <dd>
            {activeContext?.tenant_name ?? "—"}
            {activeContext?.tenant_slug ? (
              <span className="text-muted-foreground"> ({activeContext.tenant_slug})</span>
            ) : null}
          </dd>
          <dt className="text-muted-foreground">Rol</dt>
          <dd>{activeContext?.role ?? "—"}</dd>
          <dt className="text-muted-foreground">Erişilebilir tenant&apos;lar</dt>
          <dd>{availableTenants.length}</dd>
        </dl>
      </section>
    </main>
  );
}
