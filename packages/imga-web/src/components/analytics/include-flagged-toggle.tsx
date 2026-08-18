"use client";

// 2026-08-18 (Dalga 3, WS2) — "Düşük kaliteli veriyi dahil et" switch.
//
// Paylaşılan bileşen: /insights filtre şeridi + ana sayfa (dashboard)
// filtre çubuğu aynı görünümü kullanır. Varsayılan kapalı (backend
// include_flagged=false default'uyla aynı) — açıkken küçük bir uyarı
// rozeti gösterilir ki kullanıcı sayıların neden değiştiğini anlasın.
// State URL'de yaşar; bu bileşen saf controlled (url-state-patterns.md).

import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { useTranslation } from "@/lib/i18n/use-translation";

interface Props {
  checked: boolean;
  onChange: (next: boolean) => void;
  id?: string;
}

export function IncludeFlaggedToggle({
  checked,
  onChange,
  id = "include-flagged-toggle",
}: Props) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex items-center gap-2">
        <Switch
          id={id}
          size="sm"
          checked={checked}
          onCheckedChange={onChange}
          aria-label={t("insights.filter.includeFlaggedAria")}
        />
        <Label htmlFor={id} className="text-muted-foreground cursor-pointer text-xs font-medium">
          {t("insights.filter.includeFlaggedLabel")}
        </Label>
      </div>
      {checked && (
        <span className="bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300 inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium">
          {t("insights.filter.includeFlaggedBadge")}
        </span>
      )}
    </div>
  );
}
