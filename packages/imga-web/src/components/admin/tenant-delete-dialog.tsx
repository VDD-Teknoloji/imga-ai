"use client";

import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useDeleteAdminTenant } from "@/hooks/use-admin-tenants";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { AdminTenantSummary } from "@/lib/types";

interface TenantDeleteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tenant: AdminTenantSummary;
}

/**
 * Soft-delete confirm. Backend sets `deleted_at = now()`, doesn't
 * cascade — tickets and users stay intact, the tenant just stops
 * surfacing in non-admin lists.
 */
export function TenantDeleteDialog({ open, onOpenChange, tenant }: TenantDeleteDialogProps) {
  const remove = useDeleteAdminTenant();
  const { t } = useTranslation();

  async function handleConfirm() {
    try {
      await remove.mutateAsync({ tenantId: tenant.id });
      toast.success(t("admin.tenantDelete.toast.deletedTitle"), {
        description: t("admin.tenantDelete.toast.deletedDesc", {
          name: tenant.name,
        }),
      });
      onOpenChange(false);
    } catch (err) {
      toast.error(t("admin.tenantDelete.toast.deleteError"), {
        description: t(describeError(err)),
      });
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {t("admin.tenantDelete.title", { name: tenant.name })}
          </AlertDialogTitle>
          <AlertDialogDescription>{t("admin.tenantDelete.desc")}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={remove.isPending}>
            {t("admin.action.cancel")}
          </AlertDialogCancel>
          <AlertDialogAction onClick={handleConfirm} disabled={remove.isPending}>
            {remove.isPending ? t("admin.tenantDelete.deleting") : t("admin.tenantDelete.delete")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/** i18n anahtarı döndürür; çağıran `t(...)` ile çevirir. */
function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return "admin.tenantDelete.error.notFound";
    if (err.status === 403) return "admin.error.superAdminRequired";
  }
  return "admin.error.unexpected";
}
