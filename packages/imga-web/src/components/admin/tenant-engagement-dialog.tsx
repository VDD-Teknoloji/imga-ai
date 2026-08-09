"use client";

// Katılım eşikleri — süper yönetici düzenler.
//
// Bantlar artan sıralı bir listedir: her bant kendi min_pct'inden bir
// sonrakinin min_pct'ine kadar geçerlidir, ilk bant 0'dan başlar.
// Backend aynı kuralı Pydantic'te doğruluyor; buradaki ön-kontrol
// kullanıcıya 422 yerine anlaşılır bir mesaj göstermek için.

import { Plus, Trash2 } from "lucide-react";
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
import { Skeleton } from "@/components/ui/skeleton";
import {
  useAdminEngagementBands,
  useUpdateAdminEngagementBands,
} from "@/hooks/use-admin-engagement";
import type { EngagementBand } from "@/hooks/use-engagement";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { AdminTenantSummary } from "@/lib/types";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tenant: AdminTenantSummary;
}

const MAX_BANDS = 8;

interface DraftBand {
  minPct: string;
  label: string;
}

export function TenantEngagementDialog({ open, onOpenChange, tenant }: Props) {
  const { t } = useTranslation();
  const bands = useAdminEngagementBands(open ? tenant.id : undefined);
  const update = useUpdateAdminEngagementBands();
  const [draft, setDraft] = useState<DraftBand[] | null>(null);

  // Sunucudan gelen bantlar ilk kez düştüğünde (veya kurum
  // değiştiğinde) taslağı doldur — render sırası koşullu setState.
  const [seededFor, setSeededFor] = useState<string | null>(null);
  if (bands.data && seededFor !== tenant.id) {
    setSeededFor(tenant.id);
    setDraft(toDraft(bands.data.bands));
  }

  const rows = draft ?? [];

  function patchRow(index: number, patch: Partial<DraftBand>) {
    setDraft(rows.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  function addRow() {
    if (rows.length >= MAX_BANDS) return;
    const last = rows[rows.length - 1];
    const nextMin = last ? Number(last.minPct) + 1 : 0;
    setDraft([...rows, { minPct: String(nextMin), label: "" }]);
  }

  function removeRow(index: number) {
    setDraft(rows.filter((_r, i) => i !== index));
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const parsed: EngagementBand[] = [];
    for (const row of rows) {
      const minPct = Number(row.minPct);
      if (!Number.isFinite(minPct) || minPct < 0 || minPct > 100) {
        toast.error(t("admin.engagement.error.minPctRange"));
        return;
      }
      if (!row.label.trim()) {
        toast.error(t("admin.engagement.error.labelRequired"));
        return;
      }
      parsed.push({ min_pct: minPct, label: row.label.trim() });
    }
    const [first, ...rest] = parsed;
    if (first === undefined) {
      toast.error(t("admin.engagement.error.atLeastOne"));
      return;
    }
    if (first.min_pct !== 0) {
      toast.error(t("admin.engagement.error.startsAtZero"));
      return;
    }
    let previousMin = first.min_pct;
    for (const band of rest) {
      if (band.min_pct <= previousMin) {
        toast.error(t("admin.engagement.error.ascending"));
        return;
      }
      previousMin = band.min_pct;
    }
    try {
      await update.mutateAsync({ tenantId: tenant.id, bands: parsed });
      toast.success(t("admin.engagement.toast.saved"));
      onOpenChange(false);
    } catch (err) {
      toast.error(t("admin.engagement.toast.saveError"), {
        description: t(describeError(err)),
      });
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{t("admin.engagement.title")}</DialogTitle>
            <DialogDescription>
              {t("admin.engagement.desc", { tenant: tenant.name })}
            </DialogDescription>
          </DialogHeader>

          {bands.isLoading ? (
            <Skeleton className="h-40" />
          ) : bands.isError ? (
            <p className="text-destructive text-sm">{t("admin.common.listError")}</p>
          ) : (
            <div className="space-y-3">
              {bands.data?.is_default ? (
                <p className="text-muted-foreground text-xs">
                  {t("admin.engagement.usingDefaults")}
                </p>
              ) : null}
              <div className="grid grid-cols-[7rem_1fr_auto] items-end gap-2">
                <Label className="text-xs">{t("admin.engagement.field.minPct")}</Label>
                <Label className="text-xs">{t("admin.engagement.field.label")}</Label>
                <span />
                {rows.map((row, index) => (
                  <BandRow
                    key={index}
                    row={row}
                    index={index}
                    onPatch={patchRow}
                    onRemove={removeRow}
                    removable={rows.length > 1}
                  />
                ))}
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-1.5"
                onClick={addRow}
                disabled={rows.length >= MAX_BANDS}
              >
                <Plus className="size-3.5" aria-hidden />
                {t("admin.engagement.addBand")}
              </Button>
              <p className="text-muted-foreground text-xs">{t("admin.engagement.help")}</p>
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={update.isPending}
            >
              {t("admin.action.cancel")}
            </Button>
            <Button type="submit" disabled={update.isPending || bands.isLoading}>
              {update.isPending ? t("admin.engagement.saving") : t("admin.engagement.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function BandRow({
  row,
  index,
  onPatch,
  onRemove,
  removable,
}: {
  row: DraftBand;
  index: number;
  onPatch: (index: number, patch: Partial<DraftBand>) => void;
  onRemove: (index: number) => void;
  removable: boolean;
}) {
  const { t } = useTranslation();
  return (
    <>
      <Input
        type="number"
        min={0}
        max={100}
        step="0.1"
        value={row.minPct}
        onChange={(e) => onPatch(index, { minPct: e.target.value })}
        aria-label={t("admin.engagement.field.minPct")}
      />
      <Input
        value={row.label}
        maxLength={64}
        onChange={(e) => onPatch(index, { label: e.target.value })}
        aria-label={t("admin.engagement.field.label")}
      />
      <Button
        type="button"
        variant="ghost"
        size="sm"
        disabled={!removable}
        onClick={() => onRemove(index)}
        className="text-destructive hover:text-destructive"
        aria-label={t("admin.engagement.removeBand")}
      >
        <Trash2 className="size-3.5" aria-hidden />
      </Button>
    </>
  );
}

function toDraft(bands: EngagementBand[]): DraftBand[] {
  return bands.map((b) => ({ minPct: String(b.min_pct), label: b.label }));
}

/** i18n anahtarı döndürür; çağıran `t(...)` ile çevirir. */
function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return "admin.error.notFound";
    if (err.status === 403) return "admin.error.superAdminRequired";
    if (err.status === 422) return "admin.error.invalidForm";
  }
  return "admin.error.unexpected";
}
