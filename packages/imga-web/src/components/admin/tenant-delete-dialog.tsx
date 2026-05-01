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
export function TenantDeleteDialog({
  open,
  onOpenChange,
  tenant,
}: TenantDeleteDialogProps) {
  const remove = useDeleteAdminTenant();

  async function handleConfirm() {
    try {
      await remove.mutateAsync({ tenantId: tenant.id });
      toast.success("Tenant silindi", {
        description: `${tenant.name} arşivlendi (soft-delete).`,
      });
      onOpenChange(false);
    } catch (err) {
      toast.error("Silinemedi", {
        description: describeError(err),
      });
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{tenant.name}&apos;ı sil</AlertDialogTitle>
          <AlertDialogDescription>
            Bu tenant&apos;ı silmek üzeresin. Tüm verisi soft-delete
            edilir; gerekirse veritabanı seviyesinde geri yüklenebilir.
            Aktif kullanıcılar artık bu tenant&apos;ı göremez.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={remove.isPending}>
            Vazgeç
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirm}
            disabled={remove.isPending}
          >
            {remove.isPending ? "Siliniyor..." : "Sil"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return "Tenant zaten silinmiş veya bulunamadı.";
    if (err.status === 403) return "Bu işlem için süper-yönetici yetkisi gerekli.";
  }
  return "Beklenmeyen bir hata oluştu.";
}
