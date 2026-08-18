"use client";

// WS1 — kurum terim sözlüğü editörü. /settings/profile ve
// TenantCreateDialog'un (Adım 2) her ikisi de bunu paylaşır: satır
// başına terim + opsiyonel not, ekle/sil. Kalıcılık çağırana ait
// (PATCH /tenants/me/profile ya da POST /admin/tenants gövdesi) —
// bu bileşen yalnız bellek-içi listeyi düzenler.

import { Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TERMINOLOGY_MAX, type TerminologyEntry } from "@/hooks/use-onboarding";
import { useTranslation } from "@/lib/i18n/use-translation";

const TERM_MAX_LENGTH = 128;
const NOTE_MAX_LENGTH = 500;

interface TerminologyEditorProps {
  value: TerminologyEntry[];
  onChange: (next: TerminologyEntry[]) => void;
  max?: number;
}

export function TerminologyEditor({
  value,
  onChange,
  max = TERMINOLOGY_MAX,
}: TerminologyEditorProps) {
  const { t } = useTranslation();

  function updateRow(index: number, patch: Partial<TerminologyEntry>) {
    onChange(value.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function removeRow(index: number) {
    onChange(value.filter((_, i) => i !== index));
  }

  function addRow() {
    if (value.length >= max) return;
    onChange([...value, { term: "", note: "" }]);
  }

  return (
    <div className="space-y-2">
      <Label>{t("settings.terminology.label")}</Label>
      <p className="text-muted-foreground text-xs">{t("settings.terminology.help")}</p>

      {value.length > 0 && (
        <div className="space-y-2">
          {value.map((row, i) => (
            <div key={i} className="flex items-start gap-2">
              <Input
                value={row.term}
                onChange={(e) => updateRow(i, { term: e.target.value })}
                placeholder={t("settings.terminology.termPlaceholder")}
                maxLength={TERM_MAX_LENGTH}
                aria-label={t("settings.terminology.termLabel")}
                className="flex-1"
              />
              <Input
                value={row.note ?? ""}
                onChange={(e) => updateRow(i, { note: e.target.value })}
                placeholder={t("settings.terminology.notePlaceholder")}
                maxLength={NOTE_MAX_LENGTH}
                aria-label={t("settings.terminology.noteLabel")}
                className="flex-[2]"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => removeRow(i)}
                aria-label={t("settings.terminology.removeAria")}
              >
                <X className="size-4" aria-hidden />
              </Button>
            </div>
          ))}
        </div>
      )}

      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={addRow}
        disabled={value.length >= max}
        className="gap-1.5"
      >
        <Plus className="size-3.5" aria-hidden /> {t("settings.terminology.add")}
      </Button>
      <p className="text-muted-foreground text-xs tabular-nums">
        {t("settings.terminology.count", { n: value.length, max })}
      </p>
    </div>
  );
}
