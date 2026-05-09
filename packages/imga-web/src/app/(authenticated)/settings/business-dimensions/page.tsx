"use client";

// Sprint 9.3 B — /settings/business-dimensions config page.
//
// Operator turns dimensions on/off, gives them display labels, and
// optionally maps them to a CSV header for the upload pipeline.
// Each dimension is configured independently.

import { Layers3, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

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
import { formatApiErrorMessage } from "@/lib/api-client";

const DIMENSIONS: ReadonlyArray<{ key: DimensionKey; default_label: string }> = [
  { key: "business_segment", default_label: "Müşteri Segmenti" },
  { key: "product_line", default_label: "Ürün Grubu" },
  { key: "channel", default_label: "Kanal" },
  { key: "customer_tier", default_label: "Müşteri Kademesi" },
];

export default function BusinessDimensionsPage() {
  const list = useBusinessDimensions();

  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-start gap-2">
        <Layers3 className="text-primary mt-1 size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            İş Boyutları
          </h1>
          <p className="text-muted-foreground text-sm">
            Review&apos;ları segment, ürün, kanal, müşteri kademesi gibi
            boyutlar üzerinden kırın. Her boyut bağımsız aç/kapat.
          </p>
        </div>
      </header>

      {list.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> Yükleniyor…
        </div>
      ) : (
        <div className="space-y-3">
          {DIMENSIONS.map((d) => {
            const config = list.data?.find((x) => x.dimension === d.key);
            return (
              <DimensionCard
                key={d.key}
                dimensionKey={d.key}
                defaultLabel={d.default_label}
                existing={config}
              />
            );
          })}
        </div>
      )}
    </main>
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
        onSuccess: () => toast.success("Boyut kaydedildi."),
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
            Aktif
          </label>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1">
            <Label className="text-xs">Görünen ad</Label>
            <Input value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">CSV kolon eşleşmesi (opsiyonel)</Label>
            <Input
              value={csvCol}
              onChange={(e) => setCsvCol(e.target.value)}
              placeholder="örn: musteri_segmenti"
            />
          </div>
          <div className="space-y-1 md:col-span-2">
            <Label className="text-xs">İzin verilen değerler (virgülle)</Label>
            <Input
              value={allowedRaw}
              onChange={(e) => setAllowedRaw(e.target.value)}
              placeholder="premium, basic, enterprise"
            />
            <p className="text-muted-foreground text-[10px]">
              Boş bırakılırsa serbest metin kabul edilir.
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            onClick={onSave}
            disabled={upsert.isPending}
          >
            {upsert.isPending ? "Kaydediliyor…" : "Kaydet"}
          </Button>
          {existing && (
            <Button
              size="sm"
              variant="ghost"
              disabled={remove.isPending}
              onClick={() => {
                if (!confirm("Boyut konfigürasyonunu sil?")) return;
                remove.mutate(dimensionKey, {
                  onSuccess: () => toast.success("Silindi."),
                  onError: (err) => toast.error(formatApiErrorMessage(err)),
                });
              }}
              className="text-red-700 hover:text-red-900"
            >
              Sil
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
