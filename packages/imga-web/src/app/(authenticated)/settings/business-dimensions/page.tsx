"use client";

// Sprint 9.3 B — /settings/business-dimensions config page.
//
// Operator turns dimensions on/off, gives them display labels, and
// optionally maps them to a CSV header for the upload pipeline.
// Each dimension is configured independently.

import { Layers3, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { RequireRole } from "@/components/auth/require-role";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  type DimensionConfig,
  type DimensionKey,
  useBusinessDimensions,
  useDeleteBusinessDimension,
  useUpsertBusinessDimension,
} from "@/hooks/use-business-dimensions";
import {
  type FactField,
  type FactMapping,
  useFactMappings,
  useSaveFactMappings,
} from "@/hooks/use-operations";
import { formatApiErrorMessage } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";

const DIMENSIONS: ReadonlyArray<{
  key: DimensionKey;
  default_label_key: string;
}> = [
  { key: "business_segment", default_label_key: "settings.dimensions.default.segment" },
  { key: "product_line", default_label_key: "settings.dimensions.default.productLine" },
  { key: "channel", default_label_key: "settings.dimensions.default.channel" },
  { key: "customer_tier", default_label_key: "settings.dimensions.default.customerTier" },
];

export default function BusinessDimensionsPage() {
  return (
    <RequireRole level="admin">
      <BusinessDimensionsPageInner />
    </RequireRole>
  );
}

function BusinessDimensionsPageInner() {
  const list = useBusinessDimensions();
  const { t } = useTranslation();

  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-start gap-2">
        <Layers3 className="text-primary mt-1 size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {t("settings.dimensions.title")}
          </h1>
          <p className="text-muted-foreground text-sm">
            {t("settings.dimensions.subtitle")}
          </p>
        </div>
      </header>

      {list.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
        </div>
      ) : (
        <div className="space-y-3">
          {DIMENSIONS.map((d) => {
            const config = list.data?.find((x) => x.dimension === d.key);
            return (
              <DimensionCard
                key={d.key}
                dimensionKey={d.key}
                defaultLabel={t(d.default_label_key)}
                existing={config}
              />
            );
          })}
        </div>
      )}

      <FactMappingsSection />
    </main>
  );
}

// --- 2026-08-21 (Operasyonel analitik) — "Operasyonel Veri Eşlemeleri" ---
//
// DimensionCard'ın aksine burada satır-başı değil TEK Kaydet düğmesi
// var (görev sözleşmesi): PUT /tenants/me/fact-mappings tam-replace
// bekliyor, bu yüzden 13 satır tek mutation'da toplu gönderiliyor.
// Yalnız csv_column_mapping'i dolu olan satırlar gönderilir — boş
// bırakılan bir satır sunucuda o fact_field'ın eşlemesini temizler
// (tam-replace semantiği, kasıtlı).

const FACT_FIELDS: ReadonlyArray<{ key: FactField; labelKey: string }> = [
  { key: "sla_resolution_status", labelKey: "settings.factMappings.slaResolutionStatus" },
  {
    key: "sla_first_response_status",
    labelKey: "settings.factMappings.slaFirstResponseStatus",
  },
  { key: "resolution_time", labelKey: "settings.factMappings.resolutionTime" },
  { key: "first_response_time", labelKey: "settings.factMappings.firstResponseTime" },
  { key: "csat", labelKey: "settings.factMappings.csat" },
  { key: "agent_interactions", labelKey: "settings.factMappings.agentInteractions" },
  { key: "customer_interactions", labelKey: "settings.factMappings.customerInteractions" },
  { key: "compensation_status", labelKey: "settings.factMappings.compensationStatus" },
  { key: "freight_cost", labelKey: "settings.factMappings.freightCost" },
  { key: "goods_cost", labelKey: "settings.factMappings.goodsCost" },
  { key: "refund_reason", labelKey: "settings.factMappings.refundReason" },
  { key: "delivery_status", labelKey: "settings.factMappings.deliveryStatus" },
  { key: "delivery_detail", labelKey: "settings.factMappings.deliveryDetail" },
];

type FactRowState = Record<FactField, { csv: string; enabled: boolean }>;

function defaultFactRowState(): FactRowState {
  const out = {} as FactRowState;
  for (const f of FACT_FIELDS) out[f.key] = { csv: "", enabled: true };
  return out;
}

function rowStateFromMappings(data: FactMapping[]): FactRowState {
  const byField = new Map(data.map((m) => [m.fact_field, m]));
  const out = {} as FactRowState;
  for (const f of FACT_FIELDS) {
    const existing = byField.get(f.key);
    out[f.key] = {
      csv: existing?.csv_column_mapping ?? "",
      enabled: existing?.enabled ?? true,
    };
  }
  return out;
}

