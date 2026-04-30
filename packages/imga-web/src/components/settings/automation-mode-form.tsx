"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { useUpdateAutomationMode } from "@/hooks/use-tenant-config";
import type { AutomationMode } from "@/lib/types";
import { cn } from "@/lib/utils";

interface AutomationModeFormProps {
  current: AutomationMode;
}

interface ModeOption {
  value: AutomationMode;
  label: string;
  description: string;
}

const OPTIONS: ReadonlyArray<ModeOption> = [
  {
    value: "manual",
    label: "Manuel",
    description:
      "Otomatik ticket yaratılmaz. Sınıflandırma sonuçları yalnızca öneri olarak gösterilir; ekibin kendisi ticket açar.",
  },
  {
    value: "semi_auto",
    label: "Yarı otomatik",
    description:
      "Sınıflandırma confidence > 0.7 ve sentiment < -0.5 olduğunda ticket otomatik açılır. Diğer durumlarda öneri olarak kalır.",
  },
  {
    value: "full_auto",
    label: "Tam otomatik",
    description:
      "Negatif sentiment yakalanan her şikâyet için ticket otomatik açılır. Yüksek hacimli operasyon için.",
  },
];

export function AutomationModeForm({ current }: AutomationModeFormProps) {
  const [selected, setSelected] = useState<AutomationMode>(current);
  // Resync local selection when the upstream snapshot changes (another
  // tab saved, mutation invalidated, etc). We use the React 19
  // "previous prop tracking" pattern instead of useEffect so the
  // re-render is the same one that already had to happen for `current`.
  const [lastCurrent, setLastCurrent] = useState<AutomationMode>(current);
  if (lastCurrent !== current) {
    setLastCurrent(current);
    setSelected(current);
  }
  const update = useUpdateAutomationMode();

  const isDirty = selected !== current;

  function handleSave() {
    update.mutate(
      { mode: selected },
      {
        onError: () => setSelected(current), // revert local state
      },
    );
  }

  return (
    <section className="bg-card space-y-4 rounded-lg border p-6">
      <header>
        <h2 className="text-lg font-semibold tracking-tight">Otomasyon modu</h2>
        <p className="text-muted-foreground text-sm">
          Sınıflandırılan negatif yorumlar için ticket yaratma politikası.
        </p>
      </header>

      <RadioGroup
        value={selected}
        onValueChange={(v) => setSelected(v as AutomationMode)}
        className="gap-3"
      >
        {OPTIONS.map((opt) => (
          <Label
            key={opt.value}
            htmlFor={`automation-${opt.value}`}
            className={cn(
              "flex cursor-pointer items-start gap-3 rounded-md border p-4 transition-colors",
              "hover:bg-muted/40",
              selected === opt.value && "border-primary bg-primary/5",
            )}
          >
            <RadioGroupItem
              value={opt.value}
              id={`automation-${opt.value}`}
              className="mt-0.5"
            />
            <div className="flex flex-col gap-1">
              <span className="text-sm font-medium">{opt.label}</span>
              <span className="text-muted-foreground text-xs leading-relaxed">
                {opt.description}
              </span>
            </div>
          </Label>
        ))}
      </RadioGroup>

      <div className="flex justify-end">
        <Button onClick={handleSave} disabled={!isDirty || update.isPending}>
          {update.isPending ? "Kaydediliyor..." : "Kaydet"}
        </Button>
      </div>
    </section>
  );
}
