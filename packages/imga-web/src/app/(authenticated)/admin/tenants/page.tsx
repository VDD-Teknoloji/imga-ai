"use client";

import { Building2, MailPlus, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { TenantCreateDialog } from "@/components/admin/tenant-create-dialog";
import { TenantDeleteDialog } from "@/components/admin/tenant-delete-dialog";
import { TenantEditDialog } from "@/components/admin/tenant-edit-dialog";
import { TenantInviteDialog } from "@/components/admin/tenant-invite-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAdminTenants } from "@/hooks/use-admin-tenants";
import { useAuthStore } from "@/lib/auth-store";
import { formatFullDate } from "@/lib/date-format";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { AdminTenantSummary } from "@/lib/types";
import { AUTOMATION_MODE_LABELS, PLAN_TIER_LABELS } from "@/lib/user-helpers";

/**
 * Super-admin tenant CRUD page. Sidebar already gates the nav item
 * on `is_super_admin`, but the page also self-guards in case the URL
 * is hit directly — non-admins see "Yetkiniz yok" instead of an
 * inscrutable 403 from the list endpoint.
 */
export default function AdminTenantsPage() {
  const isSuperAdmin = useAuthStore((s) => s.user?.is_super_admin ?? false);
  if (!isSuperAdmin) {
    return <ForbiddenView />;
  }
  return <AdminTenantsBody />;
}

function ForbiddenView() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto w-full max-w-3xl p-6 md:p-8">
      <div className="bg-card space-y-2 rounded-lg border p-8 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("admin.tenants.forbidden.title")}
        </h1>
        <p className="text-muted-foreground text-sm">{t("admin.tenants.forbidden.desc")}</p>
      </div>
    </main>
  );
}

function AdminTenantsBody() {
  const { t } = useTranslation();
  const tenants = useAdminTenants();
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<AdminTenantSummary | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AdminTenantSummary | null>(null);
  const [inviteTarget, setInviteTarget] = useState<AdminTenantSummary | null>(null);

  const liveTenants = (tenants.data ?? []).filter((tenant) => tenant.deleted_at === null);

  return (
    <main className="mx-auto w-full max-w-7xl space-y-6 p-6 md:p-8">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight md:text-3xl">
            <Building2 className="text-primary size-5 md:size-6" aria-hidden />
            {t("admin.tenants.title")}
          </h1>
          <p className="text-muted-foreground text-sm">{t("admin.tenants.subtitle")}</p>
        </div>
        <Button onClick={() => setCreateOpen(true)} className="gap-2">
          <Plus className="size-4" aria-hidden />
          {t("admin.tenants.new")}
        </Button>
      </header>

      {tenants.isLoading ? (
        <SkeletonTable />
      ) : tenants.isError ? (
        <p className="text-destructive py-12 text-center text-sm">{t("admin.tenants.loadError")}</p>
      ) : liveTenants.length === 0 ? (
        <EmptyState onCreate={() => setCreateOpen(true)} />
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("admin.field.name")}</TableHead>
                <TableHead className="hidden md:table-cell">{t("admin.field.slug")}</TableHead>
                <TableHead>{t("admin.field.plan")}</TableHead>
                <TableHead className="hidden lg:table-cell">
                  {t("admin.field.automation")}
                </TableHead>
                <TableHead className="hidden xl:table-cell">
                  {t("admin.tenants.col.created")}
                </TableHead>
                <TableHead className="text-right">{t("admin.tenants.col.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {liveTenants.map((tenant) => (
                <TableRow key={tenant.id}>
                  <TableCell className="font-medium">{tenant.name}</TableCell>
                  <TableCell className="text-muted-foreground hidden font-mono text-xs md:table-cell">
                    {tenant.slug}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">
                      {PLAN_TIER_LABELS[tenant.plan_tier] ?? tenant.plan_tier}
                    </Badge>
                  </TableCell>
                  <TableCell className="hidden lg:table-cell">
                    <Badge variant="secondary">
                      {AUTOMATION_MODE_LABELS[tenant.automation_mode]}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground hidden text-xs xl:table-cell">
                    {formatFullDate(tenant.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setEditTarget(tenant)}
                        className="gap-1.5"
                      >
                        <Pencil className="size-3.5" aria-hidden />
                        <span className="hidden sm:inline">{t("admin.tenants.action.edit")}</span>
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setInviteTarget(tenant)}
                        className="gap-1.5"
                      >
                        <MailPlus className="size-3.5" aria-hidden />
                        <span className="hidden sm:inline">{t("admin.tenants.action.invite")}</span>
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setDeleteTarget(tenant)}
                        className="text-destructive hover:text-destructive gap-1.5"
                      >
                        <Trash2 className="size-3.5" aria-hidden />
                        <span className="hidden sm:inline">{t("admin.tenants.action.delete")}</span>
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <TenantCreateDialog open={createOpen} onOpenChange={setCreateOpen} />
      {editTarget ? (
        <TenantEditDialog
          open={editTarget !== null}
          onOpenChange={(o) => !o && setEditTarget(null)}
          tenant={editTarget}
        />
      ) : null}
      {deleteTarget ? (
        <TenantDeleteDialog
          open={deleteTarget !== null}
          onOpenChange={(o) => !o && setDeleteTarget(null)}
          tenant={deleteTarget}
        />
      ) : null}
      {inviteTarget ? (
        <TenantInviteDialog
          open={inviteTarget !== null}
          onOpenChange={(o) => !o && setInviteTarget(null)}
          tenant={inviteTarget}
        />
      ) : null}
    </main>
  );
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="bg-card flex flex-col items-center gap-3 rounded-lg border p-12 text-center">
      <Building2 className="text-muted-foreground size-10" aria-hidden />
      <div className="space-y-1">
        <h2 className="text-base font-medium">{t("admin.tenants.empty.title")}</h2>
        <p className="text-muted-foreground text-sm">{t("admin.tenants.empty.desc")}</p>
      </div>
      <Button onClick={onCreate} className="mt-2 gap-2">
        <Plus className="size-4" aria-hidden />
        {t("admin.tenants.new")}
      </Button>
    </div>
  );
}

function SkeletonTable() {
  return (
    <div className="rounded-lg border">
      <div className="space-y-2 p-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-4 py-2">
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="hidden h-4 w-20 md:block" />
            <Skeleton className="h-5 w-16" />
            <Skeleton className="hidden h-5 w-20 lg:block" />
            <Skeleton className="hidden h-4 w-32 xl:block" />
            <Skeleton className="h-7 w-32" />
          </div>
        ))}
      </div>
    </div>
  );
}