function FactMappingsSection() {
  const { t } = useTranslation();
  const list = useFactMappings();
  const save = useSaveFactMappings();
  const [rows, setRows] = useState<FactRowState>(defaultFactRowState);

  // DimensionCard ile aynı desen — sunucu satırı ilk render'dan sonra
  // gelir, geldiğinde local state'i onunla senkronize eder.
  useEffect(() => {
    if (list.data) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRows(rowStateFromMappings(list.data));
    }
  }, [list.data]);

  function onSave() {
    const body: FactMapping[] = FACT_FIELDS.map((f) => ({
      fact_field: f.key,
      csv_column_mapping: rows[f.key].csv.trim(),
      enabled: rows[f.key].enabled,
    })).filter((m) => m.csv_column_mapping.length > 0);

    save.mutate(body, {
      onSuccess: () => toast.success(t("settings.factMappings.saved")),
      onError: (err) => toast.error(formatApiErrorMessage(err)),
    });
  }

  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <div>
          <h2 className="text-sm font-semibold">{t("settings.factMappings.title")}</h2>
          <p className="text-muted-foreground text-xs">
            {t("settings.factMappings.subtitle")}
          </p>
        </div>

        {list.isLoading ? (
          <div className="flex items-center gap-2 p-4 text-sm">
            <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
          </div>
        ) : (
          <div className="divide-border divide-y">
            {FACT_FIELDS.map((f) => (
              <div
                key={f.key}
                className="grid grid-cols-1 items-center gap-2 py-2.5 sm:grid-cols-[1fr_2fr_auto]"
              >
                <Label className="text-sm">{t(f.labelKey)}</Label>
                <Input
                  value={rows[f.key].csv}
                  onChange={(e) =>
                    setRows((prev) => ({
                      ...prev,
                      [f.key]: { ...prev[f.key], csv: e.target.value },
                    }))
                  }
                  placeholder={t("settings.dimensions.csvPlaceholder")}
                />
                <label className="inline-flex cursor-pointer items-center gap-2 text-xs whitespace-nowrap">
                  <input
                    type="checkbox"
                    checked={rows[f.key].enabled}
                    onChange={(e) =>
                      setRows((prev) => ({
                        ...prev,
                        [f.key]: { ...prev[f.key], enabled: e.target.checked },
                      }))
                    }
                    className="size-3.5"
                  />
                  {t("settings.dimensions.active")}
                </label>
              </div>
            ))}
          </div>
        )}

        <Button size="sm" onClick={onSave} disabled={save.isPending || list.isLoading}>
          {save.isPending ? t("settings.common.saving") : t("common.save")}
        </Button>
      </CardContent>
    </Card>
  );
}

function DimensionCard({
  dimensionKey,
  defaultLabel,
  existing,
}: {
  dimensionKey: DimensionKey;
  defaultLabel: string;
  existing: DimensionConfig | undefined;
}) {
  const upsert = useUpsertBusinessDimension();
  const remove = useDeleteBusinessDimension();
  const { t } = useTranslation();
  const [label, setLabel] = useState<string>(
    existing?.display_label ?? defaultLabel,
  );
  const [enabled, setEnabled] = useState<boolean>(existing?.enabled ?? false);
  const [csvCol, setCsvCol] = useState<string>(
    existing?.csv_column_mapping ?? "",
  );
  const [allowedRaw, setAllowedRaw] = useState<string>(
    (existing?.allowed_values ?? []).join(", "),
  );

  // Keep local state in sync if the server-side row arrives later
  // (initial render fires before useQuery resolves).
  useEffect(() => {
    if (existing) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLabel(existing.display_label);
      setEnabled(existing.enabled);
      setCsvCol(existing.csv_column_mapping ?? "");
      setAllowedRaw((existing.allowed_values ?? []).join(", "));
    }
  }, [existing]);

  function onSave() {
    const allowed_values = allowedRaw
      .split(",")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    upsert.mutate(
      {
        dimension: dimensionKey,
        body: {
          display_label: label,
          enabled,
          allowed_values,
          csv_column_mapping: csvCol || null,
        },
      },
      {
        onSuccess: () => toast.success(t("settings.dimensions.saved")),
        onError: (err) => toast.error(formatApiErrorMessage(err)),
      },
    );
  }

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">{label}</h2>
          <label className="inline-flex cursor-pointer items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="size-3.5"
            />
            {t("settings.dimensions.active")}
          </label>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1">
            <Label className="text-xs">{t("settings.dimensions.displayName")}</Label>
            <Input value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">{t("settings.dimensions.csvMapping")}</Label>
            <Input
              value={csvCol}
              onChange={(e) => setCsvCol(e.target.value)}
              placeholder={t("settings.dimensions.csvPlaceholder")}
            />
          </div>
          <div className="space-y-1 md:col-span-2">
            <Label className="text-xs">{t("settings.dimensions.allowedValues")}</Label>
            <Input
              value={allowedRaw}
              onChange={(e) => setAllowedRaw(e.target.value)}
              placeholder="premium, basic, enterprise"
            />
            <p className="text-muted-foreground text-[10px]">
              {t("settings.dimensions.allowedHelp")}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            onClick={onSave}
            disabled={upsert.isPending}
          >
            {upsert.isPending
              ? t("settings.common.saving")
              : t("common.save")}
          </Button>
          {existing && (
            <Button
              size="sm"
              variant="ghost"
              disabled={remove.isPending}
              onClick={() => {
                if (!confirm(t("settings.dimensions.deleteConfirm"))) return;
                remove.mutate(dimensionKey, {
                  onSuccess: () => toast.success(t("settings.dimensions.deleted")),
                  onError: (err) => toast.error(formatApiErrorMessage(err)),
                });
              }}
              className="text-red-700 hover:text-red-900"
            >
              {t("settings.common.delete")}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
