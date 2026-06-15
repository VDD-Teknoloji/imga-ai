"use client";

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
import { useUpdateAdminTenant } from "@/hooks/use-admin-tenants";
import { ApiError } from "@/lib/api-client";
import type {
  AdminTenantSummary,
  AutomationMode,
  TenantPlanTier,
} from "@/lib/types";
import { AUTOMATION_MODE_LABELS, PLAN_TIER_LABELS } from "@/lib/user-helpers";

interface TenantEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tenant: AdminTenantSummary;
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
 * Slug intentionally not editable — backend treats it as URL-stable
 * after creation. Only name + plan_tier + automation_mode flow
 * through PATCH.
 */
export function TenantEditDialog({
  open,
  onOpenChange,
  tenant,
}: TenantEditDialogProps) {
  const update = useUpdateAdminTenant();
  const [name, setName] = useState(tenant.name);
  const [planTier, setPlanTier] = useState<TenantPlanTier>(tenant.plan_tier);
  const [automationMode, setAutomationMode] = useState<AutomationMode>(
    tenant.automation_mode,
  );

  // Re-sync the form when the parent swaps which tenant we're editing,
  // using the render-time conditional setState pattern.
  const [lastTenantId, setLastTenantId] = useState(tenant.id);
  if (lastTenantId !== tenant.id) {
    setLastTenantId(tenant.id);
    setName(tenant.name);
    setPlanTier(tenant.plan_tier);
    setAutomationMode(tenant.automation_mode);
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const patch = {
      name: name !== tenant.name ? name.trim() : undefined,
      plan_tier: planTier !== tenant.plan_tier ? planTier : undefined,
      automation_mode:
        automationMode !== tenant.automation_mode ? automationMode : undefined,
    };
    if (
      patch.name === undefined &&
      patch.plan_tier === undefined &&
      patch.automation_mode === undefined
    ) {
      onOpenChange(false);
      return;
    }
    try {
      await update.mutateAsync({ tenantId: tenant.id, patch });
      toast.success("Kurum güncellendi");
      onOpenChange(false);
    } catch (err) {
      toast.error("Güncellenemedi", {
        description: describeError(err),
      });
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Kurum düzenle</DialogTitle>
            <DialogDescription>
              Slug değiştirilemez. İsim ve plan / otomasyon ayarlarını
              güncelleyebilirsin.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="edit-name">İsim</Label>
            <Input
              id="edit-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={255}
              required
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="edit-slug">Slug (değişmez)</Label>
            <Input id="edit-slug" value={tenant.slug} disabled readOnly />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="edit-plan">Plan</Label>
              <Select
                value={planTier}
                onValueChange={(v) => setPlanTier(v as TenantPlanTier)}
              >
                <SelectTrigger id="edit-plan">
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
              <Label htmlFor="edit-automation">Otomasyon</Label>
              <Select
                value={automationMode}
                onValueChange={(v) =>
                  setAutomationMode(v as AutomationMode)
                }
              >
                <SelectTrigger id="edit-automation">
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

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={update.isPending}
            >
              Vazgeç
            </Button>
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? "Kaydediliyor..." : "Kaydet"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return "Kurum bulunamadı.";
    if (err.status === 403) return "Bu işlem için süper-yönetici yetkisi gerekli.";
    if (err.status === 422) return "Form alanları geçersiz.";
  }
  return "Beklenmeyen bir hata oluştu.";
}
